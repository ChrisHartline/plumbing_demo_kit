# Cloud Run commands (PowerShell)

Run these from the `deploy/` folder after `gcloud auth login`. Paste **one numbered block at a time**, then wait until it finishes.

```powershell
cd v:\ProjectsGit\scaling\plumbing-demo-kit\deploy

$project = "ai-infra-lab-508921"
$region = "us-central1"
gcloud config set project $project
```

## 1. One-time project setup

```powershell
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com --project=$project

$number = gcloud projects describe $project --format="value(projectNumber)"
$sa = "$number-compute@developer.gserviceaccount.com"

gcloud projects add-iam-policy-binding $project `
  --member="serviceAccount:$sa" `
  --role="roles/run.builder"
```

## 2. API key

Run this block alone. When the terminal prints `Anthropic API key:`, paste the key at that cursor and press Enter. The words inside the quotes are only the label on screen. The saved value is whatever you type after the colon.

```powershell
$key = Read-Host "Anthropic API key"
$path = Join-Path $env:TEMP "anthropic-api-key.txt"
[System.IO.File]::WriteAllText($path, $key.Trim())
gcloud secrets create anthropic-api-key --data-file=$path --project=$project
Remove-Item $path -Force
Remove-Variable key
```

**Gotcha.** Do not put the key inside the quotes. `Read-Host "sk-ant-..."` prints the key as the label and stores the next keystroke instead (a stray `\` became secret version 1). The version number in the console (`1`, `2`) is not the key. Open the version and choose **View secret value** to see what was stored.

If the secret already exists, replace `gcloud secrets create` with `gcloud secrets versions add`. Cloud Run uses `:latest`.

Then let the runtime service account read it:

```powershell
gcloud secrets add-iam-policy-binding anthropic-api-key `
  --member="serviceAccount:$sa" `
  --role="roles/secretmanager.secretAccessor" `
  --project=$project
```

## 3. Deploy

Run this only after section 2 has finished. `--source .` uploads the current folder, so the shell must still be in `deploy/`.

```powershell
gcloud run deploy plumbing-agent `
  --source . `
  --region $region `
  --project $project `
  --no-allow-unauthenticated `
  --set-secrets "ANTHROPIC_API_KEY=anthropic-api-key:latest" `
  --set-env-vars "ANTHROPIC_MODEL=claude-haiku-4-5-20251001,ANTHROPIC_MAX_RETRIES=0" `
  --concurrency 1 `
  --max-instances 1
```

**Gotcha.** PowerShell treats a comma as an array split. Without the quotes, `gcloud` sees `ANTHROPIC_MAX_RETRIES=0` as a separate argument and fails with `unrecognized arguments`. Keep the double quotes around both `--set-secrets` and `--set-env-vars`.

The first build takes a few minutes. It creates the Artifact Registry repo `cloud-run-source-deploy`, builds the Dockerfile, and serves revision traffic on the printed URL.
