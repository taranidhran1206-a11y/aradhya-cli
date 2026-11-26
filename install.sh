#!/bin/sh
# Aradhya Code installer for Linux, macOS and Termux (Android).
#
#   curl -fsSL https://raw.githubusercontent.com/taranidhran1206-a11y/aradhya-cli/main/docs/install.sh | sh
#
# Installs into its own folder (~/.aradhya/venv), so it never touches your system Python,
# and puts the `ara` command on your PATH. Run it again any time to update.
#
# Options (environment variables):
#   ARA_MINIMAL=1   skip the Gemini SDK and Pillow (automatic on Termux)
#   ARA_NO_SETUP=1  don't start setup at the end (run `ara setup` later)
#   ARA_SOURCE=...  install from another URL or a local folder
#   ARA_UNINSTALL=1 remove Aradhya Code (keeps your sessions and key in ~/.aradhya)
set -eu

REPO_ZIP="https://github.com/taranidhran1206-a11y/aradhya-cli/archive/refs/heads/main.zip"
SOURCE="${ARA_SOURCE:-$REPO_ZIP}"
HOME_DIR="${ARA_HOME:-$HOME/.aradhya}"
VENV="$HOME_DIR/venv"

if [ -t 1 ]; then
  GOLD="$(printf '\033[38;2;232;181;91m')"; BLUE="$(printf '\033[38;2;75;163;245m')"
  RED="$(printf '\033[38;2;229;83;75m')"; DIM="$(printf '\033[2m')"; B="$(printf '\033[1m')"; R="$(printf '\033[0m')"
else
  GOLD=""; BLUE=""; RED=""; DIM=""; B=""; R=""
fi
say()  { printf '%s\n' "$*"; }
step() { printf '%s●%s %s\n' "$GOLD" "$R" "$*"; }
fail() { printf '%s✗ %s%s\n' "$RED" "$*" "$R" >&2; exit 1; }

TERMUX=0
[ -n "${TERMUX_VERSION:-}" ] || [ -d /data/data/com.termux ] && TERMUX=1
if [ "$TERMUX" = 1 ]; then
  BIN_DIR="${PREFIX:-/data/data/com.termux/files/usr}/bin"
else
  BIN_DIR="$HOME/.local/bin"
fi

say ""
say "  ${GOLD}✦ ${B}Aradhya Code${R}  ${DIM}installer${R}"
say ""

if [ -n "${ARA_UNINSTALL:-}" ]; then
  rm -rf "$VENV"
  rm -f "$BIN_DIR/ara"
  step "Removed Aradhya Code. Your sessions and key are still in $HOME_DIR (delete that folder to remove them too)."
  exit 0
fi

# ── Python ────────────────────────────────────────────────
PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  if [ "$TERMUX" = 1 ]; then
    step "Installing Python (pkg install python)…"
    pkg install -y python >/dev/null || fail "Couldn't install Python. Run: pkg install python"
    PY=python
  else
    fail "Python 3.9 or newer is needed. Install it (macOS: brew install python · Ubuntu/Debian: sudo apt install python3 python3-venv) and run this again."
  fi
fi
step "Using $($PY --version 2>&1)"

# ── Its own environment ───────────────────────────────────
mkdir -p "$HOME_DIR"
if [ ! -x "$VENV/bin/python" ]; then
  step "Creating $VENV"
  if ! "$PY" -m venv "$VENV" >/dev/null 2>&1; then
    rm -rf "$VENV"
    fail "Python's venv module is missing. On Ubuntu/Debian run: sudo apt install python3-venv  (then run this again)"
  fi
fi
VPY="$VENV/bin/python"
"$VPY" -m pip install --quiet --disable-pip-version-check --upgrade pip >/dev/null 2>&1 || true

EXTRA="[full]"
if [ "$TERMUX" = 1 ] || [ -n "${ARA_MINIMAL:-}" ]; then
  EXTRA=""
  if [ "$TERMUX" = 1 ]; then
    # Pillow from Termux's own packages (it can't be built by pip on Android); used for the sharp logo
    if ! "$PY" -c 'import PIL' >/dev/null 2>&1; then
      pkg install -y python-pillow >/dev/null 2>&1 || true
    fi
    if "$PY" -c 'import PIL' >/dev/null 2>&1 && [ ! -f "$VENV/.system-site" ]; then
      # let the venv see Termux's Pillow
      sed -i 's/^include-system-site-packages = false/include-system-site-packages = true/' "$VENV/pyvenv.cfg" 2>/dev/null || true
      touch "$VENV/.system-site"
    fi
  fi
fi

step "Installing Aradhya Code${EXTRA:+ (with the Gemini SDK and Pillow)}…"
case "$SOURCE" in
  http*) PKG="aradhya-code$EXTRA @ $SOURCE" ;;
  *)     PKG="$SOURCE$EXTRA" ;;
esac
"$VPY" -m pip install --quiet --disable-pip-version-check --upgrade --force-reinstall --no-deps "$PKG" \
  || fail "pip couldn't install Aradhya Code (see the error above)."
"$VPY" -m pip install --quiet --disable-pip-version-check --upgrade "$PKG" \
  || fail "pip couldn't install the dependencies (see the error above)."

# ── The `ara` command ─────────────────────────────────────
mkdir -p "$BIN_DIR"
ln -sf "$VENV/bin/ara" "$BIN_DIR/ara"
VERSION="$("$VENV/bin/ara" --version 2>/dev/null || echo "Aradhya Code")"
step "Installed ${B}$VERSION${R} → $BIN_DIR/ara"

# ── Setup: her brain, sign-in, model ──────────────────────
# `ara setup` asks your name, lets you pick a brain (Google sign-in, OpenRouter, OpenAI, Anthropic, Ollama…),
# signs you in or takes a key, picks a model and checks she answers. Skipped if she's already set up.
if [ -z "${ARA_NO_SETUP:-}${ARA_NO_KEY:-}" ] && [ ! -f "$HOME_DIR/config.json" ] \
   && ! grep -qs '^GEMINI_API_KEY=.' "$HOME_DIR/.env" && [ -z "${GEMINI_API_KEY:-}" ]; then
  if [ -r /dev/tty ] && (exec </dev/tty) 2>/dev/null; then
    say ""
    "$VENV/bin/ara" setup </dev/tty >/dev/tty 2>&1 || say "  ${DIM}You can finish this later with: ara setup${R}"
  else
    say "  ${DIM}Next: run ${R}${B}ara setup${R}${DIM} to pick her brain.${R}"
  fi
fi

# ── PATH ──────────────────────────────────────────────────
say ""
case ":$PATH:" in
  *":$BIN_DIR:"*)
    say "  ${GOLD}✦${R} Done. Go to a project folder and run: ${B}ara${R}" ;;
  *)
    SHELL_RC="$HOME/.profile"
    case "${SHELL:-}" in */zsh) SHELL_RC="$HOME/.zshrc" ;; */bash) SHELL_RC="$HOME/.bashrc" ;; esac
    if ! grep -qs "$BIN_DIR" "$SHELL_RC"; then
      printf '\nexport PATH="%s:$PATH"\n' "$BIN_DIR" >> "$SHELL_RC"
    fi
    say "  ${GOLD}✦${R} Done. Open a new terminal (or run: ${B}export PATH=\"$BIN_DIR:\$PATH\"${R}), then: ${B}ara${R}" ;;
esac
say ""
