"""Unit tests for is_local_server in src/agent/lm_studio_compat.py."""

import sys
from unittest.mock import MagicMock

sys.modules["mem0"] = MagicMock()

from src.agent.lm_studio_compat import is_local_server


def test_localhost_url():
    assert is_local_server("http://localhost:1234/v1") is True


def test_127_url():
    assert is_local_server("http://127.0.0.1:1234/v1") is True


def test_cloud_url():
    assert is_local_server("https://api.deepseek.com/v1") is False


def test_other_remote_url():
    assert is_local_server("https://api.openai.com/v1") is False


def test_empty_string():
    assert is_local_server("") is False


def test_localhost_in_path():
    assert is_local_server("http://localhost") is True


def test_127_no_port():
    assert is_local_server("http://127.0.0.1") is True
