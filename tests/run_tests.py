import unittest
import asyncio
from unittest.mock import AsyncMock, patch
from langchain_core.messages import AIMessage, HumanMessage
from src.agent.graph import reason_node, validate_node
from src.agent.state import AgentState

class TestGraph(unittest.TestCase):

    def test_validate_node(self):
        # Test safe command
        safe_message = AIMessage(content="Executing", tool_calls=[{
            "name": "execute_sandboxed_shell",
            "args": {"command": "ls -l"},
            "id": "call_1"
        }])
        state = {"messages": [safe_message]}
        result = validate_node(state)
        self.assertTrue(result["execution_approved"])

        # Test dangerous command
        danger_message = AIMessage(content="Executing", tool_calls=[{
            "name": "execute_sandboxed_shell",
            "args": {"command": "rm -rf /"},
            "id": "call_2"
        }])
        state_danger = {"messages": [danger_message]}
        result_danger = validate_node(state_danger)
        self.assertFalse(result_danger["execution_approved"])
        self.assertIn("messages", result_danger)
        self.assertIn("Security Exception", result_danger["messages"][0].content)

    def test_reason_node_async(self):
        async def run_test():
            # Mock LLM
            from unittest.mock import MagicMock
            mock_llm = MagicMock()
            # bind_tools is synchronous, should return a mock that has async ainvoke
            mock_llm.bind_tools.return_value = mock_llm 
            mock_llm.ainvoke = AsyncMock(return_value=AIMessage(
                content='''<thought>I should list files.</thought>
```json
{
  "name": "list_workspace_files",
  "arguments": {"directory": "."}
}
```'''
            ))
            
            state = {

                "messages": [HumanMessage(content="list files")],
                "mode": "reasoning",
            }
            
            with patch('src.agent.graph.get_llm', return_value=mock_llm):
                with patch('src.agent.graph.get_persona') as mock_p, \
                     patch('src.agent.graph.get_profile') as mock_pr, \
                     patch('src.agent.graph.memories_to_context') as mock_m:
                     mock_p.return_value = {}
                     mock_pr.return_value = {}
                     mock_m.return_value = ""
                     
                     # Call async node
                     result = await reason_node(state)
            
            self.assertIn("messages", result)
            ans = result["messages"][0]
            self.assertTrue(hasattr(ans, "tool_calls"))
            self.assertEqual(len(ans.tool_calls), 1)
            self.assertEqual(ans.tool_calls[0]["name"], "list_workspace_files")

    def test_reason_node_fast(self):
        async def run_test():
            # Mock LLM
            from unittest.mock import MagicMock
            mock_llm = MagicMock()
            mock_llm.ainvoke = AsyncMock(return_value=AIMessage(
                content='''```json
{
  "name": "list_workspace_files",
  "arguments": {"directory": "."}
}
```'''
            ))
            
            # Fast mode state
            state = {
                "messages": [HumanMessage(content="list files")],
                "mode": "fast",
            }
            
            with patch('src.agent.graph.get_llm', return_value=mock_llm):
                with patch('src.agent.graph.get_persona') as mock_p, \
                     patch('src.agent.graph.get_profile') as mock_pr, \
                     patch('src.agent.graph.memories_to_context') as mock_m:
                     mock_p.return_value = {}
                     mock_pr.return_value = {}
                     mock_m.return_value = ""
                     
                     result = await reason_node(state)
            
            self.assertIn("messages", result)
            ans = result["messages"][0]
            # In fast mode, tool_calls should NOT be populated by the parser
            self.assertFalse(hasattr(ans, "tool_calls") and ans.tool_calls)

        asyncio.run(run_test())

if __name__ == '__main__':
    unittest.main()


