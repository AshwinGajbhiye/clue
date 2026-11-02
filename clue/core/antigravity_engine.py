"""
Clue Core — Fast Antigravity Engine
Supports both:
1. Native Antigravity CLI (`agy`) streaming — ZERO external API key needed!
   Uses the user's existing Antigravity authenticated session.
2. Google Antigravity SDK (`google.antigravity`) / warm persistent session.
"""

import asyncio
import json
import os
import shutil
import subprocess
import threading
from typing import Callable, Optional

from clue.config import Config

try:
    from google.antigravity import Agent, LocalAgentConfig
    from google.antigravity.types import Image as AgyImage
    HAS_ANTIGRAVITY_SDK = True
except ImportError:
    HAS_ANTIGRAVITY_SDK = False
    AgyImage = None


def find_agy_binary() -> Optional[str]:
    """Find the Antigravity CLI executable on the system."""
    candidates = [
        shutil.which("agy"),
        os.path.expanduser("~/.local/bin/agy"),
        os.path.expanduser("~/.gemini/antigravity/bin/agy"),
        "/usr/local/bin/agy",
        "/opt/homebrew/bin/agy",
    ]
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def has_antigravity() -> bool:
    """Return True if either the agy CLI or SDK is available."""
    return find_agy_binary() is not None or HAS_ANTIGRAVITY_SDK


# Backward-compatible flag
HAS_ANTIGRAVITY = has_antigravity()


class AntigravityWarmSession:
    """
    Antigravity Engine session.
    First priority: Antigravity CLI (agy) — requires ZERO external API keys.
    Second priority: Warm persistent Agent session via google.antigravity SDK.
    """

    def __init__(self, api_key: str = "", model: str = ""):
        self.api_key = api_key or Config.GEMINI_API_KEY
        self.model = model or Config.GEMINI_MODEL or "gemini-2.5-flash"
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._agent = None
        self._ready = threading.Event()
        self._initialized = False
        self._agy_bin = find_agy_binary()

    def start(self) -> bool:
        """Initialize and warm up engine."""
        self._agy_bin = find_agy_binary()
        if self._agy_bin:
            self._initialized = True
            return True

        if not HAS_ANTIGRAVITY_SDK or not self.api_key:
            return False

        if self._thread and self._thread.is_alive() and self._initialized:
            return True

        self._ready.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="ClueAntigravityWorker")
        self._thread.start()
        success = self._ready.wait(timeout=8.0)
        self._initialized = success and (self._agent is not None)
        return self._initialized

    def _create_agent(self):
        key = self.api_key or os.environ.get("GEMINI_API_KEY", "")
        config = LocalAgentConfig(
            api_key=key if key else None,
            model=self.model,
        )
        return Agent(config)

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._agent = self._create_agent()
            self._loop.run_until_complete(self._agent.__aenter__())
        except Exception as e:
            print(f"  ⚠️ Clue Antigravity warm session warning: {e}")
            self._agent = None
        finally:
            self._ready.set()
        self._loop.run_forever()

    def _stream_via_agy_cli(
        self,
        prompt: str,
        token_callback: Optional[Callable[[str], None]] = None,
        timeout: float = 30.0,
    ) -> str:
        """Stream response using local Antigravity CLI without requiring any API key."""
        agy_bin = self._agy_bin or find_agy_binary()
        if not agy_bin:
            raise RuntimeError("Antigravity CLI (agy) not found.")

        cmd = [
            agy_bin,
            "--output-format", "stream-json",
            "--disable-slash-commands",
            "--dangerously-skip-permissions",
            "-p", prompt,
        ]

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        tokens = []
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    event = data.get("event")
                    if event == "step_update":
                        step = data.get("step_update", {})
                        delta = step.get("text_delta")
                        if delta:
                            tokens.append(delta)
                            if token_callback:
                                token_callback(delta)
                    elif event == "result":
                        res = data.get("result", {})
                        resp_text = res.get("response", "")
                        if resp_text and not tokens:
                            tokens.append(resp_text)
                            if token_callback:
                                token_callback(resp_text)
                except Exception:
                    pass

            proc.wait(timeout=timeout)
        except Exception as e:
            try:
                proc.kill()
            except Exception:
                pass
            raise e

        return "".join(tokens)

    async def _async_chat_stream_sdk(
        self,
        prompt: str,
        image_bytes: Optional[bytes] = None,
        token_callback: Optional[Callable[[str], None]] = None,
    ) -> str:
        if self._agent is None:
            self._agent = self._create_agent()
            await self._agent.__aenter__()

        payload = prompt
        if image_bytes and AgyImage:
            try:
                agy_img = AgyImage(data=image_bytes, mime_type="image/png")
                payload = [prompt, agy_img]
            except Exception:
                payload = prompt

        response = await self._agent.chat(payload)

        accumulated = []
        try:
            async for chunk in response.chunks:
                text = getattr(chunk, "text", "")
                if text and chunk.__class__.__name__ != "Thought":
                    accumulated.append(text)
                    if token_callback:
                        token_callback(text)
        except Exception:
            pass

        full_text = "".join(accumulated)
        if not full_text.strip():
            full_text = await response.text()
            if token_callback and full_text:
                token_callback(full_text)

        return full_text

    def stream_chat(
        self,
        prompt: str,
        image_bytes: Optional[bytes] = None,
        token_callback: Optional[Callable[[str], None]] = None,
        timeout: float = 30.0,
    ) -> str:
        """Stream tokens using either Antigravity CLI or SDK."""
        # Method 1: Antigravity CLI (Zero API Key needed)
        if self._agy_bin or find_agy_binary():
            try:
                return self._stream_via_agy_cli(prompt, token_callback=token_callback, timeout=timeout)
            except Exception as e:
                print(f"  [Clue] agy CLI stream error ({e}), trying SDK fallback...")

        # Method 2: SDK session if initialized
        if self._agent and self._loop and self._loop.is_running():
            coro = self._async_chat_stream_sdk(prompt, image_bytes=image_bytes, token_callback=token_callback)
            future = asyncio.run_coroutine_threadsafe(coro, self._loop)
            return future.result(timeout=timeout)

        raise RuntimeError("No working Antigravity backend available.")


_global_antigravity: Optional[AntigravityWarmSession] = None


def get_warm_antigravity() -> AntigravityWarmSession:
    global _global_antigravity
    if _global_antigravity is None:
        _global_antigravity = AntigravityWarmSession()
        _global_antigravity.start()
    return _global_antigravity
