# Kansas City Pipe & Supply: Deploy & Monitor kit

One LangGraph quote agent, shipped four ways.

| Where | What | Start here |
|---|---|---|
| Colab | Build it and try it | `01_plumbing_agent_colab.ipynb` |
| Cloud Run | You build the box: Dockerfile, scaling flags, secret | `deploy/DEPLOY.md` |
| Agent Runtime | Google runs the box | `02_agent_runtime_deploy.ipynb` |
| **GKE (Kubernetes)** | Same image, you run the *fleet*; plus a chat front end that also talks to Vertex AI | `k8s/K8S.md` |

`deploy/` is the single source of the agent and its container. `chat-ui/` and `k8s/` only add to it; nothing in `deploy/` or the notebooks was changed.

Run the chat UI on your own machine (no Kubernetes needed):

```bash
cd chat-ui && pip install -r requirements.txt
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT=your-project-id
export AGENT_URL=http://localhost:8080      # optional: run deploy/ locally for the "agent" target
uvicorn app:app --port 8000                 # then open http://localhost:8000
```
