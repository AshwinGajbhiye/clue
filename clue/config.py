"""
Clue Stealth Copilot — Central Configuration & Settings
"""

import os
import ssl
import sys
from pathlib import Path
from dotenv import load_dotenv

# Disable gRPC fork handlers and silence INFO/poll warnings
os.environ["GRPC_ENABLE_FORK_SUPPORT"] = "0"
os.environ["GRPC_POLL_STRATEGY"] = "poll"
os.environ["GRPC_VERBOSITY"] = "ERROR"

# Ensure macOS SSL certificate verification works for urllib / SpeechRecognition
try:
    import certifi
    os.environ["SSL_CERT_FILE"] = certifi.where()
    ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())
except Exception:
    pass

# Load .env from the project root (one level above clue/ package)
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)


class Config:
    """Configuration settings for Clue Stealth Copilot."""

    # ── AI Brain ─────────────────────────────────────────────────────────────
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "").strip()
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "").strip()
    OPENROUTER_MODEL: str = os.getenv("OPENROUTER_MODEL", "openrouter/free").strip()

    # ── UI/UX Aesthetics & Translucency ──────────────────────────────────────
    # Available presets: "ghost" (0.40), "balanced" (0.65), "focus" (0.85)
    DEFAULT_OPACITY_MODE: str = os.getenv("DEFAULT_OPACITY", "balanced").lower()
    OPACITY_LEVELS = {
        "ghost": 0.40,      # Maximum background visibility
        "balanced": 0.65,   # Ideal glassmorphism & contrast balance
        "focus": 0.85,      # High contrast dark card
    }

    # ── Audio Rules & VAD Parameters ─────────────────────────────────────────
    SAMPLE_RATE: int = 16000
    FRAME_DURATION_MS: int = 30           # 30ms frames (480 samples @ 16kHz)
    VAD_ENERGY_THRESHOLD: float = float(os.getenv("VAD_ENERGY_THRESHOLD", "0.007"))
    MIN_SPEECH_DURATION: float = float(os.getenv("VAD_MIN_SPEECH_DURATION", "0.35"))   # 350ms minimum to catch short questions
    SILENCE_TIMEOUT: float = float(os.getenv("VAD_SILENCE_TIMEOUT", "0.85"))           # 850ms silence completes question turn
    MAX_UTTERANCE_DURATION: float = float(os.getenv("VAD_MAX_UTTERANCE_DURATION", "15.0")) # 15s chunking cap
    CROSS_TALK_DUCKING: float = 0.05      # Duck mic to 5% when system/interviewer audio is active

    # ── Interview Preferences & Code Craftsmanship ───────────────────────────
    PREFERRED_LANGUAGE: str = os.getenv("PREFERRED_LANGUAGE", "C++").strip()
    CODE_STYLE_CONCISE: bool = True            # Minimal boilerplate, 15-30 lines
    CODE_STYLE_SHORT_VARS: bool = True          # Short, idiomatic names: n, ans, res, cur, seen, left, right
    CODE_STYLE_MINIMAL_DS: bool = True          # Avoid unnecessary custom classes, wrapper structs, or redundant heaps

    # ── macOS Stealth Overlay Window Levels ───────────────────────────────────
    HUD_WINDOW_LEVEL: int = 1000
    HUD_WINDOW_TITLE: str = "ClueStealthCopilot"

    @classmethod
    def get_opacity(cls, mode: str = None) -> float:
        mode = (mode or cls.DEFAULT_OPACITY_MODE).lower()
        return cls.OPACITY_LEVELS.get(mode, cls.OPACITY_LEVELS["balanced"])
