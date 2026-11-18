"""The setup verbs: check the install, configure the scorer, the relay and the embedder,
calibrate the scorer's threshold, migrate old settings, uninstall.
"""
import argparse
import contextlib
import json
import math
import os
import re
import shlex
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
import _embed as embed
import _settings as panoply

from . import config
from . import net
from . import score
from . import screen
from . import store as spans


def _positive(value):
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return n


def cmd_check(a):
    ok = bool(shutil.which("pdftotext"))
    print(f"pdftotext: {'ok' if ok else 'missing (brew install poppler); sift and screen need it for PDFs'}")
    print(f"pdftoppm: {'ok' if shutil.which('pdftoppm') else 'missing; only --render needs it'}")
    try:
        sources = embed.apply_config(config.embed_layers())
        name, model = embed.resolve_backend()
        print(f"embedder: {name} ({model}" + (f"; {sources['model'][1]})" if name == "ollama" else ")"))
    except Exception as e:
        print(f"embedder: none reachable ({str(e).splitlines()[0][:80]}); sift falls back to word overlap")
    for finding in config.manifest_findings():
        print(finding)
    shared = panoply.load()[1]
    for finding in shared:
        print(finding)
    if config.legacy_note():
        print(config.legacy_note())
    cmd, withhold, why = config.score_settings()
    found = shutil.which(cmd[0])
    print(f"score: {' '.join(cmd)}: " + (f"not on PATH; --score marks pages unscored" if not found else
          f"withholds at {withhold} ({why})" if withhold is not None else f"unscored, {why}"))
    r = config.relay_settings()
    if r is None:
        print(f"relay: {config.RELAY_SETUP}")
    elif r is False:
        print("relay: turned off in grille.json; --decipher refuses")
    else:
        print("relay: " + (f"{r['model']} at {r['url']} ({r.get('api') or 'openai'} API)" if r.get("url") else "no model")
              + (f", fallback {Path(r['fallback'][0]).name}" if r.get("fallback") else "")
              + "; not called here (`grille fetch URL --ask Q --decipher` calls it)")
    print(f"settings: {config._home() / 'grille.json'}")
    print(f"store: {spans.store_dir()}")
    print(f"fetch: urllib, no JavaScript, {net.FETCH_CAP >> 20} MB cap, {net.REDIRECT_CAP} redirects, "
          f"{net.FETCH_TIMEOUT} s per hop to fetch and {net.VERIFY_TIMEOUT} s to verify; reachability is not checked here")
    return 0 if ok and r is not None and not config.manifest_findings() and not panoply.unreadable(shared) else 1


def cmd_uninstall(a):
    """Remove what Grille made, and the shared venv when no other piece still uses it; the
    settings and the command itself are listed, never removed, like every Panoply piece."""
    store = spans.store_root()
    venv, others = embed.shared_venv("grille")
    print("uninstall will remove:")
    if store.is_dir():
        print(f"  directory {store}  (withheld spans, every session)")
    if venv:
        print(f"  directory {venv}  (the embedder venv and its model; no other Panoply piece is on PATH)")
    if not store.is_dir() and not venv:
        print("  nothing it made")
    if a.dry_run:
        return 0
    if (store.is_dir() or venv) and not a.yes:
        if sys.stdin.isatty():
            if input("proceed? [y/N] ").strip().lower() not in ("y", "yes"):
                print("nothing removed")
                return 1
        else:
            print("nothing removed; rerun with --yes")
            return 1
    for d in (store, venv):
        if d and d.is_dir():
            shutil.rmtree(d)
            print(f"removed {d}")
    if venv:
        with contextlib.suppress(OSError):
            venv.parent.rmdir()             # ~/.panoply, once nothing else is in it
    print("\nleft for you, if you want it gone completely:")
    if others:
        print(f"  the embedder venv {embed.VENV}, which {' and '.join(others)} still use{'s' if len(others) == 1 else ''}")
    elif embed.VENV.is_dir() and not venv:
        print(f"  the embedder venv you named: {embed.VENV}")
    if config._home().is_dir():
        print(f"  the settings: rm -r {config._home()}   (grille.json and its schema)")
    if isinstance(panoply.load()[0].get("grille"), dict):
        print(f"  Grille's embedder overrides: the \"grille\" section of {panoply.path()}")
    print("  the command:  brew uninstall jack-com/panoply/grille   (or `uv tool uninstall grille`)")
    return 0


LOCAL_SERVERS = (("ollama", "http://127.0.0.1:11434/v1"), ("LM Studio", "http://127.0.0.1:1234/v1"),
                 ("llama.cpp", "http://127.0.0.1:8080/v1"), ("vLLM", "http://127.0.0.1:8000/v1"))


_NOT_CHAT = re.compile(r"embed|rerank|\bbge\b|minilm|\be5\b", re.I)


def _models_at(base, timeout=1.5):
    """The chat model names an OpenAI-compatible server lists, or None when nothing
    answers. A server lists its embedding models too, and one of those cannot relay."""
    try:
        with net._opener().open(base.rstrip("/") + "/models", timeout=timeout) as r:
            data = json.loads(r.read(1 << 20))
        return [m["id"] for m in data.get("data", [])
                if isinstance(m, dict) and m.get("id") and not _NOT_CHAT.search(m["id"])]
    except (urllib.error.URLError, OSError, ValueError, AttributeError):
        return None


def cmd_migrate(a):
    """Every step an upgrade leaves for this machine, each a no-op once done. A release
    that needs a new step adds it here."""
    try:
        moved = config.migrate_embed()
    except (OSError, TimeoutError) as e:
        print(f"grille: could not move grille.json's embed settings ({e}); Grille still reads them", file=sys.stderr)
        return 1
    if moved and moved.startswith("note:"):  # the Panoply settings could not be read: nothing moved
        print(f"grille: {moved[len('note: '):]}", file=sys.stderr)
        return 1
    print(moved or "migrate: nothing pending")
    return 0


# The configure flags each setting takes; any other one given is refused, never ignored.
CONFIGURE_FLAGS = {
    "relay": ("detect", "url", "model", "api", "api_key_env", "think", "fallback", "off"),
    "score": ("command", "withhold", "reset"),
    "embedder": ("model", "ollama_host", "autostart", "venv", "shared", "reset"),
}


_FLAG_OFF = {"detect": False, "think": False, "off": False, "shared": False, "reset": False}


def cmd_configure(a):
    foreign = [k for ks in CONFIGURE_FLAGS.values() for k in dict.fromkeys(ks)
               if k not in CONFIGURE_FLAGS[a.what] and getattr(a, k) not in (None, _FLAG_OFF.get(k))]
    if foreign:
        flags = ", ".join("--" + ("global" if k == "shared" else k.replace("_", "-")) for k in dict.fromkeys(foreign))
        sys.exit(f"grille: {flags} {'is not a' if len(foreign) == 1 else 'are not'} {a.what} setting{'s' * (len(foreign) > 1)}")
    try:
        moved = config.migrate_embed()
    except (OSError, TimeoutError) as e:
        moved = f"warning: could not move grille.json's embed settings ({e}); Grille still reads them"
    if moved:
        print(moved, file=sys.stderr)
    if a.what == "embedder":
        return _configure_embedder(a)
    m = config._manifest()
    if a.what == "relay":
        if a.detect:
            hits = [(n, u, ms) for n, u in LOCAL_SERVERS if (ms := _models_at(u)) is not None]
            if not hits:
                print("no local chat server answered on "
                      + ", ".join(f"{n} ({u})" for n, u in LOCAL_SERVERS)
                      + ". Start one, or name a hosted API with --url, --model and --api-key-env.")
                return 1
            for n, u, ms in hits:
                print(f"{n} at {u}: " + (", ".join(ms[:12]) + (" ..." if len(ms) > 12 else "") if ms
                                         else "no chat models listed; load or pull one, or name it with --model"))
                for model in ms[:1]:
                    print(f"  grille configure relay --url {u} --model {model}")
            return 0
        if a.off:
            m["relay"] = False
        else:
            if not ((a.url and a.model) or a.fallback):
                sys.exit("grille: give --url and --model, or --fallback, or --off, or --detect")
            r = {k: v for k, v in (("url", a.url), ("model", a.model), ("api", a.api),
                                  ("api_key_env", a.api_key_env)) if v}
            if a.think:
                r["think"] = True
            if a.fallback:
                r["fallback"] = shlex.split(a.fallback)
                if not r["fallback"]:
                    sys.exit("grille: --fallback is empty")
            if a.url and (a.api or "openai") == "openai":
                listed = _models_at(a.url)
                if listed is None:
                    print(f"warning: nothing answered at {a.url}/models; saved anyway")
                elif listed and a.model not in listed:
                    print(f"warning: {a.url} does not list {a.model}; it lists {', '.join(listed[:8])}")
            m["relay"] = r
    else:
        s = m.get("score") if isinstance(m.get("score"), dict) else {}
        if a.reset:
            m.pop("score", None)
        else:
            if a.command is not None:
                cmd = shlex.split(a.command)
                if not cmd:
                    sys.exit("grille: --command is empty")
                if cmd != s.get("command"):
                    # a threshold belongs to the scorer that earned it
                    s = {"command": cmd}
                    if a.withhold is None and cmd != config.DEFAULT_SCORER:
                        print("note: this scorer has no threshold, so --score marks pages unscored "
                              "until `grille calibrate ITEMS --write` measures one")
            if a.withhold is not None:
                if not (0 < a.withhold <= 1):
                    sys.exit("grille: --withhold must be above 0 and at most 1")
                s["withhold"] = a.withhold
            m["score"] = s
    print(f"wrote {config._write_manifest(m)}")
    return 0


def _configure_embedder(a):
    """Write Grille's own embed settings, or with --global the ones every piece shares, then
    show what Grille now uses and where each value comes from."""
    keys = {"model": a.model, "ollama_host": a.ollama_host, "venv": a.venv, "autostart": a.autostart}
    clearing = {k for k, v in keys.items() if v == "default"}
    changes = {k: v for k, v in keys.items() if v not in (None, "default")}
    empty = [k for k, v in changes.items() if v == ""]
    if empty:
        sys.exit(f"grille: --{empty[0].replace('_', '-')} is empty; pass `default` to remove the setting")
    if "venv" in changes:                   # absolute: a relative path would resolve against each run's cwd
        venv = os.path.expanduser(changes["venv"])
        if venv.startswith("~"):
            sys.exit(f"grille: --venv {changes['venv']}: no such user's home to expand")
        changes["venv"] = os.path.abspath(venv)
    if "ollama_host" in changes and not changes["ollama_host"].startswith(("http://", "https://")):
        sys.exit(f"grille: --ollama-host needs a scheme, e.g. http://{changes['ollama_host']}")
    if changes or clearing or a.reset:
        problems = []

        def change(data, findings):
            # only an unreadable file blocks: writing over it loses every piece's settings
            if panoply.unreadable(findings) and not a.reset:
                problems.extend(findings)
                return None
            return panoply.edit(data, "embed", changes, clearing, a.reset, None if a.shared else "grille")
        try:
            written = panoply.update(change)
        except TimeoutError as e:
            sys.exit(f"grille: not written: {e}")
        if problems:
            sys.exit(f"grille: {problems[0]}\nfix it, or pass --reset to start the file over "
                     "(the old one is kept as config.json.bak)")
        print(f"wrote {panoply.path()}" if written else "no change to write")
        for f in panoply.load()[1]:
            print(f"problem: {f}", file=sys.stderr)
        if a.shared:
            data = panoply.load()[0]
            for k in sorted(set(changes) | clearing | (set(embed.CONFIG_KEYS) if a.reset else set())):
                for p in panoply.overriding(data, "embed", k, usable=embed.usable):
                    print(f"note: {p} sets its own {k}, so this change does not reach {p}")
    print(f"embedder, as Grille uses it ({panoply.path()}; source: env, grille's own section, global, or default)")
    for key, (value, src) in config.apply_embed().items():
        shown = ("on" if value else "off") if key == "autostart" else value
        print(f"  {key:12s} {str(shown):40s} {src}")
    return 0


def _auroc(pos, neg):
    """Probability a random positive outscores a random negative, ties counted half."""
    return sum((p > n) + 0.5 * (p == n) for p in pos for n in neg) / (len(pos) * len(neg))


def cmd_calibrate(a):
    """Score labelled pages with the configured scorer and suggest the threshold that
    withholds every labelled injection, naming what that costs in clean pages withheld."""
    try:
        spec = json.loads(Path(a.items).read_text())
        items = spec["items"] if isinstance(spec, dict) else spec
        rows = [(str(it["id"]), it["text"], it["labels"]["instructs_agent"]) for it in items]
    except (OSError, ValueError, KeyError, TypeError) as e:
        sys.exit(f"grille: {a.items}: not an items file ({e}); each item needs id, text and "
                 "labels.instructs_agent")
    if not all(isinstance(t, str) and isinstance(y, bool) for _, t, y in rows):
        sys.exit("grille: every item needs a string text and a true or false labels.instructs_agent")
    pos_n = sum(y for *_, y in rows)
    if not pos_n or pos_n == len(rows):
        sys.exit("grille: calibration needs at least one injected page and one clean page")
    cmd, _, _ = config.score_settings()
    calls = sum(len(score.windows(screen._PLACEHOLDER.sub("", t))) for _, t, _ in rows)
    print(f"scoring {len(rows)} pages with {' '.join(cmd)}: {calls} calls", file=sys.stderr)
    scores = {}
    for i, t, y in rows:
        try:
            scores[i] = (score.score_text(cmd, t), y)
        except score.ScorerError as e:
            sys.exit(f"grille: the scorer failed on item {i}: {e}")
    pos = [p for p, y in scores.values() if y]
    neg = [p for p, y in scores.values() if not y]
    cut = math.floor(min(pos) * 100) / 100          # rounded down, so every injection stays at or above
    fp = sorted((i for i, (p, y) in scores.items() if not y and p >= cut), key=lambda i: -scores[i][0])
    auroc = _auroc(pos, neg)
    print(f"AUROC {auroc:.3f}; injections from {min(pos):.2f}, clean pages at most {max(neg):.2f}")
    if cut <= 0:
        print("an injection scored 0.00, so no threshold withholds every one; the scorer cannot "
              "screen these pages and nothing was written")
        return 1
    print(f"threshold {cut:.2f} withholds all {len(pos)} injections and {len(fp)} of {len(neg)} clean pages"
          + (f": {', '.join(fp[:10])}" if fp else ""))
    if not a.write:
        print("rerun with --write to save it for this scorer")
        return 0
    m = config._manifest()
    m["score"] = {"command": cmd, "withhold": cut,
                  "calibrated": {"items": len(rows), "auroc": round(auroc, 3), "clean_withheld": len(fp),
                                 "file": str(Path(a.items).resolve())}}
    print(f"wrote {config._write_manifest(m)}")
    return 0
