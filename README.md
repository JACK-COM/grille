<p align="center">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/grille-dark.svg">
  <img src="docs/grille-light.svg" alt="Grille" width="112">
</picture>
</p>

# Grille

*Guard what you read.* One piece of [the Panoply](https://github.com/JACK-COM/homebrew-panoply).

Cardano's grille was a sheet with windows cut in it, laid over a letter so only the words that mattered showed through. Grille does that for an AI agent reading a long document: a manufacturer's PDF, a saved web page, a text dump. It returns the eight pages that answer the agent's question instead of all eighty, and on the way it withholds any passage written to steer the agent rather than inform the reader, along with shell commands and hidden characters.

A withheld passage is replaced by one line naming the reason and an id, and it stays retrievable: `grille show ID` prints it on purpose. A maintenance page that says "remove the cowl" is data, so nothing is ever dropped.

## Install

```
brew tap jack-com/panoply
brew trust --formula jack-com/panoply/grille
brew install jack-com/panoply/grille
```

Or with [uv](https://docs.astral.sh/uv/): `uv tool install git+https://github.com/JACK-COM/grille`, with poppler from your package manager.

Then ask your agent to run `grille help install` and follow it. Grille reminds you on every run until you either point `--decipher` at a chat model or turn it off.

## Use

```
grille sift manual.pdf --ask "What is the engine's time between overhaul?"
grille fetch https://example.com/spec --ask "What is the fuel capacity?" --decipher
grille screen page.html                         the whole document, screened, no ranking
grille show 3f9a1c                              a withheld span, deliberately
grille verify https://a.example https://b.example --json
grille check                                    every part, and what is missing
grille uninstall --dry-run                      what removal takes; the shared venv goes with the last piece
```

`--ask` repeats, one per topic, and the questions take turns filling `--pages`. `--score` adds a model's judgment to the pattern screen. `--render` writes pages with no text layer as PNGs, so the agent reads three scanned pages rather than eighty.

## The three parts you can swap

Each part improves Grille, and each one's absence is named on the output, never fatal.

**Ranking.** Pages are ranked by meaning with `nomic-embed-text`, served by ollama or by fastembed in-process, and by shared words when neither is there. The fastembed virtualenv is shared by every Panoply piece: `~/.panoply/venv`, or Locket's `~/.locket/venv` when that exists, or wherever `PANOPLY_VENV` points.

**The scorer behind `--score`.** By default [Augur](https://github.com/JACK-COM/augur) asks whether each page tries to make an automated reader act or misreport, and Grille withholds a page scoring 0.3 or above, a threshold measured on hand-labelled fetched pages. Any command can take Augur's place if it reads one JSON request on stdin and prints `{"answers": {"instructs_agent": {"noul": P}}}`:

```
grille configure score --command "my-scorer --json"
grille calibrate labelled-pages.json --write
```

A new scorer withholds nothing until `calibrate` has measured its threshold on your own labelled pages, because a threshold never transfers between scorers. Until then its pages read `unscored`, and the pattern screen still runs.

**The relay behind `--decipher`.** A chat model you choose reads the screened pages and returns only the lines that answer, and Grille keeps a line only if it appears word for word on the page. Grille speaks the OpenAI-compatible API (LM Studio, llama.cpp, vLLM, ollama's `/v1`, hosted APIs) and ollama's own:

```
grille configure relay --detect                 which local servers answer, with their models
grille configure relay --url http://127.0.0.1:1234/v1 --model qwen3-8b
grille configure relay --url https://api.example.com/v1 --model NAME --api-key-env EXAMPLE_API_KEY
grille configure relay --off
```

`--fallback "COMMAND"` adds a command tried when the model fails, with the prompt on stdin. The model is called with no tools, because it reads untrusted text; keep a fallback command's tools off for the same reason.

Grille reaches the network through the proxies in `HTTP_PROXY`, `HTTPS_PROXY` and `NO_PROXY` only, never those set in macOS System Settings: after asking macOS, Python on a Mac cannot start `pdftotext` or the scorer.

Settings live in `~/.grille/grille.json` (or `$GRILLE_HOME`). `grille schema` writes its schema for an editor, and `grille check` names any misspelled key.

## Requirements

Python 3.9 or later, standard library only, and poppler (`pdftotext`, `pdftoppm`) for PDFs. `fetch` runs no JavaScript, so a page that renders in the browser stays browser work. Tested on macOS and Linux (Debian, Python 3.12); on Windows, run it under WSL.

## Releasing

`make version` (or `version-minor`, `version-major`) computes the next version from `__version__` and hands it to `scripts/release.sh X.Y.Z`, which checks the panoply-lib copies, stamps the version, runs the selftest, tags and pushes, then moves the formula in [the tap](https://github.com/JACK-COM/homebrew-panoply) to the new tarball. `make test` runs the checks alone.
