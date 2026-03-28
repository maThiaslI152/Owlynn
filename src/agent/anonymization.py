"""
Data Anonymization Engine for cloud-bound messages.

Scans text for PII and sensitive patterns, replaces with deterministic
placeholders before sending to DeepSeek API, and restores originals
in the response. Only used for the cloud path — local models are trusted.
"""

import re
from typing import Optional


# Detection patterns in priority order (longest match first)
_PATTERNS: list[tuple[str, re.Pattern]] = [
    # 1. API keys/tokens — match before shorter patterns
    ("API_KEY", re.compile(
        r"(?:Bearer\s+[A-Za-z0-9\-._~+/]+=*"
        r"|(?:sk|key|token|ghp|gho|glpat)-[A-Za-z0-9\-._]{20,}"
        r"|[A-Za-z0-9]{32,}(?=\s|$|[\"'}),:]))"
    )),
    # 2. Email addresses
    ("EMAIL", re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")),
    # 3. Localhost URLs with ports
    ("URL", re.compile(r"https?://(?:localhost|127\.0\.0\.1):\d+")),
    # 4. File system paths
    ("PATH", re.compile(r"(?:/Users/\S+|/home/\S+|~/\S+|[A-Z]:\\\\?\S+)")),
    # 5. IP addresses (exclude 0.0.0.0 and 255.255.255.255)
    ("IP", re.compile(
        r"\b(?!0\.0\.0\.0\b)(?!255\.255\.255\.255\b)"
        r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"
    )),
    # 6. Phone numbers (international formats)
    ("PHONE", re.compile(
        r"(?:\+\d{1,3}[\s\-]?)?"
        r"(?:\(\d{1,4}\)[\s\-]?)?"
        r"\d{2,4}[\s.\-]?\d{2,4}[\s.\-]?\d{2,4}"
    )),
]


def anonymize(text: str, context: Optional[dict] = None) -> tuple[str, dict]:
    """
    Scan text for sensitive patterns, replace with [CATEGORY_N] placeholders.

    Args:
        text: The text to anonymize.
        context: Optional dict with known sensitive values:
            - "name": user's name from profile
            - "custom_sensitive_terms": list of additional terms to detect

    Returns:
        (anonymized_text, mapping) where mapping is {placeholder: original_value}
    """
    if not text:
        return ("", {})

    context = context or {}
    mapping: dict[str, str] = {}   # placeholder → original
    reverse: dict[str, str] = {}   # original → placeholder (for dedup)
    counters: dict[str, int] = {}  # category → next N

    def _get_placeholder(category: str, value: str) -> str:
        """Get or create a placeholder for a value. Same value = same placeholder."""
        if value in reverse:
            return reverse[value]
        n = counters.get(category, 0) + 1
        counters[category] = n
        placeholder = f"[{category}_{n}]"
        mapping[placeholder] = value
        reverse[value] = placeholder
        return placeholder

    # Collect all matches with positions for longest-first replacement
    matches: list[tuple[int, int, str, str]] = []  # (start, end, category, value)

    # 1. Known names from context
    name = context.get("name", "").strip()
    if name and len(name) > 1:
        for m in re.finditer(re.escape(name), text, re.IGNORECASE):
            matches.append((m.start(), m.end(), "NAME", m.group()))

    # 2. Custom sensitive terms
    for term in context.get("custom_sensitive_terms", []):
        term = str(term).strip()
        if term and len(term) > 1:
            for m in re.finditer(re.escape(term), text, re.IGNORECASE):
                matches.append((m.start(), m.end(), "CUSTOM", m.group()))

    # 3. Regex patterns
    for category, pattern in _PATTERNS:
        for m in pattern.finditer(text):
            matches.append((m.start(), m.end(), category, m.group()))

    # No matches → return original text unchanged
    if not matches:
        return (text, {})

    # Sort by start position, then longest match first (to handle overlaps)
    matches.sort(key=lambda x: (x[0], -(x[1] - x[0])))

    # Remove overlapping matches (keep longest/first)
    filtered: list[tuple[int, int, str, str]] = []
    last_end = 0
    for start, end, category, value in matches:
        if start >= last_end:
            filtered.append((start, end, category, value))
            last_end = end

    # Build anonymized text by replacing from end to start (preserve positions)
    result = text
    for start, end, category, value in reversed(filtered):
        placeholder = _get_placeholder(category, value)
        result = result[:start] + placeholder + result[end:]

    return result, mapping


def deanonymize(text: str, mapping: dict) -> str:
    """
    Restore placeholders to original values.

    Unknown placeholders (not in mapping) are left unchanged.
    """
    if not text or not mapping:
        return text
    result = text
    # Sort by placeholder length descending to avoid partial replacements
    for placeholder in sorted(mapping.keys(), key=len, reverse=True):
        result = result.replace(placeholder, mapping[placeholder])
    return result
