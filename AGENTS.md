## Learned User Preferences

- Keep the Anthropic API key out of the repo, out of any file that is kept, and off the shell command line. Paste it only at a prompt; the quoted `Read-Host` text is the label, not the value. Secret Manager stores it, and Cloud Run injects it as `ANTHROPIC_API_KEY`.
- On PowerShell, quote `gcloud` `--set-secrets` and `--set-env-vars` so a comma is not split into a separate argument. Keep the API-key step as its own command block, separate from deploy.

## Learned Workspace Facts

- This repository is a teaching kit for a class on scaling agentic AI systems.
- `slides/` is discussed in class. The same LangGraph quote agent ships four ways: Colab (`01_plumbing_agent_colab.ipynb`, `02_agent_runtime_deploy.ipynb`), Cloud Run (`deploy/`, FastAPI `POST /quote`), Agent Runtime, and GKE. `deploy/` is the container for both Cloud Run and the cluster; `k8s/` and `chat-ui/` only add to it.
- Cloud Run target is GCP project `ai-infra-lab-508921`, region `us-central1`, service `plumbing-agent`. The initial live deploy is private, with concurrency 1 and max instances 1.
- The runtime secret is `anthropic-api-key`, attached as `ANTHROPIC_API_KEY=anthropic-api-key:latest`, with `ANTHROPIC_MODEL=claude-haiku-4-5-20251001` and `ANTHROPIC_MAX_RETRIES=0`.
- GKE notes are `k8s/K8S.md`: Autopilot cluster and Artifact Registry repo both named `plumbing`, chat UI reached by port-forward and left `ClusterIP` on purpose. Local steps are `HOWTO-deploy-from-cursor.md` and are bash (WSL or Git Bash on this machine). `README.md` is the four-way map.
- The Cloud Run image is in Artifact Registry repo `cloud-run-source-deploy` (`plumbing-agent`). The GKE script builds a separate `plumbing` repo (`agent:v1`, `chat-ui:v1`). Agent pods read a Kubernetes copy of `anthropic-api-key`; `chat-ui` calls Vertex AI as its own service account and does not use that key.
- Cloud Run steps for Cloud Shell and Windows PowerShell both live in `deploy/DEPLOY.md`.
