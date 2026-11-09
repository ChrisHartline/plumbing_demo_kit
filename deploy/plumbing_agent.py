"""
plumbing_agent.py — Kansas City Pipe & Supply: counter-desk quoting agent.

ONE file, used three ways:
  1. Imported in the Colab notebook  (build + try it)
  2. Imported by main.py in Cloud Run (deploy + scale)
  3. Traced/evaluated by LangSmith    (monitor + evaluate)

Graph:  START -> extract -> (lookup) -> respond -> END
  extract  : LLM reads the customer message, picks SKUs + quantities (structured output)
  lookup   : plain Python — stock, price, delivery. No LLM. Deterministic = testable.
  respond  : LLM writes the reply using ONLY the lookup facts.

Env vars:
  ANTHROPIC_API_KEY   required
  ANTHROPIC_MODEL     optional, default claude-haiku-4-5-20251001
  ANTHROPIC_MAX_RETRIES optional, default 2 (set 0 to see raw 429s in the load test)
  ANTHROPIC_TEMPERATURE optional, unset by default (some newer models reject it)
  LANGSMITH_TRACING / LANGSMITH_API_KEY / LANGSMITH_PROJECT  optional (Block 2)
"""

from __future__ import annotations

import os
import time
from typing import Literal, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from langsmith import traceable
from pydantic import BaseModel, Field

DEFAULT_MODEL = "claude-haiku-4-5-20251001"

# ---------------------------------------------------------------------------
# 1. The "database" — a dict. In production this is an inventory API or SQL.
# ---------------------------------------------------------------------------
CATALOG: dict[str, dict] = {
    "PEX-12-ELB":   {"name": '1/2" PEX crimp elbow, 90°, brass',        "price": 1.89,  "stock": 600},
    "PEX-34-ELB":   {"name": '3/4" PEX crimp elbow, 90°, brass',        "price": 2.79,  "stock": 25},
    "PEX-12-TEE":   {"name": '1/2" PEX crimp tee, brass',               "price": 2.29,  "stock": 400},
    "PEX-34-TEE":   {"name": '3/4" PEX crimp tee, brass',               "price": 3.49,  "stock": 150},
    "PEX-12-100R":  {"name": '1/2" PEX-A pipe, 100 ft roll, red (hot)', "price": 54.00, "stock": 40},
    "PEX-12-100B":  {"name": '1/2" PEX-A pipe, 100 ft roll, blue (cold)', "price": 54.00, "stock": 38},
    "PEX-34-100R":  {"name": '3/4" PEX-A pipe, 100 ft roll, red (hot)', "price": 89.00, "stock": 12},
    "RING-12-100":  {"name": '1/2" copper crimp rings, bag of 100',     "price": 18.50, "stock": 80},
    "TOOL-CRIMP":   {"name": 'PEX crimp tool, 1/2" and 3/4" jaws',      "price": 64.99, "stock": 9},
    "HEAT-CABLE-6": {"name": "Self-regulating pipe heat cable, 6 ft",   "price": 39.95, "stock": 0},
    "FOAM-12-6":    {"name": '1/2" foam pipe insulation, 6 ft',         "price": 2.49,  "stock": 1200},
    "PTC-34-CPL":   {"name": '3/4" push-to-connect coupling',           "price": 9.98,  "stock": 60},
    "VALVE-34":     {"name": '3/4" brass ball valve, full port',        "price": 14.75, "stock": 45},
}

BULK_TIERS = [(100, 0.10), (50, 0.05)]  # (min qty, discount) — checked top-down


# ---------------------------------------------------------------------------
# 2. Deterministic tools. @traceable makes each one its own span in LangSmith.
# ---------------------------------------------------------------------------
@traceable(name="check_stock")
def check_stock(sku: str, qty: int) -> dict:
    on_hand = CATALOG[sku]["stock"]
    ship_now = min(on_hand, qty)
    return {"on_hand": on_hand, "ship_now": ship_now, "backorder": qty - ship_now}


@traceable(name="quote_price")
def quote_price(sku: str, qty: int) -> dict:
    unit = CATALOG[sku]["price"]
    discount = next((d for min_q, d in BULK_TIERS if qty >= min_q), 0.0)
    total = round(unit * qty * (1 - discount), 2)
    return {"unit_price": unit, "discount": discount, "line_total": total}


@traceable(name="delivery_estimate")
def delivery_estimate(ship_now: int, backorder: int) -> str:
    if backorder == 0:
        return "next business day"
    if ship_now == 0:
        return "backordered — about 5 business days"
    return f"{ship_now} next business day, remaining {backorder} in about 5 business days"


# ---------------------------------------------------------------------------
# 3. Structured output the extract step must return.
# ---------------------------------------------------------------------------
class LineRequest(BaseModel):
    sku: Optional[str] = Field(description="Exact SKU from the catalog, or null if we don't carry it")
    description: str = Field(description="What the customer asked for, in their words")
    quantity: int = Field(ge=1, description="Quantity requested; 1 if not stated")


class Extraction(BaseModel):
    intent: Literal["order_inquiry", "product_question", "out_of_scope"]
    items: list[LineRequest] = Field(default_factory=list)


class AgentState(TypedDict, total=False):
    message: str
    intent: str
    items: list[dict]
    lines: list[dict]
    order_total: float
    reply: str
    input_tokens: int
    output_tokens: int


# ---------------------------------------------------------------------------
# 4. LLM plumbing (lazy, so importing this file never needs an API key).
# ---------------------------------------------------------------------------
_llm = None


def get_llm():
    global _llm
    if _llm is None:
        from langchain_anthropic import ChatAnthropic

        kwargs = dict(
            model=os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL),
            max_tokens=800,
            max_retries=int(os.getenv("ANTHROPIC_MAX_RETRIES", "2")),
        )
        # Some newer Claude models reject `temperature`, so it's opt-in only.
        if os.getenv("ANTHROPIC_TEMPERATURE"):
            kwargs["temperature"] = float(os.environ["ANTHROPIC_TEMPERATURE"])
        _llm = ChatAnthropic(**kwargs)
    return _llm


def _catalog_text() -> str:
    return "\n".join(f"{sku}: {v['name']}" for sku, v in CATALOG.items())


EXTRACT_PROMPT = """You are the order desk at Kansas City Pipe & Supply.
Read the customer message and identify each product they want and how many.
Map each product to an exact SKU from this catalog. If we don't carry it, set sku to null.

CATALOG:
{catalog}

Intent rules:
- order_inquiry: they want price, availability, or to buy specific items
- product_question: they ask whether we carry something or which item fits
- out_of_scope: anything unrelated to buying plumbing supplies"""

REPLY_PROMPT = """You are the order desk at Kansas City Pipe & Supply. Write a short, friendly reply
to the customer. Use ONLY the facts in ORDER LINES — never invent prices, stock, or dates.
Mention bulk discounts when applied. For items we don't carry, say so plainly.
Plain text, no markdown tables, under 120 words.

CUSTOMER MESSAGE:
{message}

ORDER LINES:
{lines}

ORDER TOTAL: ${total:.2f}"""

OUT_OF_SCOPE_REPLY = (
    "Thanks for reaching out! I can help with plumbing supplies — pricing, stock, "
    "and delivery. What can I look up for you?"
)


def _tokens(msg) -> tuple[int, int]:
    u = getattr(msg, "usage_metadata", None) or {}
    return u.get("input_tokens", 0), u.get("output_tokens", 0)


# ---------------------------------------------------------------------------
# 5. Graph nodes.
# ---------------------------------------------------------------------------
def extract(state: AgentState) -> AgentState:
    llm = get_llm().with_structured_output(Extraction, include_raw=True)
    result = llm.invoke([
        ("system", EXTRACT_PROMPT.format(catalog=_catalog_text())),
        ("human", state["message"]),
    ])
    parsed: Extraction = result["parsed"]
    tin, tout = _tokens(result["raw"])
    return {
        "intent": parsed.intent,
        "items": [i.model_dump() for i in parsed.items],
        "input_tokens": state.get("input_tokens", 0) + tin,
        "output_tokens": state.get("output_tokens", 0) + tout,
    }


def lookup(state: AgentState) -> AgentState:
    lines = []
    for item in state.get("items", []):
        sku, qty = item.get("sku"), item["quantity"]
        if sku not in CATALOG:
            lines.append({"sku": None, "requested": item["description"], "quantity": qty,
                          "status": "not carried"})
            continue
        stock = check_stock(sku, qty)
        price = quote_price(sku, qty)
        lines.append({
            "sku": sku, "name": CATALOG[sku]["name"], "quantity": qty, **price, **stock,
            "delivery": delivery_estimate(stock["ship_now"], stock["backorder"]),
        })
    total = round(sum(l.get("line_total", 0) for l in lines), 2)
    return {"lines": lines, "order_total": total}


def respond(state: AgentState) -> AgentState:
    if state.get("intent") == "out_of_scope":
        return {"reply": OUT_OF_SCOPE_REPLY}
    msg = get_llm().invoke(REPLY_PROMPT.format(
        message=state["message"],
        lines="\n".join(str(l) for l in state.get("lines", [])) or "(none)",
        total=state.get("order_total", 0.0),
    ))
    tin, tout = _tokens(msg)
    return {
        "reply": msg.content if isinstance(msg.content, str) else str(msg.content),
        "input_tokens": state.get("input_tokens", 0) + tin,
        "output_tokens": state.get("output_tokens", 0) + tout,
    }


def route_after_extract(state: AgentState) -> str:
    return "respond" if state.get("intent") == "out_of_scope" else "lookup"


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("extract", extract)
    g.add_node("lookup", lookup)
    g.add_node("respond", respond)
    g.add_edge(START, "extract")
    g.add_conditional_edges("extract", route_after_extract, {"lookup": "lookup", "respond": "respond"})
    g.add_edge("lookup", "respond")
    g.add_edge("respond", END)
    return g.compile()


graph = build_graph()


def run_agent(message: str) -> dict:
    """Convenience wrapper: one customer message in, one result dict out (with timing)."""
    t0 = time.perf_counter()
    out = graph.invoke({"message": message})
    out["latency_ms"] = round((time.perf_counter() - t0) * 1000)
    out["model"] = os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL)
    return out
