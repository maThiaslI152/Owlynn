"""
Unit tests for the AnonymizationEngine.

Tests round-trip correctness, placeholder format, deterministic duplicates,
priority ordering, all pattern categories, and edge cases.
"""

import re
import pytest
from src.agent.anonymization import anonymize, deanonymize


# ── Edge cases ──────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_text(self):
        result, mapping = anonymize("")
        assert result == ""
        assert mapping == {}

    def test_no_sensitive_data(self):
        text = "Hello, how are you today?"
        result, mapping = anonymize(text)
        assert result == text
        assert mapping == {}

    def test_none_context(self):
        text = "Just a normal sentence."
        result, mapping = anonymize(text, None)
        assert result == text
        assert mapping == {}

    def test_empty_context(self):
        text = "Nothing sensitive here."
        result, mapping = anonymize(text, {})
        assert result == text
        assert mapping == {}


# ── Round-trip property ─────────────────────────────────────────────────────

class TestRoundTrip:
    def test_round_trip_email(self):
        text = "Contact me at alice@example.com for details."
        anon, mapping = anonymize(text)
        assert deanonymize(anon, mapping) == text

    def test_round_trip_with_context(self):
        text = "Hi Tim, your project secret-project is ready."
        ctx = {"name": "Tim", "custom_sensitive_terms": ["secret-project"]}
        anon, mapping = anonymize(text, ctx)
        assert deanonymize(anon, mapping) == text

    def test_round_trip_multiple_categories(self):
        text = "Email alice@test.com from /Users/alice/docs, IP 10.0.0.1"
        anon, mapping = anonymize(text)
        assert deanonymize(anon, mapping) == text

    def test_round_trip_no_matches(self):
        text = "Plain text with no PII."
        anon, mapping = anonymize(text)
        assert anon == text
        assert deanonymize(anon, mapping) == text


# ── Placeholder format ──────────────────────────────────────────────────────

class TestPlaceholderFormat:
    _PLACEHOLDER_RE = re.compile(r"\[([A-Z_]+)_(\d+)\]")

    def test_placeholder_format_email(self):
        text = "Send to bob@example.org please."
        anon, mapping = anonymize(text)
        for ph in mapping:
            assert self._PLACEHOLDER_RE.fullmatch(ph), f"Bad placeholder: {ph}"

    def test_placeholder_format_api_key(self):
        text = "Use key sk-abcdefghijklmnopqrstuvwxyz1234"
        anon, mapping = anonymize(text)
        assert any("API_KEY" in ph for ph in mapping)
        for ph in mapping:
            assert self._PLACEHOLDER_RE.fullmatch(ph)


# ── Deterministic duplicates ────────────────────────────────────────────────

class TestDeterministicDuplicates:
    def test_same_email_same_placeholder(self):
        text = "Email alice@test.com and again alice@test.com"
        anon, mapping = anonymize(text)
        # Only one EMAIL placeholder should exist
        email_phs = [ph for ph in mapping if "EMAIL" in ph]
        assert len(email_phs) == 1
        # Both occurrences replaced with the same placeholder
        assert anon.count(email_phs[0]) == 2

    def test_same_name_same_placeholder(self):
        text = "Hello Tim, how is Tim doing?"
        ctx = {"name": "Tim"}
        anon, mapping = anonymize(text, ctx)
        name_phs = [ph for ph in mapping if "NAME" in ph]
        assert len(name_phs) == 1
        assert anon.count(name_phs[0]) == 2


# ── Pattern detection categories ────────────────────────────────────────────

class TestPatternDetection:
    def test_detect_email(self):
        text = "Contact user@domain.com"
        anon, mapping = anonymize(text)
        assert "[EMAIL_1]" in anon
        assert mapping["[EMAIL_1]"] == "user@domain.com"

    def test_detect_api_key_sk(self):
        text = "Key: sk-abcdefghijklmnopqrstuvwxyz1234"
        anon, mapping = anonymize(text)
        assert any("API_KEY" in ph for ph in mapping)

    def test_detect_api_key_bearer(self):
        text = "Auth: Bearer eyJhbGciOiJIUzI1NiJ9.test"
        anon, mapping = anonymize(text)
        assert any("API_KEY" in ph for ph in mapping)

    def test_detect_localhost_url(self):
        text = "Server at http://localhost:8080"
        anon, mapping = anonymize(text)
        assert any("URL" in ph for ph in mapping)
        assert mapping.get("[URL_1]") == "http://localhost:8080"

    def test_detect_127_url(self):
        text = "API at http://127.0.0.1:1234"
        anon, mapping = anonymize(text)
        assert any("URL" in ph for ph in mapping)

    def test_detect_path_users(self):
        text = "File at /Users/alice/projects/app"
        anon, mapping = anonymize(text)
        assert any("PATH" in ph for ph in mapping)

    def test_detect_path_home(self):
        text = "Config in /home/bob/.config/app"
        anon, mapping = anonymize(text)
        assert any("PATH" in ph for ph in mapping)

    def test_detect_path_tilde(self):
        text = "See ~/Documents/notes.txt"
        anon, mapping = anonymize(text)
        assert any("PATH" in ph for ph in mapping)

    def test_detect_ip_address(self):
        text = "Connect to 192.168.1.100 for access"
        anon, mapping = anonymize(text)
        assert any("IP" in ph for ph in mapping)
        assert mapping.get("[IP_1]") == "192.168.1.100"

    def test_exclude_ip_zeros(self):
        text = "Bind to 0.0.0.0 for all interfaces"
        anon, mapping = anonymize(text)
        assert not any("IP" in ph for ph in mapping)

    def test_exclude_ip_broadcast(self):
        text = "Broadcast 255.255.255.255"
        anon, mapping = anonymize(text)
        assert not any("IP" in ph for ph in mapping)

    def test_detect_phone(self):
        text = "Call +1-555-123-4567 for support"
        anon, mapping = anonymize(text)
        assert any("PHONE" in ph for ph in mapping)

    def test_detect_name_from_context(self):
        text = "Hello Tim, welcome back."
        ctx = {"name": "Tim"}
        anon, mapping = anonymize(text, ctx)
        assert any("NAME" in ph for ph in mapping)

    def test_detect_custom_term(self):
        text = "Working on project-alpha today."
        ctx = {"custom_sensitive_terms": ["project-alpha"]}
        anon, mapping = anonymize(text, ctx)
        assert any("CUSTOM" in ph for ph in mapping)
        assert mapping.get("[CUSTOM_1]") == "project-alpha"

    def test_custom_term_case_insensitive(self):
        text = "Working on PROJECT-ALPHA today."
        ctx = {"custom_sensitive_terms": ["project-alpha"]}
        anon, mapping = anonymize(text, ctx)
        assert any("CUSTOM" in ph for ph in mapping)


# ── Deanonymize edge cases ──────────────────────────────────────────────────

class TestDeanonymize:
    def test_unknown_placeholder_left_unchanged(self):
        text = "Hello [NAME_99], your [UNKNOWN_1] is ready."
        mapping = {"[NAME_1]": "Tim"}
        result = deanonymize(text, mapping)
        assert "[NAME_99]" in result
        assert "[UNKNOWN_1]" in result

    def test_empty_mapping(self):
        text = "Hello [NAME_1]"
        assert deanonymize(text, {}) == text

    def test_empty_text(self):
        assert deanonymize("", {"[NAME_1]": "Tim"}) == ""


# ── Overlap handling ────────────────────────────────────────────────────────

class TestOverlapHandling:
    def test_email_not_split_by_name(self):
        """Email should be matched as EMAIL, not have the local part matched as NAME."""
        text = "Contact tim@example.com for info."
        ctx = {"name": "tim"}
        anon, mapping = anonymize(text, ctx)
        # The email should be a single EMAIL placeholder, not split
        assert "[EMAIL_1]" in anon
        assert mapping["[EMAIL_1]"] == "tim@example.com"
