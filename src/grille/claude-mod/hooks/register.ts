import type { Register } from 'claude-code'

// --decipher measured up to 77 s on a live page, and 200 s once when the relay
// timed out and its fallback answered; grille's own bound is 30 s per redirect
// hop, 120 s for the relay and 120 s for its fallback, so this covers a fetch
// with no redirect, not every one. Whether the host caps a tool call below this
// is unknown.
const TIMEOUT_MS = 240_000

// grille's own error lines, the only stderr passed to the model: a fetch
// failure quotes the server's reason phrase and final URL, which a hostile
// server writes.
const GRILLE_LINE = /^grille: [a-z][a-z ,-]*/

// decipher() exits 0 when the relay dies and hands back the sifted pages
// whole: screened, but never deciphered, so the mod refuses it.
const RELAY_FAILED = /^relay failed \(/m

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
    const verdict = await $.tool.check({ tool: 'WebFetch', input: { url: e.url, prompt: e.prompt } })
    if (verdict.decision === 'deny') return { deny: verdict.reason ?? `WebFetch to ${e.url} is denied by a permission rule.` }
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
        { timeoutMs: TIMEOUT_MS, ...(session && { env: { GRILLE_SESSION: session } }) },
      )
    } catch {
      return refuse(e.url, 'grille could not run or ran past its time limit.')
    }

    if (ran.exitCode !== 0) {
      const line = ran.stderr.trim().split('\n').find(l => GRILLE_LINE.test(l))
      return refuse(e.url, line ? (line.match(GRILLE_LINE)?.[0] ?? '').trim() : `grille exited ${ran.exitCode}.`)
    }
    if (RELAY_FAILED.test(ran.stdout)) return refuse(e.url, 'The relay failed, so the page was screened but not deciphered; run `grille fetch` by hand to read it.')
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
