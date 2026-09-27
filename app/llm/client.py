"""Thin async wrapper around Groq's OpenAI-compatible chat completions API.

The LLM is used ONLY for natural-language phrasing of a decision the
deterministic engine already made (see engine/strategy.py + composer.py).
temperature=0 for determinism; a hard client-side timeout well under the
30s per-call budget so a slow/failed LLM call never blows the tick/reply
budget — composer.py always has a deterministic template fallback.
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional

import httpx

DEFAULT_MODEL = os.environ.get("LLM_MODEL", "openai/gpt-oss-120b").strip()
LLM_TIMEOUT_SECONDS = float(os.environ.get("LLM_TIMEOUT_SECONDS", "8"))
GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"


def _get_api_key() -> Optional[str]:
    """Some dashboards (Railway included) can silently include a trailing
    newline/whitespace when a value is pasted in — that turns 'Bearer <key>'
    into an illegal HTTP header value, failing every request instantly while
    still reporting the key as "present". Always strip before use."""
    key = os.environ.get("GROQ_API_KEY", "").strip()
    return key or None


def is_available() -> bool:
    return _get_api_key() is not None


def _redact(text: str, secret: Optional[str]) -> str:
    return text.replace(secret, "***REDACTED***") if secret else text


async def diagnostic_ping() -> dict:
    """Attempts one real, minimal completion and reports exactly what
    happened — used only by the /v1/debug/llm endpoint. Unlike
    complete_json(), this does NOT swallow the exception, so it can surface
    the real cause (bad key, network egress blocked, timeout, bad model id)
    instead of the silent None that composer.py relies on in production."""
    api_key = _get_api_key()
    if not api_key:
        return {"ok": False, "stage": "no_key", "detail": "GROQ_API_KEY is not set or empty"}
    try:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
            response = await client.post(
                GROQ_CHAT_COMPLETIONS_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": DEFAULT_MODEL,
                    "temperature": 0,
                    "max_tokens": 50,
                    "reasoning_effort": "low",
                    "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
                },
            )
    except Exception as exc:
        return {"ok": False, "stage": "request_failed", "detail": _redact(f"{type(exc).__name__}: {exc}", api_key)}

    if response.status_code != 200:
        return {"ok": False, "stage": "non_200_response", "status_code": response.status_code,
                "detail": _redact(response.text[:500], api_key)}
    try:
        data = response.json()
        text = data["choices"][0]["message"]["content"]
    except Exception as exc:
        return {"ok": False, "stage": "unparseable_response", "detail": _redact(f"{type(exc).__name__}: {exc}", api_key),
                "raw": _redact(response.text[:500], api_key)}

    return {"ok": True, "stage": "success", "model": DEFAULT_MODEL, "content": text,
            "key_prefix": api_key[:8] + "..." if len(api_key) > 8 else "(short/invalid key)"}


async def complete_json(system: str, prompt: str, max_tokens: int = 900) -> Optional[dict]:
    """Calls the LLM and parses a JSON object out of the response. Returns
    None on any failure (missing key, timeout, malformed output) so the
    caller can fall back to a deterministic template.

    `gpt-oss-120b` is a reasoning model: part of `max_tokens` is spent on an
    internal chain-of-thought (returned separately as `message.reasoning`)
    before it writes the actual JSON answer. Left at the default effort,
    reasoning alone regularly consumed 400+ tokens on prompts like ours and
    truncated the JSON output entirely (`finish_reason: "length"` with a
    dangling, unparsable `{...`). `reasoning_effort: "low"` is appropriate
    for a phrasing task with no real reasoning to do, and `max_tokens` is
    sized with headroom on top of that.
    """
    api_key = _get_api_key()
    if not api_key:
        return None
    try:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
            response = await client.post(
                GROQ_CHAT_COMPLETIONS_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": DEFAULT_MODEL,
                    "temperature": 0,
                    "max_tokens": max_tokens,
                    "reasoning_effort": "low",
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                },
            )
            response.raise_for_status()
            data = response.json()
            text = data["choices"][0]["message"]["content"]
    except Exception:
        return None

    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return None
