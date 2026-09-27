"""Post-LLM grounding + shape validation.

The LLM is never trusted blindly. Every composed body is checked for
fabricated numbers, taboo vocabulary, URLs, multiple CTAs, and repetition
before it leaves the service. Any failure falls back to a deterministic,
template-built message assembled directly from the same facts the LLM was
given — so the bot never returns an ungrounded or malformed message.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_NUM_RE = re.compile(r"₹\s?[\d,]+(?:\.\d+)?|\d[\d,]*(?:\.\d+)?\s?%|\d{2,}(?:,\d{3})*(?:\.\d+)?")


@dataclass
class ValidationResult:
    ok: bool
    notes: list[str] = field(default_factory=list)


def _normalize_number(token: str) -> str:
    return token.replace("₹", "").replace(",", "").replace(" ", "").replace("%", "")


def build_grounding_blob(*payloads) -> str:
    import json
    parts = []
    for p in payloads:
        if p:
            try:
                parts.append(json.dumps(p, default=str))
            except TypeError:
                parts.append(str(p))
    return " ".join(parts)


_FRACTION_RE = re.compile(r"-?0?\.\d+")


def _derived_percent_tokens(blob: str) -> set[str]:
    """Context payloads store rates as fractions (delta_pct: -0.45); messages
    legitimately render these as percentages ("45%"). Treat the *100 form of
    every fraction-like number in the blob as grounded too, so a correct
    derivation is never flagged as a hallucination."""
    tokens: set[str] = set()
    for raw in _FRACTION_RE.findall(blob):
        try:
            value = abs(float(raw)) * 100
        except ValueError:
            continue
        tokens.add(str(int(round(value))))
        tokens.add(f"{value:.1f}")
        tokens.add(f"{value:.0f}")
    return tokens


def check_grounding(body: str, grounding_blob: str) -> ValidationResult:
    blob_normalized = grounding_blob.replace(",", "").replace(" ", "")
    derived = _derived_percent_tokens(grounding_blob)
    bad = []
    for match in _NUM_RE.findall(body):
        norm = _normalize_number(match)
        if not norm:
            continue
        if norm in blob_normalized or norm in derived:
            continue
        bad.append(match)
    if bad:
        return ValidationResult(ok=False, notes=[f"unverified number(s) not found in pushed context: {bad}"])
    return ValidationResult(ok=True)


def check_no_url(body: str) -> ValidationResult:
    if _URL_RE.search(body):
        return ValidationResult(ok=False, notes=["message contains a URL"])
    return ValidationResult(ok=True)


def check_taboo(body: str, taboo_words: list[str]) -> ValidationResult:
    lowered = body.lower()
    hits = [w for w in taboo_words if w and w.lower() in lowered]
    if hits:
        return ValidationResult(ok=False, notes=[f"taboo vocabulary used: {hits}"])
    return ValidationResult(ok=True)


def check_single_cta(body: str) -> ValidationResult:
    question_marks = body.count("?")
    if question_marks > 1:
        return ValidationResult(ok=False, notes=["more than one question/CTA in the message"])
    return ValidationResult(ok=True)


def check_not_repeated(body: str, previous_bodies: list[str]) -> ValidationResult:
    normalized = " ".join(body.split()).strip().lower()
    for prev in previous_bodies:
        if normalized == " ".join(prev.split()).strip().lower():
            return ValidationResult(ok=False, notes=["identical to a previously sent message in this conversation"])
    return ValidationResult(ok=True)


def validate_body(body: str, grounding_blob: str, taboo_words: list[str],
                   previous_bodies: list[str]) -> ValidationResult:
    if not body or not body.strip():
        return ValidationResult(ok=False, notes=["empty body"])
    checks = [
        check_no_url(body),
        check_taboo(body, taboo_words),
        check_single_cta(body),
        check_grounding(body, grounding_blob),
        check_not_repeated(body, previous_bodies),
    ]
    notes = [n for c in checks for n in c.notes]
    return ValidationResult(ok=all(c.ok for c in checks), notes=notes)
