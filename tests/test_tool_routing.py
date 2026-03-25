import sys
from unittest.mock import AsyncMock, MagicMock

sys.modules["mem0"] = MagicMock()

import pytest

# The graph no longer has a dedicated "tool" route (tool calls run inside complex_llm →
# security_proxy → tool_action). These tests targeted the retired flow.
pytestmark = pytest.mark.skip(
    reason="Legacy tool-route graph removed; use test_sentence_routing / test_tool_executor_new."
)
