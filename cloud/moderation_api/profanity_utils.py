"""
Profanity handling for SMS LED Display.

Modes:

    EXPLICIT:
        - Soft profanity allowed (e.g., "fuck").
        - Hard-banned words (e.g., racial slurs) NOT allowed.
        - If any hard-banned word is found, message is rejected.

    FAMILY:
        - Any profanity (soft OR hard) causes rejection.

    STARRED:
        - Hard-banned words cause rejection.
        - Soft-banned words are replaced with asterisks (same length).

    ANARCHY:
        - No filtering. Everything is allowed.

This module does NOT touch DynamoDB directly; it only encapsulates the text logic.
"""

import re
from typing import List, Tuple


def _normalize(text: str) -> str:
    """Lowercase and strip non-alphanumeric for crude profanity matching."""
    if not isinstance(text, str):
        return ""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _contains_any(text: str, words: List[str]) -> bool:
    """Check if any listed word appears in the normalized text."""
    norm_text = _normalize(text)
    for w in words or []:
        norm_w = _normalize(w)
        if norm_w and norm_w in norm_text:
            return True
    return False


def _star_soft_words(text: str, soft_words: List[str]) -> str:
    """
    Replace each occurrence of a soft-banned word (case-insensitive)
    with asterisks of the same length. Simple literal match.
    """
    result = text
    for w in soft_words or []:
        if not isinstance(w, str) or not w.strip():
            continue
        pattern = re.compile(re.escape(w), re.IGNORECASE)
        result = pattern.sub("*" * len(w), result)
    return result


def apply_profanity_policy(
    body: str,
    profanity_mode: str,
    hard_banned_words: List[str],
    soft_banned_words: List[str],
) -> Tuple[bool, str, str]:
    """
    Apply profanity policy to a message body.

    Returns:
        (allowed, new_body, reason)

        allowed: bool
        new_body: possibly modified message body (for STARRED)
        reason: short string explaining why it was rejected, or "" if allowed.
    """
    body = body or ""
    profanity_mode = (profanity_mode or "").upper()

    has_hard = _contains_any(body, hard_banned_words)
    has_soft = _contains_any(body, soft_banned_words)

    # ANARCHY: everything goes, no changes.
    if profanity_mode == "ANARCHY":
        return True, body, ""

    # EXPLICIT: soft OK, hard-banned NOT OK.
    if profanity_mode == "EXPLICIT":
        if has_hard:
            return False, body, "hard-banned profanity in EXPLICIT mode"
        return True, body, ""

    # FAMILY: any profanity (soft or hard) is rejected.
    if profanity_mode == "FAMILY":
        if has_hard or has_soft:
            return False, body, "profanity not allowed in FAMILY mode"
        return True, body, ""

    # STARRED: hard-banned rejected; soft gets starred out.
    if profanity_mode == "STARRED":
        if has_hard:
            return False, body, "hard-banned profanity in STARRED mode"
        if has_soft:
            starred = _star_soft_words(body, soft_banned_words)
            return True, starred, ""
        return True, body, ""

    # Unknown mode: be conservative and reject.
    return False, body, f"unknown profanity_mode: {profanity_mode!r}"
