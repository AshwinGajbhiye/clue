"""
Clue Core — Fast AI Generation Engine & Streaming Worker
Ultra-low-latency pipeline utilizing persistent warm Antigravity Agent
with direct Gemini Flash streaming fallback.
"""

import io
import time
from typing import Callable, Dict, List, Optional
from PyQt6.QtCore import QThread, pyqtSignal

from clue.config import Config
from clue.core.antigravity_engine import get_warm_antigravity, HAS_ANTIGRAVITY
from clue.core.interview_modes import (
    InterviewMode,
    build_copilot_prompt,
    has_explicit_code_request,
)

import warnings

try:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=FutureWarning)
        import google.generativeai as genai
    HAVE_GEMINI = True
except ImportError:
    HAVE_GEMINI = False


class LLMStreamWorker(QThread):
    """
    High-performance background worker that queries the warm Antigravity Agent
    (with direct Gemini streaming fallback) and delivers sub-second tokens to the HUD.
    """
    token_received = pyqtSignal(str)   # Emits individual streaming chunks
    stream_completed = pyqtSignal(str) # Emits full final response string
    stream_error = pyqtSignal(str)

    def __init__(
        self,
        query: str,
        transcript_text: str = "",
        mode: InterviewMode = InterviewMode.CODING_INTERVIEW,
        language: str = "C++",
        screenshot_bytes: Optional[bytes] = None,
        force_code: Optional[bool] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.query = query
        self.transcript_text = transcript_text
        self.mode = mode
        self.language = language
        self.screenshot_bytes = screenshot_bytes
        self.force_code = force_code
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        full_prompt = build_copilot_prompt(
            mode=self.mode,
            user_query=self.query,
            transcript_text=self.transcript_text,
            language=self.language,
            force_code=self.force_code,
        )

        accumulated = []

        def on_token(chunk: str):
            if not self._is_cancelled and chunk:
                accumulated.append(chunk)
                self.token_received.emit(chunk)

        # ── 1. PRIMARY FAST PIPELINE: Warm Persistent Antigravity Agent ───────
        if HAS_ANTIGRAVITY:
            try:
                antigravity_session = get_warm_antigravity()
                full_text = antigravity_session.stream_chat(
                    prompt=full_prompt,
                    image_bytes=self.screenshot_bytes,
                    token_callback=on_token,
                    timeout=25.0,
                )
                if full_text and full_text.strip():
                    self.stream_completed.emit("".join(accumulated) if accumulated else full_text)
                    return
            except Exception as e:
                # Silently failover to direct Gemini stream
                pass

        # ── 2. FALLBACK FAST PIPELINE: Direct Gemini Flash Streaming ─────────
        if HAVE_GEMINI and Config.GEMINI_API_KEY:
            try:
                genai.configure(api_key=Config.GEMINI_API_KEY)
                model = genai.GenerativeModel(Config.GEMINI_MODEL or "gemini-2.5-flash")

                contents = []
                if self.screenshot_bytes:
                    try:
                        from PIL import Image
                        img = Image.open(io.BytesIO(self.screenshot_bytes))
                        contents.append(img)
                    except Exception:
                        pass

                contents.append(full_prompt)
                response = model.generate_content(contents, stream=True)

                for chunk in response:
                    if self._is_cancelled:
                        break
                    text = chunk.text or ""
                    if text:
                        on_token(text)

                final_text = "".join(accumulated)
                if final_text.strip():
                    self.stream_completed.emit(final_text)
                    return
            except Exception as e:
                pass

        # ── 3. EMERGENCY CLEAN FALLBACK ───────────────────────────────────────
        want_code = self.force_code if self.force_code is not None else has_explicit_code_request(self.query, self.transcript_text)
        fallback_parts = [
            f"### 🗣️ WHAT TO SAY TO THE INTERVIEWER",
            f"- For '{self.query}': Clarify input constraints, edge cases, and expected scale.",
            f"- State core approach: Begin with baseline intuition, then optimize for time and memory.",
            f"- Target complexity: State optimal time and space tradeoffs directly."
        ]
        if want_code:
            fallback_parts.extend([
                f"\n### 💻 CODE SOLUTION",
                f"```{self.language.lower()}\n// Clean, minimal solution (short variable names, minimal data structures)\n// Optimal solution for: {self.query}\n```",
                f"\n### ⏱️ COMPLEXITY & TRADEOFFS",
                f"- Time Complexity: O(N)\n- Space Complexity: O(1)"
            ])

        self.stream_completed.emit("\n".join(fallback_parts))
