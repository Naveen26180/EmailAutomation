"""
Deterministic checks — no API calls, no cost, instant.
These handle everything that doesn't need real judgment: counting,
keyword matching, presence checks. Reserved AI calls for things that
actually need a model's judgment (drafting, tone, personalization).
"""

import re

SPAM_KEYWORDS = [
    "free", "guarantee", "act now", "limited time", "click here",
    "buy now", "risk free", "no obligation", "urgent", "winner",
    "cash", "cheap", "discount", "offer expires", "100% free",
]

PLATFORM_LIMITS = {
    "Email": {"unit": "words", "max": 220},
    "LinkedIn Connection Request": {"unit": "characters", "max": 300},
    "LinkedIn DM": {"unit": "words", "max": 150},
    "X (Twitter) DM": {"unit": "characters", "max": 280},
    "Slack": {"unit": "words", "max": 100},
    "Discord": {"unit": "words", "max": 100},
}

GREETING_PATTERN = re.compile(r"\b(hi|hello|hey|dear)\b", re.IGNORECASE)
SIGNOFF_PATTERN = re.compile(
    r"\b(best|regards|thanks|sincerely|cheers|warm regards|kind regards|talk soon)\b",
    re.IGNORECASE,
)


def word_count(text: str) -> int:
    return len(text.split())


def char_count(text: str) -> int:
    return len(text)


def reading_time_seconds(text: str) -> int:
    words = word_count(text)
    return max(1, round(words / 200 * 60))  # ~200 wpm average


def spam_risk_flags(text: str):
    lower = text.lower()
    hits = [kw for kw in SPAM_KEYWORDS if kw in lower]
    exclamations = text.count("!")
    all_caps_words = len(re.findall(r"\b[A-Z]{4,}\b", text))
    flags = []
    if hits:
        flags.append(f"Spammy phrases found: {', '.join(hits)}")
    if exclamations > 2:
        flags.append(f"{exclamations} exclamation marks — consider reducing")
    if all_caps_words > 0:
        flags.append(f"{all_caps_words} ALL-CAPS word(s) — can trigger spam filters")
    return flags


def platform_length_check(text: str, platform: str):
    limits = PLATFORM_LIMITS.get(platform)
    if not limits:
        return True, ""
    if limits["unit"] == "words":
        count = word_count(text)
    else:
        count = char_count(text)
    within_limit = count <= limits["max"]
    msg = f"{count}/{limits['max']} {limits['unit']}"
    return within_limit, msg


def checklist(subject: str, body: str, sender_name: str, platform: str):
    """Returns list of (label, passed: bool) tuples."""
    items = []
    if platform == "Email":
        items.append(("Subject present", bool(subject.strip())))
    items.append(("Greeting present", bool(GREETING_PATTERN.search(body))))
    items.append(("Sign-off present", bool(SIGNOFF_PATTERN.search(body))))
    items.append(("Sender name in body", sender_name.lower() in body.lower() if sender_name else False))
    items.append(("Body is non-empty", bool(body.strip())))
    within_limit, _ = platform_length_check(body, platform)
    items.append((f"Within {platform} length guideline", within_limit))
    return items


def run_full_review(subject: str, body: str, sender_name: str, platform: str):
    """Bundles all deterministic checks into one dict for the Pre-Send Review panel."""
    within_limit, length_msg = platform_length_check(body, platform)
    return {
        "word_count": word_count(body),
        "char_count": char_count(body),
        "reading_time_seconds": reading_time_seconds(body),
        "spam_flags": spam_risk_flags(subject + " " + body),
        "length_check": {"within_limit": within_limit, "detail": length_msg},
        "checklist": checklist(subject, body, sender_name, platform),
    }
