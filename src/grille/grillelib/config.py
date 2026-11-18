"""Grille's settings: grille.json (its schema, the scorer and relay sections, the checks a
hand edit draws) and the shared embedder settings it layers under them.
"""
import json
import math
import os
from pathlib import Path

import _embed as embed
import _settings as panoply


# jev-1.13.0 on 117 real pages and 60 injected ones: negatives at most 0.07, positives
# from 0.68, run-to-run sd 0.031. The cut sits low because a withheld page costs one
# `grille show`, and a missed injection costs the session. Recalibrate on a backend change.
SCORE_WITHHOLD = 0.3


# --decipher's relay: a chat model the user names in grille.json, called bare, never through
# an agent: an agent reading untrusted page text would hold its tools and every server it
# spawns, a production write path included. A hosted model sends the screened text off the
# machine, which is why --decipher is on fetch (public pages) and not on sift (local files).
RELAY_TIMEOUT = 120


# --score's scorer: a command taking one JSON request on stdin and printing Augur's response
# shape, `answers.instructs_agent.noul` a probability. SCORE_WITHHOLD is calibrated for this
# command only; any other scorer stays unscored until it has a threshold of its own.
DEFAULT_SCORER = ["augur", "ask", "--request", "-", "--caller", "grille"]


SCORE_TIMEOUT = 120


_STR = {"type": "string"}


_ARGV = {"type": "array", "items": {"type": "string"}}


MANIFEST_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "$id": "grille.schema.json",
    "title": "Grille manifest (grille.json)",
    "description": "Grille's settings. Every key is optional; `grille configure` writes them.",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "$schema": {"type": "string", "description": "Editor hint only; ignored by Grille."},
        "score": {"type": "object", "additionalProperties": False, "properties": {
            "command": {**_ARGV, "description": "The --score command as an argument list: one JSON "
                        "request on stdin, `answers.instructs_agent.noul` on stdout. Default: Augur."},
            "withhold": {"type": "number", "description": "Withhold a page scoring this or above. "
                         "Measured by `grille calibrate --write`; it does not transfer between scorers."},
            "calibrated": {"type": "object", "description": "What the last calibration measured. Informational."}}},
        "relay": {"type": ["object", "boolean"], "additionalProperties": False,
                  "description": "--decipher's chat model, or false to turn --decipher off.", "properties": {
            "url": {"type": "string", "description": "Server base URL: http://127.0.0.1:1234/v1 for an "
                    "OpenAI-compatible server, http://127.0.0.1:11434 for ollama's own API."},
            "model": {"type": "string", "description": "The model name the server knows."},
            "api": {"type": "string", "description": "openai (default: LM Studio, llama.cpp, vLLM, ollama's /v1, "
                    "hosted APIs) or ollama (its /api/chat)."},
            "api_key_env": {"type": "string", "description": "Environment variable holding a bearer key, for a hosted API."},
            "key_host": {"type": "string", "description": "host:port the key may be sent to, written by "
                         "`grille configure relay` when a person confirms it; any other host gets no key."},
            "think": {"type": "boolean", "description": "ollama API only: send think, for a reasoning model."},
            "fallback": {**_ARGV, "description": "A command tried when the model fails: the prompt on stdin, "
                         "the answer on stdout; `{system}` in an argument becomes the system prompt."}}},
    },
}


RELAY_SETUP = ("--decipher is not set up: name a chat model with `grille configure relay --url URL "
               "--model NAME` (`grille configure relay --detect` lists the local servers answering), "
               "or turn it off with `grille configure relay --off`")


def _schema_lib():
    """The shared checker, panoply-lib's copy beside grille.py, which puts its directory on
    the path however Grille is installed."""
    import _manifest_schema
    return _manifest_schema


def _home():
    return Path(os.environ.get("GRILLE_HOME") or Path.home() / ".grille").expanduser()


def _manifest():
    """grille.json as a dict; {} when absent or unreadable, which `grille check` reports."""
    try:
        m = json.loads((_home() / "grille.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return m if isinstance(m, dict) else {}


def _write_manifest(m):
    home = _home()
    home.mkdir(parents=True, exist_ok=True)
    path = home / "grille.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def manifest_findings():
    """Structural problems in grille.json, as lines; [] when clean or absent. An older
    grille.json's embed section is named as moved rather than unknown."""
    found = _schema_lib().validate_file(_home() / "grille.json", MANIFEST_SCHEMA)
    if _legacy_embed() is not None:         # named by legacy_note instead, which is no problem
        found = [f for f in found if not f.startswith("manifest: unknown key 'embed'")]
    return ["grille.json" + (f[len("manifest"):] if f.startswith("manifest") else ": " + f) for f in found]


def legacy_note():
    """A line while grille.json still holds Grille 0.2's embed section, else None."""
    if _legacy_embed() is None:
        return None
    return f"note: grille.json's embed settings now belong in {panoply.path()}; `grille migrate` moves them"


def _legacy_embed():
    """The usable settings of grille.json's embed section from Grille 0.2, while it remains, else None."""
    e = _manifest().get("embed")
    # never `venv`: a venv's .pth files run on import, so only a person names one (configure embedder --venv)
    return {k: v for k, v in e.items() if k in embed.CONFIG_KEYS and k != "venv" and embed.usable(k, e)} \
        if isinstance(e, dict) else None


def embed_layers(data=None):
    """Grille's view of the embed settings, highest first: its own section of the Panoply
    settings, then grille.json's older section until it is moved, then the top level."""
    data = panoply.load(check=False)[0] if data is None else data
    own = data.get("grille") if isinstance(data.get("grille"), dict) else {}
    layers = [("grille", own.get("embed")), ("grille.json", _legacy_embed()), ("global", data.get("embed"))]
    return [(label, s) for label, s in layers if isinstance(s, dict) and s]


def apply_embed():
    """Put Grille's embed settings into the embedder, under the environment."""
    try:
        return embed.apply_config(embed_layers())
    except Exception:                       # nothing in a settings file may stop a run
        return embed.apply_config(None)


def migrate_embed():
    """Move grille.json's older embed section into Grille's own section of the Panoply
    settings, where a key already set there keeps its value, then drop it from grille.json.
    Leaves both files alone when the Panoply settings cannot be read. Returns a line, or None."""
    legacy = _legacy_embed()
    if legacy is None:
        return None
    raw = _manifest().get("embed")
    with panoply.lock():
        data, findings = panoply.load()
        if panoply.unreadable(findings):
            return f"note: {panoply.path()} cannot be read, so grille.json's embed settings stay put; fix it and rerun"
        own = dict(panoply.layers("grille", "embed", data)).get("grille", {})
        add = {k: v for k, v in legacy.items() if k not in own}
        if add:
            panoply.write_json(panoply.path(), panoply.edit(data, "embed", add, piece="grille"))
    m = _manifest()
    m.pop("embed", None)
    _write_manifest(m)
    kept = sorted(set(legacy) - set(add))
    dropped = sorted(set(raw) - set(legacy))
    return "\n".join([f"moved grille.json's embed settings into {panoply.path()}"
                      + (f" ({', '.join(sorted(add))})" if add else " (nothing usable to move)")]
                     + [f"note: kept Grille's own {', '.join(kept)} over grille.json's"] * bool(kept)
                     + [f"note: dropped what Grille never read: {', '.join(dropped)}"] * bool(dropped))


def write_schema():
    return _schema_lib().write_schema(MANIFEST_SCHEMA, _home() / "grille.schema.json")


def _probability(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and 0 <= v <= 1


def score_settings(m=None):
    """-> (command, withhold or None, why). The default scorer carries SCORE_WITHHOLD; any
    other command needs a threshold of its own, and a page it cannot threshold is unscored."""
    s = (_manifest() if m is None else m).get("score")
    s = s if isinstance(s, dict) else {}
    cmd = s.get("command") or DEFAULT_SCORER
    if not (isinstance(cmd, list) and all(isinstance(x, str) and x for x in cmd)):
        return DEFAULT_SCORER, None, "score.command in grille.json is not a list of arguments"
    w = s.get("withhold")
    if w is not None:
        if _probability(w) and w > 0:
            return cmd, w, "threshold from grille.json"
        return cmd, None, f"score.withhold={w!r} in grille.json is not a probability above 0"
    if cmd == DEFAULT_SCORER:
        return cmd, SCORE_WITHHOLD, "the default scorer's calibrated threshold"
    return cmd, None, "no calibrated threshold for this scorer (`grille calibrate ITEMS --write`)"


def relay_settings(m=None):
    """-> the relay dict, False when turned off, or None when not set up."""
    r = (_manifest() if m is None else m).get("relay")
    if r is False:
        return False
    if isinstance(r, dict) and ((r.get("url") and r.get("model")) or r.get("fallback")):
        return r
    return None


def host(url):
    """`host:port` of `url`, the port explicit: what a key is confirmed for."""
    from urllib.parse import urlparse
    u = urlparse(url)
    try:
        port = u.port or {"http": 80, "https": 443}.get(u.scheme, 0)
    except ValueError:
        port = 0
    return f"{(u.hostname or '').lower()}:{port}"
