import os
import re
import json
from typing import TypedDict, Annotated, List, Dict, Optional
from dotenv import load_dotenv

from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage, AIMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages

from tools.financial_utils import log_transaction, check_history, get_spending_summary
from tools.analytics_tools import generate_chart

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
AI_MODEL = os.getenv("AI_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")
MAX_MEMORY = 10  # Max messages kept per user

# ── Per-user Memory ────────────────────────────────────────────────────────────
user_memory: Dict[int, List[BaseMessage]] = {}

def _get_memory(user_id: int) -> List[BaseMessage]:
    return user_memory.get(user_id, [])

def _update_memory(user_id: int, human: HumanMessage, ai_text: str):
    mem = user_memory.setdefault(user_id, [])
    mem.append(human)
    mem.append(AIMessage(content=ai_text))
    user_memory[user_id] = mem[-MAX_MEMORY:]

# ── LLM + Tools ────────────────────────────────────────────────────────────────
llm = ChatOpenAI(
    model=AI_MODEL,
    openai_api_key=OPENROUTER_API_KEY,
    openai_api_base="https://openrouter.ai/api/v1",
    temperature=0.1,
    default_headers={"HTTP-Referer": "https://wallet-watch-bot.app", "X-Title": "Wallet Watch"},
)

ALL_TOOLS = [log_transaction, check_history, get_spending_summary, generate_chart]
TOOL_MAP = {t.name: t for t in ALL_TOOLS}
llm_with_tools = llm.bind_tools(ALL_TOOLS)

# ── Graph ──────────────────────────────────────────────────────────────────────
class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]

async def llm_node(state: AgentState):
    response = await llm_with_tools.ainvoke(state["messages"])
    return {"messages": [response]}

async def tool_node(state: AgentState):
    last = state["messages"][-1]
    outputs = []
    for call in last.tool_calls:
        name, args = call["name"], call["args"]
        print(f"🛠️  {name}({args})")
        result = TOOL_MAP[name].invoke(args) if name in TOOL_MAP else f"Unknown tool: {name}"
        outputs.append(ToolMessage(content=str(result), tool_call_id=call["id"]))
    return {"messages": outputs}

def route(state: AgentState):
    return "tools" if state["messages"][-1].tool_calls else END

graph = StateGraph(AgentState)
graph.add_node("llm", llm_node)
graph.add_node("tools", tool_node)
graph.add_edge(START, "llm")
graph.add_conditional_edges("llm", route)
graph.add_edge("tools", "llm")
agent = graph.compile()

# ── System Prompt ──────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """
You are Wallet Watch 💰 — a friendly, smart personal finance assistant on Telegram.

Available tools:
- log_transaction: Record an expense or income.
- check_history: Fetch recent transactions.
- get_spending_summary: Get total money spent.
- generate_chart: Create a chart (pie/line/bar) for a given time period.

How to behave:
- Understand natural language: "spent 200 on food", "got paid 5000", "show charts", etc.
- Always use a tool when action is needed — never invent data.
- For chart requests: if the user specifies a chart type, call generate_chart directly.
  If vague, ask: "Which chart? Pie (categories), Line (trends), or Bar (income vs expense)?"
- After completing a tool action, reply with a short, warm confirmation.
- Never mention file paths, JSON, technical details, or raw data in your replies.
- Use the conversation history to give contextual, helpful responses.
"""

# ── Helpers ───────────────────────────────────────────────────────────────────
def _to_text(raw: str) -> str:
    """Extract clean plain text from LLM response (handles JSON content blocks)."""
    s = raw.strip()
    if s.startswith("["):
        try:
            parts = [b["text"] for b in json.loads(s) if isinstance(b, dict) and b.get("type") == "text"]
            if parts:
                return "\n".join(parts).strip()
        except Exception:
            pass
    if s.startswith("{"):
        try:
            obj = json.loads(s)
            if "text" in obj:
                return str(obj["text"]).strip()
        except Exception:
            pass
    found = re.findall(r'"text"\s*:\s*"((?:[^"\\]|\\.)*)"', s, re.DOTALL)
    if found:
        parts = []
        for f in found:
            try:
                parts.append(f.encode().decode("unicode_escape"))
            except Exception:
                parts.append(f)
        return "\n".join(parts).strip()
    return s

def _scrub(text: str) -> str:
    """Remove any leaked file path / CHART_PATH artifacts from text."""
    text = re.sub(r'CHART_PATH:"[^"]+"', "", text)
    text = re.sub(r'CHART_PATH:\S+', "", text)
    text = re.sub(r'/\S+\.png', "", text)
    return text.strip()

def _find_attachment(messages: List[BaseMessage]) -> Optional[dict]:
    """Scan tool results for a generated file — infrastructure only, not business logic."""
    for msg in reversed(messages):
        if isinstance(msg, ToolMessage):
            m = re.search(r'CHART_PATH:"([^"]+)"', msg.content)
            if m:
                path = m.group(1)
                if os.path.exists(path):
                    return {"type": "photo", "path": path}
    return None

# ── Public API ─────────────────────────────────────────────────────────────────
async def run_agent(user_id: int, user_message: str) -> dict:
    """
    Run the agent for a user message.
    Returns: {"text": str, "attachment": None | {"type": "photo", "path": str}}
    """
    human = HumanMessage(content=f"[user_id={user_id}]\n{user_message}")
    input_messages = [SystemMessage(content=SYSTEM_PROMPT), *_get_memory(user_id), human]

    result = await agent.ainvoke({"messages": input_messages})
    all_msgs = result["messages"]

    text = _scrub(_to_text(all_msgs[-1].content)) or "Done! Let me know if you need anything else."
    attachment = _find_attachment(all_msgs)

    _update_memory(user_id, human, text)
    return {"text": text, "attachment": attachment}
