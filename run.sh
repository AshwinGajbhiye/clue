#!/usr/bin/env bash
# Quick launcher — activates venv and runs Clue
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ ! -f ".venv/bin/python" ]]; then
  echo "Virtual environment not found. Please run ./setup.sh first."
  exit 1
fi

.venv/bin/python run_clue.py "$@"
