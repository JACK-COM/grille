<p align="center">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/grille-dark.svg">
  <img src="docs/grille-light.svg" alt="Grille" width="112">
</picture>
</p>

# Grille

*Guard what you read.* One piece of [the Panoply](https://github.com/JACK-COM/homebrew-panoply).

Cardano's grille was a sheet with windows cut in it, laid over a letter so only the words that mattered showed through. Grille does that for an AI agent reading a long document, such as a manufacturer's PDF, a saved web page or a text dump: it returns the eight pages that answer the agent's question instead of all eighty. On the way it withholds any passage written to steer the agent, along with shell commands, hidden characters, and any text a web page hides from a human reader. A withheld passage stays retrievable with `grille show`, so nothing is dropped.

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

Python 3.9 or later, standard library only, and poppler (`pdftotext`, `pdftoppm`) for PDFs. Ranking by meaning uses the same embedder as Locket; `--score` uses Augur by default; `--decipher` uses a chat model you choose. `fetch` runs no JavaScript, so a page that renders in the browser stays browser work. Tested on macOS and Linux (Debian, Python 3.12); on Windows, run it under WSL.

## Releasing

`make version` (or `version-minor`, `version-major`) computes the next version from `__version__` and hands it to `scripts/release.sh X.Y.Z`, which checks the panoply-lib copies, stamps the version, runs the selftest, tags and pushes, then moves the formula in [the tap](https://github.com/JACK-COM/homebrew-panoply) to the new tarball and names any guide page the release has moved past. `make test` runs the checks alone.
