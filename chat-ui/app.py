"""
app.py — a VERY simple chat front end. One page, one endpoint, two kinds of target.

  target "agent"   -> the plumbing agent running next to us in the cluster (POST {AGENT_URL}/quote)
  target "vertex"  -> a model on Vertex AI, called directly (Claude or Gemini)

The browser never sees a credential. This pod authenticates to Vertex AI with Workload Identity
(no key file, no secret): the Kubernetes service account IS the identity. Locally it falls back
to your `gcloud auth application-default login`.

Run locally:
  export GOOGLE_CLOUD_PROJECT=your-project-id
  export AGENT_URL=http://localhost:8080          # optional: only needed for the "agent" target
  uvicorn app:app --port 8000

Env vars:
  GOOGLE_CLOUD_PROJECT  required for the "vertex" target
  VERTEX_LOCATION       default "global"  (Claude's recommended endpoint; Gemini accepts it too)
  VERTEX_MODELS         comma list shown in the dropdown, default below. Check Model Garden for
                        the IDs your project can use. IDs starting with "claude" go through the
                        Anthropic SDK; everything else goes through the Google GenAI SDK.
  AGENT_URL             default http://plumbing-agent  (the in-cluster Service name)
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "")
LOCATION = os.getenv("VERTEX_LOCATION", "global")
AGENT_URL = os.getenv("AGENT_URL", "http://plumbing-agent").rstrip("/")
MODELS = [m.strip() for m in os.getenv(
    "VERTEX_MODELS", "claude-haiku-4-5@20251001,gemini-2.5-flash").split(",") if m.strip()]
POD = os.getenv("HOSTNAME", "local")

SYSTEM = "You are a concise, friendly assistant. Keep answers under 150 words."
MAX_CHARS = 2000      # per message
MAX_TURNS = 20        # history we will forward; keeps one tab from running up a token bill

app = FastAPI(title="Plumbing chat front end")


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=MAX_CHARS)


class ChatRequest(BaseModel):
    target: Literal["agent", "vertex"]
    model: str = ""
    messages: list[Turn] = Field(min_length=1, max_length=MAX_TURNS)


@app.get("/")
def page():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/healthz")
def healthz():
    return {"status": "ok", "pod": POD}


@app.get("/api/config")
def config():
    return {"models": MODELS, "project_set": bool(PROJECT), "location": LOCATION, "pod": POD}


@app.post("/api/chat")
def chat(req: ChatRequest):
    if req.messages[-1].role != "user":
        raise HTTPException(400, "last message must be from the user")
    t0 = time.perf_counter()
    out = _ask_agent(req) if req.target == "agent" else _ask_vertex(req)
    out["round_trip_ms"] = round((time.perf_counter() - t0) * 1000)
    out["ui_pod"] = POD
    return out


# ---------------------------------------------------------------------------
# target: the plumbing agent (single-turn quoting agent, so only the last message goes)
# ---------------------------------------------------------------------------
def _ask_agent(req: ChatRequest) -> dict:
    try:
        r = httpx.post(f"{AGENT_URL}/quote", json={"message": req.messages[-1].content}, timeout=120)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Could not reach the agent at {AGENT_URL}: {type(e).__name__}")
    if r.status_code == 429:
        raise HTTPException(429, "The agent is rate limited upstream. Try again in a moment.")
    if r.status_code >= 400:
        raise HTTPException(502, f"Agent returned HTTP {r.status_code}")
    d = r.json()
    return {
        "reply": d.get("reply", ""),
        "model": d.get("model"),
        "input_tokens": d.get("input_tokens", 0),
        "output_tokens": d.get("output_tokens", 0),
        "backend_ms": d.get("latency_ms"),
        "served_by": d.get("revision"),            # the agent pod name (see k8s/20-agent.yaml)
        "order_total": d.get("order_total", 0.0),
    }


# ---------------------------------------------------------------------------
# target: a model on Vertex AI
# ---------------------------------------------------------------------------
def _ask_vertex(req: ChatRequest) -> dict:
    if not PROJECT:
        raise HTTPException(500, "GOOGLE_CLOUD_PROJECT is not set on the chat-ui pod")
    if req.model not in MODELS:                    # allow-list: the browser can't pick arbitrary models
        raise HTTPException(400, f"model must be one of {MODELS}")
    history = [{"role": m.role, "content": m.content} for m in req.messages]
    t0 = time.perf_counter()
    try:
        if req.model.startswith("claude"):
            reply, tin, tout = _claude(req.model, history)
        else:
            reply, tin, tout = _gemini(req.model, history)
    except HTTPException:
        raise
    except Exception as e:  # permissions, quota, bad model ID, region: show the real cause
        raise HTTPException(502, f"Vertex AI call failed: {type(e).__name__}: {str(e)[:300]}")
    return {
        "reply": reply, "model": req.model, "input_tokens": tin, "output_tokens": tout,
        "backend_ms": round((time.perf_counter() - t0) * 1000), "served_by": POD,
    }


def _claude(model: str, history: list[dict]) -> tuple[str, int, int]:
    from anthropic import AnthropicVertex
    msg = AnthropicVertex(project_id=PROJECT, region=LOCATION).messages.create(
        model=model, max_tokens=600, system=SYSTEM, messages=history)
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    return text, msg.usage.input_tokens, msg.usage.output_tokens


def _gemini(model: str, history: list[dict]) -> tuple[str, int, int]:
    from google import genai
    from google.genai import types
    client = genai.Client(vertexai=True, project=PROJECT, location=LOCATION)
    contents = [types.Content(role="user" if m["role"] == "user" else "model",
                              parts=[types.Part(text=m["content"])]) for m in history]
    resp = client.models.generate_content(
        model=model, contents=contents,
        config=types.GenerateContentConfig(system_instruction=SYSTEM, max_output_tokens=600))
    u = resp.usage_metadata
    return (resp.text or ""), (u.prompt_token_count or 0), (u.candidates_token_count or 0)
