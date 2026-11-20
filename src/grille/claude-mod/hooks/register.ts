import type { Register } from 'claude-code'

// --decipher measured up to 77 s on a live page, and 200 s once when the relay
// timed out and its fallback answered; grille's own bound is 30 s per redirect
// hop, 120 s for the relay and 120 s for its fallback, so this covers a fetch
// with no redirect, not every one. Whether the host caps a tool call below this
// is unknown.
const TIMEOUT_MS = 240_000
const DEADLINE_S = 225

// grille's own error lines, the only stderr passed to the model: a fetch
// failure quotes the server's reason phrase and final URL, which a hostile
// server writes.
const GRILLE_LINE = /^grille: [a-z][a-z ,-]*/

// grille fetch --decipher exits 5 when no relay answered and hands back the
// sifted pages whole: screened, but never deciphered, so the mod refuses it.
// By exit code, never by the text: a page can print anything.
const RELAY_FAILED = 5

const refuse = (url: string, why: string) => ({
  deny: `grille refused ${url}; WebFetch is routed through grille and has no unscreened fallback. ${why}`,
})

// Answers WebFetch without running it: the page goes through grille, whose
// screen runs before any model reads it. Every failure refuses the call rather
// than falling back to WebFetch, because the fallback is the unscreened path
// this mod exists to close, and a page could ask for that failure.
export const register: Register = on => {
  on('tool.call', { tool: 'WebFetch' }, async ($, e, next) => {
    if (!/^https?:\/\//i.test(e.url)) return refuse(e.url, 'Only http and https URLs are fetched.')
    if (e.offset) return refuse(e.url, 'grille answers from the whole page, so offset is not supported; ask a narrower prompt instead.')

    // Answering without `next` skips core's permission check, so a
    // WebFetch(domain:...) deny rule would not bind. tool.check settles allow
    // and deny; its ask comes before the mode or a dialog settles it, so an ask
    // runs core's own path and its result is discarded unread: one extra fetch,
    // whose small-model summary no one sees.
    // Claude Code 2.1.329 runs WebFetch inside its built-in web-fetch subagent,
    // where tool.check throws `no tool named "WebFetch" in this session` (an
    // agentId does not help). A check that throws is treated as an ask, so
    // core's own permission path decides before grille runs. The catch also
    // takes an abort, deliberately: the ask path still fails closed. There every
    // fetch pays the ask path's discarded core fetch, allowed ones included.
    const verdict = await $.tool
      .check({ tool: 'WebFetch', input: { url: e.url, prompt: e.prompt } })
      .catch(() => ({ decision: 'ask' as const, reason: undefined }))
    if (verdict.decision === 'deny') return { deny: verdict.reason ?? `WebFetch to ${e.url} is denied by a permission rule.` }
    // Only a verdict this mod knows proceeds: one the host adds later refuses until read.
    if (verdict.decision !== 'allow' && verdict.decision !== 'ask') {
      return refuse(e.url, `The permission check answered ${String(verdict.decision)}, which this mod does not act on.`)
    }
    if (verdict.decision === 'ask') {
      // A declined prompt comes back as an error result, not a deny, so any
      // error refuses: grille runs only on a fetch core actually let through.
      const core = await next(e)
      if (core.deny !== undefined) return core
      if (core.isError) return refuse(e.url, 'WebFetch was not permitted, or its own fetch failed, so grille did not run.')
    }

    // The mod ships inside grille's libexec folder, so grille.py is found
    // beside it rather than through an install-location lookup.
    const grille = `${$.plugin.root}/../grille.py`
    const started = Date.now()

    // The host's environment lacks CLAUDE_CODE_SESSION_ID (only Bash children
    // get it), so without GRILLE_SESSION withheld spans land in the `default`
    // store, where the session's own `grille show <id>` never looks. A failed
    // lookup falls back to that store rather than refusing the fetch.
    const session = await $.session.id().catch(() => undefined)

    let ran
    try {
      // `--ask=` and `--` keep a prompt or URL that starts with a dash from
      // being read as a flag (a URL of `--help` otherwise prints usage, exit 0).
      // `--split` asks each part of a compound prompt on its own: one ranking
      // for a five-part prompt left three topics' best chunks out.
      ran = await $.process.run(
        [grille, 'fetch', '--decipher', '--split', `--ask=${e.prompt}`, '--', e.url],
        {
          timeoutMs: TIMEOUT_MS,
          // grille's own deadline, short of this kill: past it grille stops its stages and
          // refuses (exit 5) instead of being killed with every finished stage lost
          env: {
            PANOPLY_DEADLINE: String(Date.now() / 1000 + DEADLINE_S),
            ...(session && { GRILLE_SESSION: session }),
          },
        },
      )
    } catch {
      return refuse(e.url, 'grille could not run or ran past its time limit.')
    }

    if (ran.exitCode === RELAY_FAILED) {
      return refuse(e.url, 'The relay failed, so the page was screened but not deciphered; run `grille fetch` by hand to read it.')
    }
    if (ran.exitCode !== 0) {
      const line = ran.stderr.trim().split('\n').find(l => GRILLE_LINE.test(l))
      return refuse(e.url, line ? (line.match(GRILLE_LINE)?.[0] ?? '').trim() : `grille exited ${ran.exitCode}.`)
    }
    if (!ran.stdout.trim() || ran.isStdoutTruncated) return refuse(e.url, 'grille returned no complete answer.')

    // code and codeText are fixed: grille exits non-zero on any failed fetch,
    // so a result here followed a successful one; bytes counts grille's answer.
    return {
      result: {
        bytes: ran.stdout.length,
        code: 200,
        codeText: 'OK',
        result: ran.stdout,
        durationMs: Date.now() - started,
        url: e.url,
      },
    }
  }).catch(($, e) => refuse(e.url, `The grille mod failed: ${$.plugin.name} hook error.`))
}
