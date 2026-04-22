import os
import re
import json
from typing import TypedDict, Annotated, List, Dict, Optional
from dotenv import load_dotenv
from datetime import datetime
import pytz
from tools.config_manager import get_secret, get_secrets_list

from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage, AIMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages

from tools.financial_utils import log_transaction, check_history, get_spending_summary
from tools.analytics_tools import generate_chart
from tools.export_tools import export_expenses
from tools.budget_tools import manage_budgets, get_budget_report
from tools.recurring_tools import setup_recurring_bill, list_recurring_bills, remove_recurring_bill

load_dotenv()

OPENROUTER_KEYS = get_secrets_list("OPENROUTER_API_KEY")
AI_MODEL = get_secret("AI_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")
current_key_index = 0
MAX_MEMORY = 10  # Max messages kept per user
IST = pytz.timezone('Asia/Kolkata')

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
    openai_api_key=OPENROUTER_KEYS[0] if OPENROUTER_KEYS else None,
    openai_api_base="https://openrouter.ai/api/v1",
    temperature=0.1,
    max_retries=0, # We handle retries manually for key rotation
    default_headers={"HTTP-Referer": "https://wallet-watch-bot.app", "X-Title": "Wallet Watch"},
)

ALL_TOOLS = [
    log_transaction, check_history, get_spending_summary, generate_chart, 
    export_expenses, manage_budgets, get_budget_report,
    setup_recurring_bill, list_recurring_bills, remove_recurring_bill
]
TOOL_MAP = {t.name: t for t in ALL_TOOLS}
llm_with_tools = llm.bind_tools(ALL_TOOLS)

# ── Graph ──────────────────────────────────────────────────────────────────────
class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]

async def llm_node(state: AgentState):
    global current_key_index
    
    while current_key_index < len(OPENROUTER_KEYS):
        try:
            # Update key in case of previous failure
            llm.openai_api_key = OPENROUTER_KEYS[current_key_index]
            # Bind tools again with the new LLM state if needed
            bound_llm = llm.bind_tools(ALL_TOOLS)
            response = await bound_llm.ainvoke(state["messages"])
            return {"messages": [response]}
        except Exception as e:
            # Check if it's an authentication error
            error_str = str(e).lower()
            if "invalid api key" in error_str or "unauthorized" in error_str or "401" in error_str:
                print(f"⚠️ Key Failover: Key {current_key_index + 1} failed. Trying next...")
                current_key_index += 1
                if current_key_index >= len(OPENROUTER_KEYS):
                    raise e
            else:
                # Other errors (network, etc) should just be raised
                raise e
    
    # Fallback if no keys work
    raise Exception("All provided API keys failed.")

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
- export_expenses: Create a CSV or Excel file of transactions. Handles filters like category or dates.
- manage_budgets: Setup or update monthly limits for categories or 'Total' spend.
- get_budget_report: View progress vs budgets with progress bars.
- setup_recurring_bill: Automate a monthly or multi-month expense or income.
    - If the user says "every 2 months", set `interval=2`.
    - Handle durations with math: "for 2 years every 2 months" = 12 installments.
- list_recurring_bills: Show all active recurring bills in a clean format.
- remove_recurring_bill: You must first `list_recurring_bills` to find the exact description. Then pass the `bill_id`. (Always ask for confirmation before deleting).

How to behave:
- **Currency**: Always use the **Indian Rupee (₹)** symbol. Use Indian numbering if appropriate (Lakhs/Crores).
- **Timezone**: Everything is based on **Indian Standard Time (IST)**.
- **Clean UI**: Never print technical things like "ID: 4" or raw database fields.
- **EMI Logic**: Convert "1 year" or "2 years" into months. Convert "every quarter" to `interval=3`.
- **Gym Example**: "gym 5000 every 2 months for 2 years" -> `amount=5000, interval=2, installments=12`.
- After completing actions, reply with a warm summary in ₹.

Examples:
- "spent ₹200 on lunch"
- "salary ₹50,000"
- "how much did I spend this month?"
- If a user sets multiple budgets at once, use a single call to manage_budgets.
- Always use a tool when action is needed — never invent data.
- After logging an expense, if the tool returns a budget warning, make sure to relay it clearly to the user.
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
            # Check for charts (photos)
            m_chart = re.search(r'CHART_PATH:"([^"]+)"', msg.content)
            if m_chart:
                path = m_chart.group(1)
                if os.path.exists(path):
                    return {"type": "photo", "path": path}
            
            # Check for exports (documents)
            m_export = re.search(r'EXPORT_PATH:"([^"]+)"', msg.content)
            if m_export:
                path = m_export.group(1)
                if os.path.exists(path):
                    return {"type": "document", "path": path}
    return None

# ── Public API ─────────────────────────────────────────────────────────────────
async def run_agent(user_id: int, user_message: str) -> dict:
    """
    Run the agent for a user message.
    Returns: {"text": str, "attachment": None | {"type": "photo", "path": str}}
    """
    human = HumanMessage(content=f"[user_id={user_id}]\n{user_message}")
    
    # 🕵️ Inject today's date for accurate timeframe tool usage
    time_str = datetime.now(IST).strftime("%A, %d %B %Y, %H:%M %p")
    input_messages = [
        SystemMessage(content=SYSTEM_PROMPT + f"\n\n[CONTEXT: Today is {time_str} (IST)]"), 
        *_get_memory(user_id), 
        human
    ]

    result = await agent.ainvoke({"messages": input_messages})
    all_msgs = result["messages"]

    text = _scrub(_to_text(all_msgs[-1].content)) or "Done! Let me know if you need anything else."
    attachment = _find_attachment(all_msgs)

    _update_memory(user_id, human, text)
    return {"text": text, "attachment": attachment}
