# Install Grille

Grille lays a card over a long document and shows an agent only the pages that answer its question, with any passage written to steer the agent withheld. It is one piece of the Panoply. The screen is deterministic and always on; the embedder, the scorer and the relay each improve it, and each one's absence is reported rather than fatal. These steps are written for the agent doing the install; the user answers only the questions marked as theirs.

## What it does

- `sift FILE --ask Q` splits a PDF, a saved web page or a text file into pages, ranks them against the question, screens them and returns the best few.
- `fetch URL --ask Q` gets a page over plain HTTP, with no JavaScript, and sifts it. `--decipher` adds a chat model that returns only the lines answering the question, each checked word for word against the page.
- `screen FILE` screens a whole document without ranking; `show ID` prints a withheld span on purpose.
- `verify URL...` prints status, final address, type and redirect count per URL.

A withheld span is replaced by one line naming the reason and an id. It never enters the agent's context unless the agent asks for it with `grille show`.

## Step 1. Install the command

```
brew tap jack-com/panoply
brew trust --formula jack-com/panoply/grille
brew install jack-com/panoply/grille
```

Homebrew installs poppler with it, for reading PDFs. Without Homebrew, `uv tool install git+https://github.com/JACK-COM/grille` does the same, and poppler comes from the system's package manager. Run `grille selftest` and expect a line starting `selftest ok`.

## Step 2. An embedder, for ranking by meaning

Without one, `sift` ranks by shared words and says so. Either works:

- **ollama**: install it, then `ollama pull nomic-embed-text`. Grille starts the server when it is not running.
- **fastembed**, in-process with no server, in the virtualenv every Panoply piece shares. If Locket is installed and its venv exists, Grille already uses it. Otherwise make one with Homebrew's Python:

```
$(brew --prefix python@3.14)/bin/python3.14 -m venv ~/.panoply/venv
~/.panoply/venv/bin/python -m pip install fastembed
```

`PANOPLY_VENV` names another location for every piece at once; `embed.venv` in `grille.json` names one for Grille alone.

## Step 3. The relay for --decipher (the user's choice)

`--decipher` needs a chat model, and Grille ships without one, because no default fits every machine. Until the user chooses, every Grille command prints a one-line reminder. Ask the user which of these they want:

- **A local server they already run** (ollama, LM Studio, llama.cpp, vLLM). Run `grille configure relay --detect`, which lists the servers answering on their usual ports with their models and prints the line to set each one. Offer the user that list.
- **A hosted API.** `grille configure relay --url https://HOST/v1 --model NAME --api-key-env VAR`, with the key exported as `VAR` in the user's shell profile. Never write the key into `grille.json`. A hosted model sees the screened page text.
- **None.** `grille configure relay --off` turns `--decipher` off and ends the reminder.

A command can stand behind the model, or alone: `--fallback "COMMAND"` runs it with the prompt on stdin and reads the answer from stdout, with `{system}` in any argument replaced by the system prompt. Keep that command's tools off, because it reads untrusted page text.

## Step 4. The scorer for --score

`--score` asks a scorer whether each returned page tries to steer an automated reader, and withholds a page at or above the scorer's threshold. The default scorer is Augur (`brew install jack-com/panoply/augur`), whose threshold was measured and ships with Grille. Without Augur, `--score` marks each page unscored and the pattern screen still runs.

Any command can stand in for Augur if it reads one JSON request on stdin (`questions`, `text`, `subject`) and prints `{"answers": {"instructs_agent": {"noul": P}}}` with P from 0 to 1:

```
grille configure score --command "my-scorer --json"
grille calibrate pages.json --write
```

A new scorer withholds nothing until `grille calibrate` has measured its threshold on labelled pages the user actually reads (`grille calibrate -h` shows the file). A threshold never transfers from one scorer to another.

## Step 5. Prove it

```
grille check
```

It names each part: poppler, the embedder, the scorer and its threshold, the relay, the settings file and any misspelled key in it. It exits 1 while poppler is missing, the relay is neither set up nor turned off, or `grille.json` has a problem. `grille schema` writes `~/.grille/grille.schema.json` for an editor.

## Step 6. Report

Tell the user, in five lines or fewer: the version (`grille --version`), how `sift` ranks (embedder or word overlap), the scorer and whether it is calibrated, the relay or that it is off, and anything left for them to do.

## Removal

`brew uninstall jack-com/panoply/grille`, then `rm -r ~/.grille` for the settings. Withheld spans live under the system's temporary directory and are swept after seven days.
