<p align="center">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/grille-dark.svg">
  <img src="docs/grille-light.svg" alt="Grille" width="112">
</picture>
</p>

# Grille

*Guard what you read.* One piece of [the Panoply](https://github.com/JACK-COM/homebrew-panoply).

Cardano's grille was a sheet with windows cut in it, laid over a letter so only the words that mattered showed through. Grille does that for an AI agent reading a long document, such as a manufacturer's PDF, a saved web page or a text dump: it returns the ten pages that answer the agent's question instead of all eighty. On the way it withholds any passage written to steer the agent, along with shell commands, hidden characters, and any text a web page hides from a human reader. A withheld passage stays retrievable with `grille show`, so nothing is dropped.

**[Read the Grille guide](https://github.com/JACK-COM/homebrew-panoply/blob/main/docs/grille/README.md)**: when to use it, a first run against a planted instruction, teaching your agent to reach for it, troubleshooting, and [how to make it yours](https://github.com/JACK-COM/homebrew-panoply/blob/main/docs/grille/make-it-yours.md): your own scorer, your own relay model, and settings.

## Install

```sh
brew tap jack-com/panoply
brew trust --formula jack-com/panoply/grille
brew install jack-com/panoply/grille
```

Or with [uv](https://docs.astral.sh/uv/): `uv tool install git+https://github.com/JACK-COM/grille`, with poppler from your package manager.

Then ask your agent to run `grille help install` and follow it. `grille check` names every part and what is missing.

## Requirements

Python 3.9 or later, numpy, and poppler (`pdftotext`, `pdftoppm`) for PDFs. Ranking by meaning uses the same embedder as Locket; `--score` uses Augur by default; `--decipher` uses a chat model you choose. `fetch` runs no JavaScript, so a page that renders in the browser stays browser work. Tested on macOS and Linux (Debian, Python 3.12); on Windows, run it under WSL.

## Security

Grille reads pages written by strangers for an AI agent that runs it without a terminal. It treats every page and every server as hostile.

- **A person confirms.** A setting that runs a program (a scorer, a relay fallback, ollama autostart), sends text off this machine (a relay or embedder host), sends a key, names a venv, changes the scorer or its threshold, or writes a calibration is written only when a person at a terminal types `yes`. Without a terminal nothing is written, and Grille prints the line for the person to run.
- **Redirects:** a redirect within the site, or to https on the same host, is followed. A redirect to another origin is reported for the caller to fetch, so the fetch passes their own permission check. From an origin the caller did not name as local, no hop reaches this machine or a private address.
- **What reaches the agent is screened.** Page text, headings, labels, links, URLs, content types, reason phrases and relay output all pass the screen. Patterns match on a normalised copy, so lookalike, full-width and invisible characters hide nothing. A page cannot write Grille's own placeholders or headings. Terminal controls never reach the output.
- **Under `fetch --decipher`, nothing uncleared passes.** A page the scorer did not clear is withheld. A relay failure exits 5, and the WebFetch mod refuses on that code.
- **Every scan is bounded.** Pattern scans, HTML nesting, PDF object streams, pdftotext and every network read have bounds. One deadline runs from the mod through every stage.

These residuals are accepted:

- The screen is lexical: a paraphrased injection that matches no listed pattern reaches the scorer, the only layer that reads meaning.
- A single shell command padded past about 7 KB of non-space characters on one line escapes the windowed pattern scan.
- An agent that fakes a terminal passes the person check. Without Locket's hooks, an agent's own file tools can edit `~/.grille/grille.json` directly.

## Releasing

`make version` (or `version-minor`, `version-major`) computes the next version from `__version__` and hands it to `scripts/release.sh X.Y.Z`, which refuses a module over 800 lines, runs `make test`, stamps the version, tags and pushes, then moves the formula in [the tap](https://github.com/JACK-COM/homebrew-panoply) to the new tarball and names any guide page the release has moved past. `make test` checks the panoply-lib copies, runs `tests/` (stdlib unittest; `GRILLE_SRC` points the suites at another tree) and the install smoke check, `grille selftest`.
