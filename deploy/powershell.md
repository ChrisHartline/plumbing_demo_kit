# Cloud Run from PowerShell

Run these from the `deploy` folder. Each block is its own paste. Wait until it finishes before the next one.

`>>` at the start of a line is PowerShell waiting for the rest of a command. Do not type it, and do not copy it from the terminal.

```powershell
$project = "ai-infra-lab-508921"
$region = "us-central1"
gcloud config set project $project
$number = gcloud projects describe $project --format="value(projectNumber)"
$sa = "$number-compute@developer.gserviceaccount.com"
```

```powershell
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com --project=$project

gcloud projects add-iam-policy-binding $project --member="serviceAccount:$sa" --role="roles/run.builder"
```

Enable the APIs before creating the secret. If `gcloud` stops to ask `y/N` and you paste the next command into that question, it consumes the paste.

## API key

Run this line alone. When the terminal prints `Anthropic API key:`, paste the key there and press Enter.

```powershell
$key = Read-Host "Anthropic API key"
```

The text inside the quotes is the label PowerShell prints. It is not the value that gets saved. The saved value is whatever you type after the colon. Putting the key in the quotes only displays it, and Secret Manager stores the next keystroke instead (in our case a single `\`).

After the prompt has returned, run this:

```powershell
$path = Join-Path $env:TEMP "anthropic-api-key.txt"
[System.IO.File]::WriteAllText($path, $key.Trim())
gcloud secrets create anthropic-api-key --data-file=$path --project=$project
Remove-Item $path -Force
Remove-Variable key
```

If the secret already exists, use `versions add` in place of `create`:

```powershell
gcloud secrets versions add anthropic-api-key --data-file=$path --project=$project
```

That line has to run before `Remove-Item`. Cloud Run's `:latest` uses the newest version, so a bad first version can stay.

`Read-Host` prints the key in the scrollback. Clear the terminal after this step. The temp file is deleted. Nothing in this folder should contain the key.

```powershell
gcloud secrets add-iam-policy-binding anthropic-api-key --member="serviceAccount:$sa" --role="roles/secretmanager.secretAccessor" --project=$project
```

## Deploy

Run this from `deploy`. `--source .` uploads the current directory.

PowerShell treats a comma as an array separator. Without quotes, `gcloud` sees `ANTHROPIC_MAX_RETRIES=0` as a separate argument and fails with `unrecognized arguments`.

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

The first build takes a few minutes. Confirm with:

```powershell
$url = gcloud run services describe plumbing-agent --region $region --project $project --format="value(status.url)"
$token = gcloud auth print-identity-token
curl.exe -s $url/ -H "Authorization: Bearer $token"
```
