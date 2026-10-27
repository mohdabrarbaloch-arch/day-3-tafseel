"""Safety guardrails: input classification, refusal paths, PII redaction.

This runs BEFORE any document is stored and BEFORE any analysis. It is deliberately
deterministic -- a regex/rule layer you can unit-test and reason about, not a model
whose behaviour drifts between deploys.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SafetyVerdict:
    verdict: str  # "allow" | "redact" | "refuse"
    category: str
    reason: str
    redactions: int = 0
    redacted_text: str = ""
    matches: tuple[str, ...] = field(default_factory=tuple)

    @property
    def blocked(self) -> bool:
        return self.verdict == "refuse"


# --- PII patterns -------------------------------------------------------------
# Ordered: more specific patterns first so a CNIC is not half-eaten by the phone rule.
_PII_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "cnic",
        re.compile(r"\b\d{5}-\d{7}-\d\b"),
        "[REDACTED_CNIC]",
    ),
    (
        "email",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        "[REDACTED_EMAIL]",
    ),
    (
        "iban",
        re.compile(r"\bPK\d{2}[A-Z]{4}\d{16}\b", re.IGNORECASE),
        "[REDACTED_IBAN]",
    ),
    (
        "card",
        re.compile(r"\b(?:\d[ -]?){13,19}\b"),
        "[REDACTED_CARD]",
    ),
    (
        "phone",
        re.compile(r"(?:\+92|0)\d{3}[ -]?\d{7}\b"),
        "[REDACTED_PHONE]",
    ),
)

# --- Refusal categories -------------------------------------------------------
# Each entry: (category, human reason, patterns). A hit refuses the whole request.
_REFUSAL_RULES: tuple[tuple[str, str, tuple[re.Pattern[str], ...]], ...] = (
    (
        "credential_theft",
        "This looks like a request to obtain someone else's credentials or break into an "
        "account. I can't help with that.",
        (
            re.compile(
                r"\b(?:steal|harvest|phish|phishing)\b.{0,40}\b(?:password|credential|login|otp)\b", re.I
            ),
            re.compile(r"\b(?:crack|brute[ -]?force)\b.{0,30}\b(?:password|hash|account)\b", re.I),
            re.compile(r"\bbypass\b.{0,30}\b(?:2fa|mfa|otp|authentication)\b", re.I),
        ),
    ),
    (
        "malware",
        "This asks for malicious code or an exploit. That's outside what I'll produce.",
        (
            re.compile(
                r"\b(?:write|build|create|generate)\b.{0,30}\b(?:ransomware|keylogger|rootkit|botnet)\b", re.I
            ),
            re.compile(r"\b(?:reverse shell|privilege escalation exploit|sql injection payload)\b", re.I),
        ),
    ),
    (
        "self_harm",
        "I'm not able to help with this. If you're going through something hard, please talk "
        "to someone you trust or a local crisis line.",
        (
            re.compile(
                r"\b(?:how (?:to|do i)|best way to)\b.{0,30}\b(?:kill myself|end my life|self[ -]?harm)\b",
                re.I,
            ),
        ),
    ),
    (
        "weapons",
        "I can't help with building weapons or explosives.",
        (
            re.compile(
                r"\b(?:how (?:to|do i)|instructions? (?:for|to))\b.{0,40}\b(?:make|build|synthesi[sz]e)\b.{0,30}\b(?:bomb|explosive|nerve agent|bioweapon)\b",
                re.I,
            ),
        ),
    ),
    (
        "prompt_injection",
        "The input contains instructions aimed at overriding my own rules, so I'm stopping here.",
        (
            re.compile(r"\bignore (?:all )?(?:previous|prior|above) (?:instructions|rules|prompts?)\b", re.I),
            re.compile(r"\byou are now (?:dan|in developer mode|unrestricted)\b", re.I),
            re.compile(r"\bdisregard (?:your|all) (?:safety|system) (?:rules|prompt|guidelines)\b", re.I),
        ),
    ),
)


def redact_pii(text: str) -> tuple[str, int, tuple[str, ...]]:
    """Replace PII with typed placeholders. Returns (clean_text, count, kinds)."""
    total = 0
    kinds: list[str] = []
    cleaned = text
    for name, pattern, placeholder in _PII_PATTERNS:
        cleaned, hits = pattern.subn(placeholder, cleaned)
        if hits:
            total += hits
            kinds.append(name)
    return cleaned, total, tuple(kinds)


def classify(text: str) -> SafetyVerdict:
    """Full guardrail pass: refuse on hard rules, otherwise redact PII."""
    if not text or not text.strip():
        return SafetyVerdict(verdict="refuse", category="empty", reason="Input is empty.")

    for category, reason, patterns in _REFUSAL_RULES:
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                return SafetyVerdict(
                    verdict="refuse",
                    category=category,
                    reason=reason,
                    matches=(match.group(0)[:120],),
                )

    cleaned, count, kinds = redact_pii(text)
    if count:
        return SafetyVerdict(
            verdict="redact",
            category="pii",
            reason=f"Removed {count} piece(s) of personal data before processing: {', '.join(kinds)}.",
            redactions=count,
            redacted_text=cleaned,
            matches=kinds,
        )

    return SafetyVerdict(
        verdict="allow", category="none", reason="No policy issues found.", redacted_text=text
    )


def sanitize_for_storage(text: str) -> tuple[str, SafetyVerdict]:
    """Convenience wrapper: returns the text to store plus the verdict to log."""
    verdict = classify(text)
    if verdict.blocked:
        return "", verdict
    return verdict.redacted_text or text, verdict
