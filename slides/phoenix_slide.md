# Slide plan: "Observability is a standard, not a vendor"

**Placement:** Block 2, right after the LangSmith traces walkthrough and before evals (about 5 min).
**Goal:** Students leave knowing LangSmith is one tool in a category, and that OpenTelemetry is what keeps traces portable.

---

## On the slide

**Title:** Observability is a standard, not a vendor

**Left: the stack (diagram)**

```
 Your agent (LangGraph, CrewAI, ADK, raw SDK…)
        │  instrumentation
        ▼
 OpenTelemetry spans  ← the open wire format (like IPFIX / NetFlow v9)
        │
        ├──► LangSmith           (SaaS, LangChain-native)
        ├──► Arize Phoenix       (self-host / notebook, OpenInference conventions)
        ├──► Google Cloud Trace  (Agent Runtime exports OTel by default for ADK agents)
        └──► Datadog, Grafana, W&B Weave …
```

**Right: two-column comparison**

| | LangSmith | Arize Phoenix |
|---|---|---|
| Runs where | Hosted SaaS (self-host on enterprise plans) | Your laptop, a notebook, or your own container |
| Signup | Account + API key | None to run locally |
| Sweet spot | LangChain / LangGraph teams that want polish | Teams that want traces to stay in their own environment |
| Built on | Its own SDK; also accepts OTel | OpenTelemetry + OpenInference |

**Footer takeaway (one line):** *Pick the tool for the team. Pick the standard for the decade.*

---

## Talking points

1. **Analogy:** NetFlow/IPFIX let any collector read flows from any router. OpenTelemetry does the same for agent traces: instrument once, send to any backend.
2. **The PM question is "where do my traces live?"** Traces contain prompts, customer messages, and tool outputs. For regulated, healthcare, or defense customers, "in our VPC" can decide the deal, and self-hostable OTel tools answer that.
3. **We used LangSmith today** because it's the least friction with LangGraph and you already have accounts. Nothing we learned (spans, latency, token cost, evals) is LangSmith-specific.
4. **Google is moving the same way:** Agent Runtime turns on OpenTelemetry tracing by default for newly deployed ADK agents. Cloud vendors are converging on the standard.

## Likely student questions

- *"Can I switch later?"* Mostly yes, if you instrument with OTel. Dashboards and saved eval datasets are the sticky parts.
- *"Which one is cheaper?"* Phoenix is free to self-host, but you then run it (compute, storage, upgrades). LangSmith has a free tier and per-seat pricing. That's the same build-vs-buy trade as Cloud Run vs. Agent Runtime in Block 1.
- *"Do I need both?"* No. Some teams send OTel to their existing APM (Datadog, Grafana) and skip LLM-specific tools until they need evals.

## Before class

- Confirm current pricing and free-tier limits on both vendors' sites. These change often.
- Optional live flourish (2 min): in Colab, `pip install arize-phoenix openinference-instrumentation-langchain`, then `phoenix.otel.register(auto_instrument=True)`, run one `pa.run_agent(...)`, and show the same trace in Phoenix's local UI. Rehearse it first; skip it if short on time.
