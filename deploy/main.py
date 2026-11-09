"""
main.py — wraps the agent in an HTTP contract so anything (a website, n8n, a load test)
can call it. A notebook is a conversation; a service is a contract.

Run locally:   uvicorn main:app --port 8080
Cloud Run sets $PORT and starts it via the Dockerfile CMD.
"""

import os

import anthropic
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from plumbing_agent import DEFAULT_MODEL, run_agent

app = FastAPI(title="Kansas City Pipe & Supply — Quote Agent")


class QuoteRequest(BaseModel):
    message: str


@app.get("/")
def health():
    # Cloud Run doesn't require a health route, but humans (and uptime checks) like one.
    return {"status": "ok", "model": os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL),
            "revision": os.getenv("K_REVISION", "local")}


@app.post("/quote")
def quote(req: QuoteRequest):
    # A plain `def` (not `async def`): FastAPI runs it in a thread pool, so one
    # container can work several requests at once — up to Cloud Run's --concurrency.
    try:
        out = run_agent(req.message)
    except anthropic.RateLimitError as e:
        # The upstream provider said "slow down." Pass that through honestly as a 429,
        # tagged so the load test can tell it apart from Cloud Run's own 429.
        return JSONResponse(status_code=429,
                            content={"error": "upstream_rate_limit", "detail": str(e)[:200]})
    except anthropic.APIStatusError as e:
        return JSONResponse(status_code=503,
                            content={"error": "upstream_error", "status": e.status_code})

    return {
        "reply": out.get("reply"),
        "intent": out.get("intent"),
        "lines": out.get("lines", []),
        "order_total": out.get("order_total", 0.0),
        "input_tokens": out.get("input_tokens", 0),
        "output_tokens": out.get("output_tokens", 0),
        "latency_ms": out["latency_ms"],
        "model": out["model"],
        "revision": os.getenv("K_REVISION", "local"),
    }
