# How-to: Deploy the Plumbing Kit to GKE from Cursor

You're deploying from your own machine instead of Cloud Shell. The steps are the same as `k8s/K8S.md`. This page covers what changes locally, and the order to run things in. Use `K8S.md` for the explanations.

## 0 · Prerequisites on your machine (one time)

| Tool | Why | Check |
|---|---|---|
| Google Cloud CLI (`gcloud`) | auth, builds, cluster | `gcloud --version` |
| `kubectl` + `gke-gcloud-auth-plugin` | talk to the cluster | `gcloud components install kubectl gke-gcloud-auth-plugin` |
| Python 3.12 (optional) | run the chat UI locally | `python --version` |
| Docker (optional) | **not needed**; Cloud Build builds the images | |

**Shell:** the commands are bash. On Windows, use **WSL or Git Bash** in Cursor's terminal and paste commands verbatim. Steps 1 and 3 also have PowerShell versions; everything else runs unchanged in PowerShell except step 6.

**PowerShell and quotes:** PowerShell strips double quotes out of arguments it hands to native programs (`curl.exe`, `kubectl`, `python`), even inside single quotes. A JSON body or a `python -c "..."` script arrives broken. Use `Invoke-RestMethod` for HTTP calls with a body, and pipe scripts on stdin (`$script | kubectl exec -i ... -- python -`).

## 1 · Log in and set variables

```bash
gcloud auth login
gcloud auth application-default login      # only needed to run the chat UI locally against Vertex AI

export PROJECT_ID=your-project-id
export REGION=us-central1
gcloud config set project $PROJECT_ID
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
REPO=$REGION-docker.pkg.dev/$PROJECT_ID/plumbing
```

PowerShell equivalent:
```powershell
$env:PROJECT_ID="your-project-id"; $env:REGION="us-central1"
gcloud config set project $env:PROJECT_ID
$PROJECT_NUMBER = gcloud projects describe $env:PROJECT_ID --format='value(projectNumber)'
```

> Shell variables don't survive a new terminal. If a command complains about an empty value, re-run this step.

## 2 · Project setup, cluster, and images (from the kit's top folder)

```bash
gcloud services enable container.googleapis.com artifactregistry.googleapis.com \
  cloudbuild.googleapis.com aiplatform.googleapis.com secretmanager.googleapis.com

gcloud artifacts repositories create plumbing --repository-format=docker --location=$REGION
gcloud container clusters create-auto plumbing --region $REGION          # ~5-8 min
gcloud container clusters get-credentials plumbing --region $REGION
kubectl get ns                                                           # confirms kubectl is pointed at it

gcloud builds submit deploy/  --tag $REPO/agent:v1
gcloud builds submit chat-ui/ --tag $REPO/chat-ui:v1
```

## 3 · Secret and identity

```bash
kubectl apply -f k8s/00-namespace.yaml

gcloud secrets versions access latest --secret=anthropic-api-key | \
  kubectl -n plumbing create secret generic anthropic-api-key --from-file=ANTHROPIC_API_KEY=/dev/stdin
```

PowerShell equivalent. `/dev/stdin` doesn't exist there, and `--from-literal` would put the key on the command line. This pipes a Secret manifest to `kubectl` instead, so the key stays in memory:
```powershell
$k = (gcloud secrets versions access latest --secret=anthropic-api-key | Out-String).Trim()
$b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($k))
@"
apiVersion: v1
kind: Secret
metadata:
  name: anthropic-api-key
  namespace: plumbing
type: Opaque
data:
  ANTHROPIC_API_KEY: $b64
"@ | kubectl apply -f -
Remove-Variable k, b64
```

Let the chat UI call Vertex AI:
```bash
gcloud projects add-iam-policy-binding $PROJECT_ID --role=roles/aiplatform.user \
  --member="principal://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${PROJECT_ID}.svc.id.goog/subject/ns/plumbing/sa/chat-ui"
```

Then in the Cloud Console: **Vertex AI ▸ Model Garden ▸ Claude ▸ Enable** (one-time, per project).

## 4 · Edit one file, then deploy

In `k8s/kustomization.yaml`, replace `ai-infra-lab-508921` with your project ID (3 places) and check the region and `VERTEX_MODELS`.

```bash
kubectl kustomize k8s/          # optional: preview exactly what will be applied
kubectl apply -k k8s/
kubectl -n plumbing rollout status deploy/plumbing-agent
kubectl -n plumbing rollout status deploy/plumbing-chat-ui
kubectl -n plumbing get pods,svc,hpa
```

## 5 · Open the UI

```bash
kubectl -n plumbing port-forward svc/plumbing-chat-ui 8088:80
```
Open **http://127.0.0.1:8088**. No Cloud Shell web preview is needed. Leave that terminal running.

This uses 8088 rather than 8000 because WSL and Docker Desktop often already listen on 8000, and `localhost` then reaches them instead (you get `{"detail":"Not Found"}`). Check with `Get-NetTCPConnection -LocalPort 8088 -State Listen` if in doubt. The port-forward is tied to one pod: after the chat UI rolls out again, stop it and start it again.

## 6 · Load test and ACL check

Use bash (WSL/Git Bash) for this one, because it relies on `$(cat ...)`:

```bash
kubectl -n plumbing run loadtest --rm -i --restart=Never --labels=agent-client=true \
  --image=python:3.12-slim --command -- \
  python3 -c "$(cat deploy/loadtest.py)" http://plumbing-agent -n 60 -c 30
```
Watch in a second terminal: `kubectl -n plumbing get hpa,pods -w`

## 7 · Optional: run the chat UI locally (no cluster)

```bash
cd chat-ui
python -m venv .venv && source .venv/bin/activate     # Windows (PowerShell): .venv\Scripts\Activate.ps1
pip install -r requirements.txt
export GOOGLE_CLOUD_PROJECT=$PROJECT_ID
uvicorn app:app --port 8088
```
The "Vertex AI model" target works using your `application-default` login. The "agent" target needs `AGENT_URL` pointing at a running agent (for example `deploy/` run with `uvicorn main:app --port 8080`).

## 8 · Cleanup

```bash
kubectl delete namespace plumbing
gcloud container clusters delete plumbing --region $REGION --quiet
gcloud artifacts repositories delete plumbing --location=$REGION --quiet
gcloud projects remove-iam-policy-binding $PROJECT_ID --role=roles/aiplatform.user \
  --member="principal://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${PROJECT_ID}.svc.id.goog/subject/ns/plumbing/sa/chat-ui"
```

## Common snags

| Symptom | Fix |
|---|---|
| `gke-gcloud-auth-plugin not found` | `gcloud components install gke-gcloud-auth-plugin`, then re-run `get-credentials` |
| `kubectl` talks to the wrong cluster | `kubectl config current-context`; re-run `get-credentials` |
| `ImagePullBackOff` | grant `roles/artifactregistry.reader` to `${PROJECT_NUMBER}-compute@developer.gserviceaccount.com` |
| `CreateContainerConfigError` (agent) | the Secret from step 3 is missing |
| UI error `403` from Vertex | IAM binding missing or typo in namespace/service-account name; wait ~1 min |
| UI error `404 ... model not found` | Claude not enabled in Model Garden, a retired Gemini ID (`gemini-2.5-flash`), or wrong `VERTEX_MODELS` / `VERTEX_LOCATION` |
| UI error `429 Quota exceeded ... anthropic-claude-haiku-4-5` | the project's Claude quota is zero; request it in **IAM & Admin ▸ Quotas** |
| `localhost:8000` returns `{"detail":"Not Found"}` | another app owns port 8000; port-forward to 8088 instead |
| Port-forward stops answering after `kubectl apply` | the pod it pointed at was replaced; restart the port-forward |
| `SyntaxError` or `json_invalid` from a PowerShell command | PowerShell stripped the double quotes; use `Invoke-RestMethod` or pipe the script on stdin |
| Empty variable in a command | new terminal lost your `export`s; redo step 1 |
