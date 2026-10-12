# Deploy the API to the GCP VM

The always-on API runs as the `stocks-api` container on the Compute Engine instance `stocks-insights-api` (`e2-micro`, `us-central1-a`) in project `stock-analysis-511406`. Caddy serves HTTPS at `https://34-63-128-121.sslip.io`. Secrets stay in `/opt/stocks.env` on the VM. They are not stored in GitHub.

Pushes to `main` that change the API image run `.github/workflows/deploy-gcp-api.yml`. The scheduled sync and analysis workflows are separate and keep using the `API_BASE_URL` secret.

## GitHub Actions secrets

Add these under **Settings → Secrets and variables → Actions**. Do not create a JSON service-account key.

| Secret | Value |
| --- | --- |
| `GCP_WIF_PROVIDER` | `projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/github/providers/github` |
| `GCP_SA_EMAIL` | `github-actions-deploy@stock-analysis-511406.iam.gserviceaccount.com` |

`PROJECT_NUMBER` is printed by the setup script below. `API_BASE_URL` is already `https://34-63-128-121.sslip.io`.

## One-time Cloud Shell setup

Run this in Cloud Shell, in project `stock-analysis-511406`, before the first deploy. It creates a Workload Identity pool locked to `Kanav129/stock-analysis`, a deploy service account, IAP SSH access, and the two values to paste into GitHub.

```bash
PROJECT_ID=stock-analysis-511406
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
SA_EMAIL=github-actions-deploy@${PROJECT_ID}.iam.gserviceaccount.com
REPO=Kanav129/stock-analysis

gcloud config set project "$PROJECT_ID"
gcloud services enable \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com \
  compute.googleapis.com \
  iap.googleapis.com \
  artifactregistry.googleapis.com

gcloud iam service-accounts create github-actions-deploy \
  --display-name="GitHub Actions API deploy" || true

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/artifactregistry.writer"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/compute.osAdminLogin"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/iap.tunnelResourceAccessor"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/compute.viewer"

gcloud compute instances add-metadata stocks-insights-api \
  --zone=us-central1-a \
  --metadata=enable-oslogin=TRUE

gcloud compute firewall-rules create allow-iap-ssh \
  --direction=INGRESS \
  --action=allow \
  --rules=tcp:22 \
  --source-ranges=35.235.240.0/20 \
  --network=default || true

gcloud iam workload-identity-pools create github \
  --location=global \
  --display-name="GitHub Actions" || true

gcloud iam workload-identity-pools providers create-oidc github \
  --location=global \
  --workload-identity-pool=github \
  --display-name="GitHub" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
  --attribute-condition="assertion.repository=='${REPO}'" || true

gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/attribute.repository/${REPO}"

echo "GCP_WIF_PROVIDER=projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/providers/github"
echo "GCP_SA_EMAIL=${SA_EMAIL}"
```

The VM's own service account still needs `roles/artifactregistry.reader`. The deploy logs into Docker with that VM's metadata token, then pulls `latest`.

`roles/compute.osAdminLogin` is what lets the GitHub identity use `sudo docker` over SSH. IAP reaches the VM on port 22 from `35.235.240.0/20` only.

## What a deploy does

1. Authenticates with Workload Identity Federation (`google-github-actions/auth`).
2. Builds the root `Dockerfile` and pushes `:<git sha>` and `:latest` to `us-central1-docker.pkg.dev/stock-analysis-511406/apps/stocks-insights-api`.
3. SSHes through IAP and replaces the `stocks-api` container: `--env-file /opt/stocks.env`, `-p 127.0.0.1:8001:8001`, `--restart=unless-stopped`.
4. Polls `https://34-63-128-121.sslip.io/health` until it returns `{"status":"ok"}`.

Manual run: **Actions → Deploy API to GCP → Run workflow**.
