#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════╗
# ║         ✦ Clue Stealth Copilot — One-Command Setup             ║
# ║   Installs everything and sets up Antigravity integration       ║
# ╚══════════════════════════════════════════════════════════════════╝

set -e  # Exit immediately on any error

# ── Colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[Clue]${RESET} $*"; }
success() { echo -e "${GREEN}[✓]${RESET} $*"; }
warn()    { echo -e "${YELLOW}[!]${RESET} $*"; }
error()   { echo -e "${RED}[✗]${RESET} $*"; exit 1; }

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║           ✦ Clue Stealth Copilot — Setup                   ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════════╝${RESET}"
echo ""

# ── 1. Check macOS ────────────────────────────────────────────────────────────
if [[ "$OSTYPE" != "darwin"* ]]; then
  error "Clue requires macOS (uses CoreAudio + AppKit stealth APIs). Detected: $OSTYPE"
fi
success "macOS detected."

# ── 2. Check Python 3.10+ ─────────────────────────────────────────────────────
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" &>/dev/null; then
    if "$candidate" -c 'import sys; exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
      PYTHON="$candidate"
      break
    fi
  fi
done

if [[ -z "$PYTHON" ]]; then
  error "Python 3.10 or higher is required but not found.\nInstall from https://www.python.org/downloads/ then re-run this script."
fi
success "Python found: $($PYTHON --version)"

# ── 3. Create virtual environment ─────────────────────────────────────────────
VENV_DIR="$(pwd)/.venv"
if [[ ! -d "$VENV_DIR" ]]; then
  info "Creating virtual environment in .venv/ ..."
  "$PYTHON" -m venv "$VENV_DIR"
  success "Virtual environment created."
else
  success "Virtual environment already exists, skipping."
fi

PIP="$VENV_DIR/bin/pip"
PYTHON_VENV="$VENV_DIR/bin/python"

# ── 4. Upgrade pip silently ────────────────────────────────────────────────────
info "Upgrading pip..."
"$PIP" install --quiet --upgrade pip

# ── 5. Install Python dependencies ────────────────────────────────────────────
info "Installing Python dependencies from requirements.txt..."
"$PIP" install --quiet -r requirements.txt
success "Python dependencies installed."

# ── 6. Check for Antigravity (agy CLI / SDK) ──────────────────────────────────
AGY_BIN=""
for candidate in "$(which agy 2>/dev/null)" "$HOME/.local/bin/agy" "$HOME/.gemini/antigravity/bin/agy" "/usr/local/bin/agy" "/opt/homebrew/bin/agy"; do
  if [[ -n "$candidate" && -x "$candidate" ]]; then
    AGY_BIN="$candidate"
    break
  fi
done

echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${BOLD}  🤖 Antigravity AI Engine Detection${RESET}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""

if [[ -n "$AGY_BIN" ]]; then
  success "Google Antigravity CLI detected at: ${BOLD}$AGY_BIN${RESET}"
  echo -e "  ${GREEN}${BOLD}✦ NO EXTERNAL API KEY NEEDED!${RESET}"
  echo -e "  Clue will use your existing authenticated Antigravity account directly."
else
  warn "Antigravity CLI (agy) was not found in standard paths."
  echo -e "  If you have Antigravity installed, make sure ${BOLD}agy${RESET} is in your PATH."
  echo -e "  You can add to ~/.zshrc:"
  echo -e "    ${CYAN}export PATH=\"\$HOME/.local/bin:\$PATH\"${RESET}"
fi

# Try installing google-antigravity SDK as additional bridge
"$PIP" install --quiet google-antigravity 2>/dev/null || true

# ── 7. Create .env if it doesn't exist ────────────────────────────────────────
ENV_FILE="$(pwd)/.env"
if [[ -f "$ENV_FILE" ]]; then
  success ".env already exists, skipping creation."
else
  info "Creating .env from template..."
  cp "$(pwd)/.env.example" "$ENV_FILE"
  success ".env created from .env.example."
fi

# ── 8. Preferred coding language ──────────────────────────────────────────────
echo ""
echo -e "  What's your preferred interview coding language?"
echo -e "  Options: ${BOLD}C++${RESET}, Python, Java, JavaScript, Go, TypeScript"
read -r -p "  Language (default: C++): " USER_LANG
USER_LANG="${USER_LANG:-C++}"
sed -i.bak "s|^PREFERRED_LANGUAGE=.*|PREFERRED_LANGUAGE=${USER_LANG}|" "$ENV_FILE"
rm -f "${ENV_FILE}.bak"
success "Preferred language set to: $USER_LANG"

# ── 9. Optional fallback API key (only if no Antigravity) ─────────────────────
if [[ -z "$AGY_BIN" ]]; then
  echo ""
  echo -e "  (Optional) If you want to configure an external Gemini API key as fallback:"
  read -r -p "  Enter GEMINI_API_KEY (press Enter to skip): " USER_API_KEY
  if [[ -n "$USER_API_KEY" ]]; then
    sed -i.bak "s|^GEMINI_API_KEY=.*|GEMINI_API_KEY=${USER_API_KEY}|" "$ENV_FILE"
    rm -f "${ENV_FILE}.bak"
    success "API key saved as fallback."
  fi
fi

# ── 10. macOS Permissions Reminder ────────────────────────────────────────────
echo ""
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${YELLOW}  ⚠️  macOS Permissions (First Run)${RESET}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""
echo -e "  On first launch, macOS will ask for:"
echo -e "    • ${BOLD}Microphone${RESET} access — required for audio listening"
echo -e "    • ${BOLD}Accessibility${RESET} — required for global hotkeys (⌥A, ⌥C, etc.)"
echo -e "    • ${BOLD}Screen Recording${RESET} — required for screen snip (⌥O)"
echo ""
echo -e "  Go to: ${CYAN}System Settings → Privacy & Security${RESET}"
echo ""

# ── 11. Launch helper ─────────────────────────────────────────────────────────
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${GREEN}${BOLD}  ✓ Setup complete!${RESET}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""
echo -e "  To launch Clue, simply run:"
echo -e "    ${BOLD}${CYAN}./run.sh${RESET}"
echo ""
