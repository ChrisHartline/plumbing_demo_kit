# Block 3 — Same Container, Now on Kubernetes (GKE Autopilot) + a Chat Front End

Run everything from **Google Cloud Shell**, from the kit's top folder (the one that contains `deploy/`, `chat-ui/`, `k8s/`).

```
plumbing-demo-kit/
├── deploy/      # the agent + Dockerfile (unchanged). Same image runs on Cloud Run AND here
├── chat-ui/     # NEW: one-page chat front end (FastAPI + a single HTML file)
└── k8s/         # NEW: the manifests
    ├── kustomization.yaml       # <- the only file you edit
    ├── 00-namespace.yaml        # the VRF
    ├── 10-serviceaccounts.yaml  # identities
    ├── 20-agent.yaml            # Deployment + Service + HPA
    ├── 30-chat-ui.yaml          # Deployment + Service
    └── 40-networkpolicy.yaml    # the ACLs
```

**What you're building**

```
 you ──port-forward──► chat-ui (pod) ──┬─► plumbing-agent Service ─► agent pods (x2..6) ─► Anthropic API
                          │            │        (ClusterIP, only chat-ui may connect)
                          │            └─► Vertex AI: Claude / Gemini   (Workload Identity, no key)
                          └ identity: KSA "chat-ui" == roles/aiplatform.user
```

---

## 0 · One-time setup

```bash
export PROJECT_ID=your-project-id
export REGION=us-central1
gcloud config set project $PROJECT_ID

gcloud services enable container.googleapis.com artifactregistry.googleapis.com \
  cloudbuild.googleapis.com aiplatform.googleapis.com

# A private place for images (the Cloud Run demo used an auto-created repo; here we name one)
gcloud artifacts repositories create plumbing --repository-format=docker --location=$REGION

# Autopilot = Google runs the nodes; you only declare pods. Takes ~5-8 min. Workload Identity and
# NetworkPolicy enforcement are already on.
gcloud container clusters create-auto plumbing --region $REGION
gcloud container clusters get-credentials plumbing --region $REGION

kubectl get ns     # proves kubectl is pointed at the new cluster
```

> If you ran `DEPLOY.md` step 0 in this project, Cloud Build permissions are already set.

## 1 · Build the two images

```bash
REPO=$REGION-docker.pkg.dev/$PROJECT_ID/plumbing

gcloud builds submit deploy/  --tag $REPO/agent:v1      # the SAME deploy/ folder as Cloud Run
gcloud builds submit chat-ui/ --tag $REPO/chat-ui:v1
```

> **Talking point:** `deploy/` didn't change. A container is the portable unit; Cloud Run and Kubernetes are two different schedulers for it.

## 2 · The Anthropic key: Secret Manager → Kubernetes Secret

Reuses the `anthropic-api-key` secret from `DEPLOY.md` step 1.

```bash
kubectl apply -f k8s/00-namespace.yaml

gcloud secrets versions access latest --secret=anthropic-api-key | \
  kubectl -n plumbing create secret generic anthropic-api-key \
    --from-file=ANTHROPIC_API_KEY=/dev/stdin
```

> **Honest caveat:** a Kubernetes Secret is only base64, readable by anyone with `get secret` in the namespace. It's fine for a class demo. For production, mount straight from Secret Manager with the GKE Secret Manager add-on, or call Claude through Vertex AI and have no key at all (see "Where to go next").

## 3 · Let the chat UI call Vertex AI (no key, just identity)

```bash
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --role=roles/aiplatform.user \
  --member="principal://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${PROJECT_ID}.svc.id.goog/subject/ns/plumbing/sa/chat-ui"
```

That member string reads: *"the Kubernetes service account `chat-ui` in namespace `plumbing`, in this cluster's identity pool."* Google IAM trusts the cluster to vouch for it.

> **Networking analogy:** a shared Anthropic API key is a pre-shared key on a Wi-Fi network: whoever has the string is in. Workload Identity is 802.1X with certificates: each pod proves *who it is*, and there's nothing to leak, rotate, or paste into a chat window.

**For the Claude choice in the dropdown:** open **Vertex AI ▸ Model Garden**, find the Claude model, and click **Enable**. This is a one-time project-level step that the IAM role doesn't cover. Gemini needs no enablement.

## 4 · Point the manifests at your project, then deploy

Edit **`k8s/kustomization.yaml`**: replace `YOUR_PROJECT_ID` in three places (two image names, one `GOOGLE_CLOUD_PROJECT`). Change `us-central1` if you used another region.

```bash
kubectl apply -k k8s/                     # preview first with: kubectl kustomize k8s/
kubectl -n plumbing rollout status deploy/plumbing-agent
kubectl -n plumbing rollout status deploy/plumbing-chat-ui
kubectl -n plumbing get pods,svc,hpa
```

First rollout takes a few minutes while Autopilot adds capacity; "Pending" pods in that window are normal.

## 5 · Open the chat UI

```bash
kubectl -n plumbing port-forward svc/plumbing-chat-ui 8000:80
```

In Cloud Shell: **Web Preview ▸ Preview on port 8000**. (That preview URL only works for your own Google login.)

- **Plumbing agent (in cluster):** the browser talks to `chat-ui`, which calls the agent Service by name. The footer of each reply shows which **agent pod** answered.
- **A Vertex AI model:** pick Claude or Gemini from the dropdown. Same UI, but the call goes straight to Vertex AI with the pod's identity.

> **Point for PMs:** put the same question to both. The agent *knows the inventory* (a lookup step that isn't the LLM); the raw model doesn't, and will cheerfully invent a plausible answer. That gap is why you build agents.

## 6 · The deep freeze, on Kubernetes

Run the same `loadtest.py` from *inside* the cluster. The throwaway pod carries the `agent-client=true` label, the key that the NetworkPolicy checks.

```bash
kubectl -n plumbing run loadtest --rm -i --restart=Never --labels=agent-client=true \
  --image=python:3.12-slim --command -- \
  python3 -c "$(cat deploy/loadtest.py)" http://plumbing-agent -n 60 -c 30
```

Look at the last line, **Served by revision(s)**: on Kubernetes these are *pod names*, so you can see how many replicas took traffic.

In a second terminal, while it runs:

```bash
kubectl -n plumbing get hpa,pods -w
```

**Predict before you look:** will the HPA add pods? Probably not much. The agent spends its time *waiting on the model*, so CPU stays low even when requests are stacking up. CPU is the wrong signal for this workload. In-flight requests or queue depth is the right one, and that's what KEDA scales on.

**Prove the ACL works** (this should hang, then fail, because the pod lacks the label):

```bash
kubectl -n plumbing run intruder --rm -i --restart=Never --image=python:3.12-slim --command -- \
  python3 -c "import urllib.request as u; print(u.urlopen('http://plumbing-agent', timeout=5).read())"
```

## 7 · Cloud Run vs. Kubernetes: the same knobs, different names

| Cloud Run | Kubernetes | Networking analogy |
|---|---|---|
| `--max-instances` | HPA `maxReplicas` | How many ECMP paths you're allowed to light up |
| `--min-instances` | `replicas` / HPA `minReplicas` | Keepalive: established neighbor vs. starting from Idle |
| `--concurrency` | *No equivalent.* Nothing caps requests per pod; uvicorn's thread pool is the de facto limit | An interface with no policer: the box accepts until it falls over |
| Revision (immutable) | Deployment rollout (ReplicaSet per version) | Candidate config vs. running config; `kubectl rollout undo` = rollback |
| Cloud Run URL | Service (ClusterIP VIP + DNS name) | A VIP in front of a pool |
| Cloud Run health check | Readiness probe (traffic) + liveness probe (restart) | Pool-member monitor vs. watchdog |
| `--no-allow-unauthenticated` | ClusterIP + NetworkPolicy | Default-deny ACL with explicit permits |
| Scale to zero (free) | Not by default; needs KEDA/Knative | n/a |

**One thing that surprises people:** the Service balances per *connection*, not per request. A client holding one keep-alive connection can stick to one pod, like too few flows hashing onto one ECMP path. The in-cluster load test uses many connections, which is why it spreads.

## 8 · Sharing it

The UI is `ClusterIP` on purpose: it can spend Vertex AI credits, and it has no login. **Don't switch it to `type: LoadBalancer`.** That's the same open relay `DEPLOY.md` warned about. To let others in, put it behind **Identity-Aware Proxy** on a GKE Gateway so only named Google accounts reach it. When you add a Gateway, add a NetworkPolicy rule for its health-check ranges.

## 9 · Cleanup

```bash
kubectl delete namespace plumbing
gcloud container clusters delete plumbing --region $REGION --quiet
gcloud artifacts repositories delete plumbing --location=$REGION --quiet
gcloud projects remove-iam-policy-binding $PROJECT_ID --role=roles/aiplatform.user \
  --member="principal://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${PROJECT_ID}.svc.id.goog/subject/ns/plumbing/sa/chat-ui"
```

---

### Fallbacks if something stalls
- **`ImagePullBackOff`:** the cluster's node service account can't read Artifact Registry. Grant it `roles/artifactregistry.reader` (the node SA is usually the default compute SA: `${PROJECT_NUMBER}-compute@developer.gserviceaccount.com`). Confirm with `kubectl -n plumbing describe pod <name>`.
- **`CreateContainerConfigError` on the agent:** the `anthropic-api-key` Secret doesn't exist yet. Redo step 2; the pod retries on its own.
- **Chat UI shows `Vertex AI call failed: ... 403`:** the IAM binding in step 3 is missing or has a typo in the namespace or service account name. Allow a minute for IAM to propagate.
- **`... 404 ... model not found`** (Claude): you haven't enabled it in Model Garden, or the model ID or `VERTEX_LOCATION` isn't available to your project. Fix `VERTEX_MODELS` / `VERTEX_LOCATION` in `kustomization.yaml` and re-run `kubectl apply -k k8s/`.
- **Pods `Pending` for minutes:** Autopilot is provisioning. `kubectl -n plumbing describe pod <name>` shows events if it's something else (quota, for example).
- **`401`/`403` using `loadtest.py` from your own terminal:** inside the cluster there is no token. Don't pass `--token` to the in-cluster run.

### Where to go next
- **Drop the Anthropic key entirely:** run the agent's model through Claude on Vertex AI (LangChain's `ChatAnthropicVertex`), give the agent its own Workload Identity service account, and delete the Secret.
- **Scale on the right signal:** replace the CPU-based HPA with KEDA scaling on queue depth or in-flight requests.
- **Call a dedicated Vertex AI Endpoint** (a model you deployed yourself) instead of a publisher model: add a third target in `chat-ui/app.py`.
