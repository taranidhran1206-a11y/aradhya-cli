<p align="center"><img src="ara_code/assets/logo.png" width="120" alt="Aradhya"></p>

<h1 align="center">Aradhya Code</h1>

<p align="center"><b>Aradhya, a coding agent in your terminal.</b><br>
<a href="https://taranidhran1206-a11y.github.io/unknown-project/">Website</a> · <a href="#install">Install</a> · <a href="#commands">Commands</a></p>


Aradhya as a coding agent in your terminal. You tell her what you want in plain words. She reads your project, edits files (showing you the change first), runs commands and tests, keeps a to-do list while she works, and remembers each project's notes. It works on Windows, Linux, macOS, your EC2 server and Termux on Android.

![Welcome screen](docs/img/ara-welcome.png)

## Contents

- [Install](#install)
- [Your Gemini key](#your-gemini-key)
- [Using her](#using-her)
- [Commands](#commands)
- [Keys](#keys)
- [How careful she is](#how-careful-she-is)
- [What she can do](#what-she-can-do)
- [Project memory: ARADHYA.md](#project-memory-aradhyamd)
- [Sessions](#sessions)
- [Other brains: Hermes, OpenRouter, Ollama](#other-brains-hermes-openrouter-ollama)
- [Her logo in different terminals](#her-logo-in-different-terminals)
- [Settings](#settings)
- [Troubleshooting](#troubleshooting)

## Install

**Windows** (PowerShell):

```powershell
irm https://raw.githubusercontent.com/taranidhran1206-a11y/unknown-project/main/docs/install.ps1 | iex
```

**macOS, Linux and Termux**:

```bash
curl -fsSL https://taranidhran1206-a11y.github.io/unknown-project/install.sh | sh
```

That's it. The installer:
- checks for Python 3.9+ (on Windows it offers to install it with winget; on Termux it installs it with `pkg`),
- installs Aradhya Code into its own folder, `~/.aradhya/venv`, so your other Python projects are untouched,
- puts the `ara` command on your PATH,
- asks for your Gemini key once (press Enter to skip).

Run the same command again to **update**. To **uninstall**, run it with `ARA_UNINSTALL=1`:

```bash
curl -fsSL https://taranidhran1206-a11y.github.io/unknown-project/install.sh | ARA_UNINSTALL=1 sh
```
```powershell
$env:ARA_UNINSTALL=1; irm https://raw.githubusercontent.com/taranidhran1206-a11y/unknown-project/main/docs/install.ps1 | iex
```

**With pip instead** (any OS): `pip install "aradhya-code[full] @ https://github.com/taranidhran1206-a11y/unknown-project/archive/refs/heads/main.zip"`. On Termux leave out `[full]`: the Gemini SDK can't build on Android, and Aradhya Code talks to Gemini directly without it.

## Your Gemini key

She uses Google Gemini by default. Get a free key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey). The installer asks for it; to add or change it later, edit `~/.aradhya/.env`:

```
GEMINI_API_KEY=your-key-here
```

The installer saves it to `~/.aradhya/.env` for you. She also reads a `.env` in the folder you're working in.

## Using her

Go to a project folder and start her:

```bash
cd my-project
ara                                   # start a session
ara "the login test is failing, fix it"   # start with a request
ara -p "explain what this repo does"  # answer once and exit (good for scripts)
ara -c                                # continue the last session in this folder
ara -r                                # pick an earlier session to resume
```

Then talk to her normally. A typical session looks like this:

![A session](docs/img/ara-session.png)

Every action she takes shows as a line with a dot (`● Read(calc.py)`, `● Bash(npm test)`), and its result appears under it after `⎿`. Edits show the exact lines added (green) and removed (red). When she's done, she gives a short summary.

**Pointing at files.** Type `@` and start typing a filename to pick it from a list, for example `explain @src/app.py`.

**Running a command yourself.** Start the line with `!`, for example `!git status`. The input line turns pink and the command runs straight away. She sees the output too, so you can follow up with "why is that failing?".

## Commands

Type `/` to see this list with descriptions:

![Command menu](docs/img/ara-commands.png)

| Command | What it does |
|---|---|
| `/help` | Commands and keys |
| `/init` | Explores the project and writes `ARADHYA.md` so she understands it next time |
| `/clear` | Starts a fresh conversation (the old one stays saved) |
| `/compact` | Summarizes a long conversation to free up space (she also does this by herself when it gets very long) |
| `/mode` | Changes how careful she is: `default`, `accept-edits` or `yolo` |
| `/model` | Shows the model, or switches it: `/model gemini-3.8-flash` |
| `/resume` | Picks up an earlier session in this folder |
| `/todos` | Shows her current task list |
| `/status` | Folder, model, mode and tokens used |
| `/leo`, `/aradhya` | Switches persona: Leo is short, sharp and cold; Aradhya is warm |
| `/exit` | Quits (so does Ctrl+C twice, or Ctrl+D) |

## Keys

| Key | What it does |
|---|---|
| Enter | Send |
| Alt+Enter (or Esc then Enter) | New line in your message |
| Shift+Tab | Changes how careful she is (see below) |
| Esc | Stops her mid-answer, then you can redirect her |
| Ctrl+C | Clears what you've typed; press twice on an empty line to quit |
| `?` on an empty line | Shows the shortcuts |
| `@` | File picker |
| `!` at the start of a line | Run a shell command yourself |
| ↑ / ↓ | Your earlier messages |

## How careful she is

She never changes anything without asking unless you tell her she can. Before an edit she shows the change and waits:

![Approving an edit](docs/img/ara-permission.png)

Pick with the arrow keys and Enter, or press 1, 2 or 3:

1. **Yes**: do it this once.
2. **Yes, and don't ask again**: for edits, she stops asking for the rest of the session. For a command like `npm test`, she stops asking about `npm test` only.
3. **No**: she stops. Type what she should do instead, or just press Enter to stop her.

Reading files, searching and read-only commands (`ls`, `git status`, `git diff`, `cat`, `grep`…) never ask.

Shift+Tab (or `/mode`) switches between three modes. The current one shows under the input box.

| Mode | She asks before… |
|---|---|
| `default` | every edit and every command that changes something |
| `accept-edits` | commands only (file edits just happen) |
| `yolo` | nothing. Use this only in a project with git, so you can undo. |

You can also start in a mode: `ara --accept-edits` or `ara --yolo`.

## What she can do

| Tool | Shown as | Notes |
|---|---|---|
| Read a file | `Read(path)` | Reads before every edit, and refuses to edit a file she hasn't read |
| Edit a file | `Update(path)` | Replaces exact text, so it can't silently change the wrong place |
| Write a file | `Write(path)` | New files, or a full rewrite of one she has read |
| Find files | `Search(pattern)` | e.g. `**/*.py`, newest first |
| Search contents | `Grep("text")` | Uses ripgrep if installed |
| Run commands | `Bash(command)` | bash on Linux, macOS and Termux; PowerShell on Windows. `cd` carries over between commands. Stops after 2 minutes unless she asks for longer |
| Fetch a web page | `Fetch(url)` | Docs, raw files from GitHub, etc. |
| To-do list | `Update Todos` | For bigger jobs, so you can see her plan and progress |

Her instructions say not to commit, push, deploy or delete branches unless you ask, and not to print secrets from `.env` files. In `default` mode you approve every command anyway.

## Project memory: ARADHYA.md

`ARADHYA.md` is a short note about a project: what it is, how to build and test it, and its rules ("use tabs", "never touch the dynamic island code"). She reads it at the start of every session in that folder. Run `/init` once and she writes it for you; edit it whenever you like.

She reads these files and follows them:

- `~/.aradhya/ARADHYA.md`: your rules for every project
- `ARADHYA.md` in the project's main folder and any folder you're in below it
- `AGENTS.md` or `CLAUDE.md`, if a project already has one instead

## Sessions

Every conversation is saved per folder in `~/.aradhya/sessions/`. The welcome screen lists your recent ones. `ara -c` continues the last one, and `ara -r` or `/resume` lets you pick. When you quit, she shows how long you worked and how many tokens you used.

## Other brains: Hermes, OpenRouter, Ollama

Gemini is the default, but any service that speaks the OpenAI chat format works too:

```bash
ara --provider hermes                                # Hermes Agent's API server on this machine (:8642)
ara --provider hermes --base-url http://<ec2-ip>:8642/v1
ara --provider openrouter --model meta-llama/llama-3.3-70b-instruct   # needs ARA_API_KEY=<OpenRouter key>
ara --provider ollama --model qwen2.5-coder          # a local model through Ollama
ara --base-url https://any-openai-compatible/v1 --model name
```

`/model` switches the model inside a session.

## Her logo in different terminals

On start she shows her logo. How it's drawn depends on what your terminal can do, and she works this out by asking the terminal itself, so you don't set anything up.

| Terminal | Logo |
|---|---|
| Windows Terminal 1.22 or newer | Sharp picture |
| Termux | Sharp picture with `python-pillow` installed, if Termux reports its character size; block art otherwise (`ARA_CELL_PX` forces the picture) |
| VS Code terminal | Sharp picture if "Terminal › Integrated: Enable Images" is on; block art otherwise |
| WezTerm, iTerm2, Kitty, Ghostty, foot, Konsole, xterm (sixel builds) | Sharp picture |
| Old Windows console, PowerShell ISE, other terminals | Block art made of coloured squares |
| Terminals with only 16 colours, or no colour | Her name as text |

The rest of the interface looks the same everywhere.

## Settings

Put these in `~/.aradhya/.env` (or set them in your shell):

| Setting | What it does |
|---|---|
| `GEMINI_API_KEY` | Your Gemini key |
| `ARA_MODEL` | Default model (`gemini-flash-latest`) |
| `ARA_PROVIDER` | `gemini`, `hermes`, `openai`, `openrouter` or `ollama` |
| `ARA_BASE_URL`, `ARA_API_KEY` | For OpenAI-compatible providers |
| `ARA_NAME` | The name in the welcome message |
| `ARA_LOGO` | Force the logo style: `sixel`, `kitty`, `iterm`, `blocks` or `off` |
| `ARA_CELL_PX` | Your terminal's character size in pixels, e.g. `10x21`, if the logo picture comes out the wrong size |
| `ARA_HOME` | Where sessions and history are kept (default `~/.aradhya`) |

## Troubleshooting

**"No Gemini key"**: put `GEMINI_API_KEY=...` in `~/.aradhya/.env`.

**"Gemini didn't answer (busy or out of quota)"**: she already waited and tried other models. Wait a minute, try `/model gemini-3.8-flash`, or use your own key instead of a shared one.

**Strange characters or colours on Windows**: use Windows Terminal (free in the Microsoft Store) rather than the old console window. Aradhya Code switches the console to UTF-8 by itself, so emoji and box lines shouldn't crash anything even in the old one.

**The logo picture is too big or too small**: set `ARA_CELL_PX`. Windows Terminal at default settings is about `10x21`; if you zoomed in, try `12x25`.

**A blank gap where the logo should be**: your terminal claims to support pictures but didn't draw one. Set `ARA_LOGO=blocks`.

**On Termux, the install fails while building `pydantic-core`**: you installed with `[full]`. Use the one-line installer, which leaves it out on Termux.

**`ara` isn't found right after installing**: open a new terminal so the updated PATH applies.
