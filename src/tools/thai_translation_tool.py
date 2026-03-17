"""
Thai Technical Term Lookup Tool
--------------------------------
Loads EN→TH term pairs from tech_thai.json and exposes a lightweight
keyword-matching lookup tool. No external DB or model downloads required.
"""

import json
import re
from pathlib import Path
from langchain_core.tools import tool

_GLOSSARY_PATH = Path(__file__).parent / "glossaries" / "tech_thai.json"

# Load the glossary once at module import time
def _load_glossary() -> list[dict]:
    try:
        with open(_GLOSSARY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("terms", [])
    except Exception as e:
        print(f"[Thai Glossary] Failed to load glossary: {e}")
        return []

_GLOSSARY = _load_glossary()
print(f"[Thai Glossary] Loaded {len(_GLOSSARY)} terms.")


@tool
def lookup_thai_terms(text: str) -> str:
    """
    Retrieves relevant Thai technical term translations from the glossary.
    
    ALWAYS call this tool BEFORE translating any technical content to Thai.
    It scans your input for known technical terms and returns the correct 
    EN→TH translations so you can use precise vocabulary in your translation.
    
    Args:
        text: The English text or list of technical terms you are about to translate.
    
    Returns:
        A formatted glossary of relevant technical terms with correct Thai translations.
    """
    if not _GLOSSARY:
        return "[lookup_thai_terms] Glossary not loaded. Use best-effort translation."
    
    text_lower = text.lower()
    matched = []
    seen = set()
    
    # 1. Exact / phrase match — find terms whose EN phrase appears in the text
    for term in _GLOSSARY:
        en = term["en"].lower()
        if en in text_lower and en not in seen:
            matched.append(term)
            seen.add(en)
    
    # 2. Word overlap — boost coverage for technical words not phrase-matched
    text_words = set(re.findall(r"[a-z]+", text_lower))
    for term in _GLOSSARY:
        en = term["en"].lower()
        if en in seen:
            continue
        term_words = set(re.findall(r"[a-z]+", en))
        if term_words & text_words:  # any word overlap
            matched.append(term)
            seen.add(en)
    
    if not matched:
        return (
            "No specific technical terms found in the glossary for this text.\n"
            "Please translate using your best judgment and keep technical terms in their common Thai forms."
        )
    
    # Sort by English term length (longer = more specific, show first)
    matched.sort(key=lambda t: -len(t["en"]))
    
    lines = [f"📚 Relevant Technical Terms (EN → TH) — use these exactly:"]
    lines.append("─" * 52)
    for m in matched[:30]:  # cap at 30 for context length
        domain = m.get("domain", "")
        lines.append(f"  {m['en']:<35} → {m['th']}  [{domain}]")
    lines.append("─" * 52)
    lines.append("Use the Thai translations above in your output. Do not deviate from them.")
    
    return "\n".join(lines)
