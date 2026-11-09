# Block 1 — Deploy the Plumbing Agent to Cloud Run

Run everything from **Google Cloud Shell** (gcloud and auth are already set up there).
Upload this `deploy/` folder to Cloud Shell (⋮ menu ▸ Upload), then `cd deploy`.

```
deploy/
├── plumbing_agent.py   # the agent — same file the Colab notebook uses
├── main.py             # FastAPI wrapper: POST /quote, GET /
├── requirements.txt    # pinned versions
├── Dockerfile          # the container recipe
├── .gcloudignore       # keeps loadtest.py and this file out of the image
└── loadtest.py         # "deep freeze" surge — stdlib only
```

---

## 0 · One-time project setup (do this before class)

```bash
export PROJECT_ID=your-project-id
export REGION=us-central1
gcloud config set project $PROJECT_ID

gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com

PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

# Let Cloud Build build source deploys
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA}" --role=roles/run.builder
```

## 1 · Secrets — the key never goes in the image

```bash
read -s -p "Anthropic API key: " KEY && printf '%s' "$KEY" | \
  gcloud secrets create anthropic-api-key --data-file=- && unset KEY

gcloud secrets add-iam-policy-binding anthropic-api-key \
  --member="serviceAccount:${SA}" --role=roles/secretmanager.secretAccessor
```

> **Talking point:** In Colab the key lived in `userdata`. Here it lives in Secret Manager and is
> injected as an env var at runtime. The container image could be published and the key wouldn't leak.

## 2 · Deploy — deliberately tiny

```bash
gcloud run deploy plumbing-agent \
  --source . \
  --region $REGION \
  --no-allow-unauthenticated \
  --set-secrets ANTHROPIC_API_KEY=anthropic-api-key:latest \
  --set-env-vars ANTHROPIC_MODEL=claude-haiku-4-5-20251001,ANTHROPIC_MAX_RETRIES=0 \
  --concurrency 1 \
  --max-instances 1
```

Takes ~2–4 min the first time (Cloud Build builds the Dockerfile, pushes to Artifact Registry, Cloud Run rolls out a revision).
Narrate while it builds: **Dockerfile → image → registry → revision → URL.**

> **Why `--no-allow-unauthenticated`?** A public URL that spends your Anthropic credits is an open
> relay. Same reason you don't leave SMTP open on the internet.

> **Why `ANTHROPIC_MAX_RETRIES=0`?** So an upstream 429 shows up honestly in the load test instead of
> being silently retried. In production you'd leave retries on.

## 3 · First call

```bash
URL=$(gcloud run services describe plumbing-agent --region $REGION --format='value(status.url)')
TOKEN=$(gcloud auth print-identity-token)

curl -s $URL/ -H "Authorization: Bearer $TOKEN"

curl -s -X POST $URL/quote \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"message":"Need 40 of the 3/4 PEX elbows. When can I get them?"}' | python3 -m json.tool
```

Point out `latency_ms`, `input_tokens`/`output_tokens`, and `revision` in the response.

## 4 · The deep freeze — load test, round 1 (one lane)

```bash
python3 loadtest.py $URL -n 20 -c 10 --token "$TOKEN"
```

Expect most requests to come back **429 platform**: one instance, one request at a time, nowhere to put the rest.

| Knob | Networking analogy |
|---|---|
| `--concurrency` | Interface queue depth — how many flows one box handles at once |
| `--max-instances` | How many ECMP paths you're allowed to light up |
| `--min-instances` | Keepalive — an established BGP neighbor vs. one starting from Idle (cold start) |
| Provider rate limit | Upstream ISP policing you at your CIR, no matter how many paths you add |

## 5 · Round 2 — open it up

```bash
gcloud run services update plumbing-agent --region $REGION \
  --concurrency 10 --max-instances 3

python3 loadtest.py $URL -n 40 -c 20 --token "$TOKEN"
```

Platform 429s disappear; throughput rises. Note the **new revision name** in the output — every config change is a new immutable revision (rollback = shift traffic back).

If you see **429 upstream**, that's the provider's ceiling — scaling Cloud Run further won't help.
If you don't, that's the discussion: *"What happens at 400 concurrent contractors? Which wall do we hit first, and who owns raising it?"*
Fixes live outside the container: higher quota tier, retries with backoff, a queue, an AI gateway (APIM / Apigee) with token limits and caching.

## 6 · (Block 2 prep) Turn on LangSmith tracing — no code change

> **Tip:** Do this step *before* Round 2 of the load test. Then Block 2 opens with real traces from the surge instead of an empty project.

```bash
read -s -p "LangSmith API key: " KEY && printf '%s' "$KEY" | \
  gcloud secrets create langsmith-api-key --data-file=- && unset KEY
gcloud secrets add-iam-policy-binding langsmith-api-key \
  --member="serviceAccount:${SA}" --role=roles/secretmanager.secretAccessor

gcloud run services update plumbing-agent --region $REGION \
  --update-secrets LANGSMITH_API_KEY=langsmith-api-key:latest \
  --update-env-vars LANGSMITH_TRACING=true,LANGSMITH_PROJECT=plumbing-agent-cloudrun
```

Re-run the load test; every request now appears as a trace (extract → lookup → check_stock / quote_price / delivery_estimate → respond).

## 7 · Cleanup (after class)

```bash
gcloud run services delete plumbing-agent --region $REGION --quiet
gcloud secrets delete anthropic-api-key --quiet
gcloud secrets delete langsmith-api-key --quiet
# Optional: delete the cloud-run-source-deploy repo in Artifact Registry to drop stored images
```

---

### Fallbacks if a live step stalls
- **Build slow/failing:** deploy before class; in class, run `gcloud run services describe` and walk the revision history in the console instead.
- **Token expired** (`401`): `TOKEN=$(gcloud auth print-identity-token)` — they last about an hour.
- **`403` on invoke:** your account needs `roles/run.invoker` (project Owners have it).
- **Secret access error at startup:** re-run the `secretAccessor` binding for the compute service account.
