from langchain_core.messages import SystemMessage, AIMessage
from src.agent.state import AgentState
from src.agent.llm import get_small_llm
from src.agent.response_styles import style_instruction_for_prompt
from src.agent.lm_studio_compat import with_system_for_local_server
import re

SIMPLE_PROMPT = """You are a quick, plain assistant. Answer in as few words as fit: usually 1–3 short sentences unless the user clearly wants detail. No tools. No chain-of-thought, no "let me think", no meta commentary.
Memory context (use only if relevant):
{memory_context}{style_hint}"""

def _strip_thinking(text: str) -> str:
    """Remove thinking/reasoning blocks from model output."""
    if not text:
        return text
    # Strip <think>...</think> blocks (Qwen3.5 reasoning format)
    cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
    # Strip numbered reasoning steps (abliterated model style)
    # Look for the actual answer after reasoning — usually after a line like "Hi Tim..."
    # or after the last numbered step
    lines = cleaned.split('\n')
    # Find the last line that looks like an actual response (not a reasoning step)
    answer_lines = []
    in_reasoning = False
    for line in lines:
        stripped = line.strip()
        # Skip reasoning markers
        if re.match(r'^\d+\.\s+\*\*', stripped) or re.match(r'^\s+\*\s+', stripped):
            in_reasoning = True
            continue
        if stripped.startswith('Thinking Process:') or stripped.startswith('Reasoning:'):
            in_reasoning = True
            continue
        if stripped.startswith('Analysis:') or stripped.startswith('Step '):
            in_reasoning = True
            continue
        if not stripped:
            if in_reasoning:
                continue
        if stripped and not stripped.startswith('*'):
            in_reasoning = False
            answer_lines.append(line)
    result = '\n'.join(answer_lines).strip()
    # If we stripped everything, try extracting quoted content from reasoning
    if not result:
        quotes = re.findall(r'"([^"]{5,})"', cleaned)
        if quotes:
            result = quotes[-1]
    return result if result else text

async def simple_node(state: AgentState) -> AgentState:
    memory_context = state.get("memory_context", "None")
    style_hint = style_instruction_for_prompt(state.get("response_style"))
    small_llm = await get_small_llm()
    chat_llm = small_llm.bind(temperature=0.35, max_tokens=384)
    system = SystemMessage(
        content=SIMPLE_PROMPT.format(
            memory_context=memory_context,
            style_hint=style_hint,
        )
    )
    prompt_messages = with_system_for_local_server(system, list(state["messages"]))
    response = await chat_llm.ainvoke(prompt_messages)
    content = _strip_thinking(response.content or "")
    return {
        "messages": [AIMessage(content=content)],
        "model_used": "small"
    }
