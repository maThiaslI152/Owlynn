import argparse
import asyncio
import subprocess
import sys
import unittest
from pathlib import Path


def run_routing_regressions() -> int:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_prompt_regression.py",
            "tests/test_sentence_routing_and_response.py",
        ]
    )
    return result.returncode


def run_legacy_unittests():
    from unittest.mock import AsyncMock, patch
    from langchain_core.messages import AIMessage, HumanMessage

    # Ensure project root is importable when script is run directly.
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from src.agent.graph import reason_node, validate_node

    class TestGraph(unittest.TestCase):
        def test_validate_node(self):
            safe_message = AIMessage(
                content="Executing",
                tool_calls=[{"name": "execute_sandboxed_shell", "args": {"command": "ls -l"}, "id": "call_1"}],
            )
            state = {"messages": [safe_message]}
            result = validate_node(state)
            self.assertEqual(result, {})

            danger_message = AIMessage(
                content="Executing",
                tool_calls=[{"name": "execute_sandboxed_shell", "args": {"command": "rm -rf /"}, "id": "call_2"}],
            )
            state_danger = {"messages": [danger_message]}
            result_danger = validate_node(state_danger)
            self.assertIn("messages", result_danger)
            self.assertEqual(len(result_danger["messages"]), 1)
            self.assertIn("Security Exception", result_danger["messages"][0].content)

        def test_reason_node_async(self):
            async def run_test():
                from unittest.mock import MagicMock

                mock_llm = MagicMock()
                mock_llm.bind_tools.return_value = mock_llm
                mock_llm.ainvoke = AsyncMock(
                    return_value=AIMessage(
                        content="""<thought>I should list files.</thought>
```json
{
  "name": "list_workspace_files",
  "arguments": {"directory": "."}
}
```"""
                    )
                )

                state = {"messages": [HumanMessage(content="list files")], "mode": "reasoning"}

                with patch("src.agent.graph.get_llm", return_value=mock_llm):
                    with patch("src.agent.graph.get_persona") as mock_p, patch(
                        "src.agent.graph.get_profile"
                    ) as mock_pr, patch("src.agent.graph.memories_to_context") as mock_m:
                        mock_p.return_value = {}
                        mock_pr.return_value = {}
                        mock_m.return_value = ""
                        result = await reason_node(state)

                self.assertIn("messages", result)
                ans = result["messages"][0]
                self.assertTrue(hasattr(ans, "tool_calls"))
                self.assertEqual(len(ans.tool_calls), 1)
                self.assertEqual(ans.tool_calls[0]["name"], "list_workspace_files")

            asyncio.run(run_test())

        def test_reason_node_fast(self):
            async def run_test():
                from unittest.mock import MagicMock

                mock_llm = MagicMock()
                mock_llm.ainvoke = AsyncMock(
                    return_value=AIMessage(
                        content="""```json
{
  "name": "list_workspace_files",
  "arguments": {"directory": "."}
}
```"""
                    )
                )

                state = {"messages": [HumanMessage(content="list files")], "mode": "fast"}

                with patch("src.agent.graph.get_llm", return_value=mock_llm):
                    with patch("src.agent.graph.get_persona") as mock_p, patch(
                        "src.agent.graph.get_profile"
                    ) as mock_pr, patch("src.agent.graph.memories_to_context") as mock_m:
                        mock_p.return_value = {}
                        mock_pr.return_value = {}
                        mock_m.return_value = ""
                        result = await reason_node(state)

                self.assertIn("messages", result)
                ans = result["messages"][0]
                self.assertFalse(hasattr(ans, "tool_calls") and ans.tool_calls)

            asyncio.run(run_test())

    unittest.main()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Owlynn test suites.")
    parser.add_argument(
        "--routing",
        action="store_true",
        help="Run sentence/prompt routing regression tests via pytest.",
    )
    args = parser.parse_args()

    if args.routing:
        raise SystemExit(run_routing_regressions())

    run_legacy_unittests()


