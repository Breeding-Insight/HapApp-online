# Cloud Run deployment

This deployment uses one Cloud Run service, a Firestore Standard database, ORCID
OAuth, GitHub, Dropbox, Secret Manager, and a dedicated Cloud Run service identity.
It does not require Cloud SQL, a VPC connector, or SQL credentials.

## 1. Firestore

Create a Firestore Standard database in Native mode. The production deployment uses:

```text
database ID: hapapp-db
location: us-west1
security rules: restrictive
```

HapApp accesses Firestore only from its Python server through Google IAM. Browser and
mobile rules should deny all direct reads and writes. Seed each allowed ORCID account
as `users/{orcid_id}` with at least:

```json
{
  "orcid_id": "0000-0000-0000-0000",
  "display_name": "Example User",
  "role": "admin",
  "is_active": true
}
```

The application creates and maintains `orcid_profiles`, `madc_submissions`, and
`submission_keys`. The last collection provides a transactional uniqueness claim for
normalized MADC filename and formal project ID pairs.

## 2. Service identity

Create a user-managed service account such as `hapapp-cloud-run` and grant it:

- `roles/datastore.user` on the project
- `roles/secretmanager.secretAccessor` on each HapApp secret

Attach that account as the Cloud Run service identity. Do not create a JSON service
account key and do not set `GOOGLE_APPLICATION_CREDENTIALS` in Cloud Run; the Python
Firestore client uses Application Default Credentials from the attached identity.

## 3. ORCID

Create a separate production ORCID application for this deployment. Its redirect URI
must exactly match:

```text
https://YOUR-CLOUD-RUN-OR-CUSTOM-DOMAIN/auth/callback
```

Set the same origin as `HAPAPP_PUBLIC_URL`. Store `ORCID_CLIENT_ID` and
`ORCID_CLIENT_SECRET` in Secret Manager. Cloud Run terminates HTTPS, so keep
`TLS_ENABLED=false` inside the container.

## 4. Secrets and environment

Use `config/cloudrun.env.example` as the non-secret environment checklist. Create
Secret Manager secrets for at least:

- `SECRET_KEY` (a random value of at least 32 characters)
- `ORCID_CLIENT_ID`
- `ORCID_CLIENT_SECRET`
- `HAPAPP_GITHUB_TOKEN`
- the configured Dropbox credentials

The required Firestore variables are:

```text
HAPAPP_DATASTORE=firestore
HAPAPP_DATASTORE_PREFLIGHT=true
GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID
FIRESTORE_DATABASE=hapapp-db
```

Cloud Run injects configuration directly into the process; no mounted `.env` file is
required. Startup performs an authenticated Firestore read and fails clearly when the
database name or service-account permission is incorrect.

## 5. Service settings

For the current polling and background-processing implementation, use:

- container port: `8080`
- minimum instances: `0` (scale to zero when idle)
- maximum instances: `1`
- instance-based CPU allocation
- session affinity: enabled
- startup CPU boost: enabled
- request timeout: `3600` seconds
- concurrency: `8`
- CPU: `2`
- memory: `4 GiB`
- second-generation execution environment
- public ingress, with application access controlled by ORCID
- no Cloud SQL connection and no VPC connection solely for Firestore

Example deployment flags, after replacing uppercase values:

```bash
gcloud run deploy hapapp-online \
  --source . \
  --region=us-west1 \
  --allow-unauthenticated \
  --service-account=hapapp-cloud-run@PROJECT_ID.iam.gserviceaccount.com \
  --port=8080 \
  --min=0 \
  --max=1 \
  --concurrency=8 \
  --cpu=2 \
  --memory=4Gi \
  --timeout=3600 \
  --cpu-boost \
  --no-cpu-throttling \
  --session-affinity \
  --set-env-vars="APP_ENV=production,HAPAPP_ENV_FROM_PROCESS=1,HAPAPP_PUBLIC_URL=https://YOUR_SERVICE_URL,TLS_ENABLED=false,HAPAPP_DATASTORE=firestore,HAPAPP_DATASTORE_PREFLIGHT=true,GOOGLE_CLOUD_PROJECT=PROJECT_ID,FIRESTORE_DATABASE=hapapp-db,HAPAPP_GITHUB_PUBLISHING_RECOVERY_ENABLED=true,HAPAPP_TEST_ALFALFA_PANEL_REPO=https://github.com/ORG/SPECIES_REPOSITORY" \
  --set-secrets="SECRET_KEY=hapapp-session-secret:latest,ORCID_CLIENT_ID=hapapp-orcid-client-id:latest,ORCID_CLIENT_SECRET=hapapp-orcid-client-secret:latest,HAPAPP_GITHUB_TOKEN=hapapp-github-token:latest"
```

Apply the Dropbox variables and secrets from `config/cloudrun.env.example` when the
archive is enabled. Do not commit real credentials.

## 6. Repository deployment

The root `Dockerfile` follows the Cloud Run container contract and honors the injected
`PORT`. In Cloud Run, connect this repository and the `cloud_run` branch, and choose
the root `Dockerfile` as the build type. Alternatively, create a Cloud Build trigger
using `cloudbuild.yaml` after the service has received its one-time identity,
environment, secret, and scaling configuration.

## Current scaling boundary

Firestore makes authorization, duplicate detection, publication claims, and recovery
durable and safe across instances. The run registry and active workflow files are
still process-local, so they exist only while the single instance is running.

With minimum instances at `0`, Cloud Run scales the service to zero once no requests
arrive, keeping an idle instance for up to 15 minutes. While a run is shown, the app
page polls the server once a second, which keeps the instance alive for the run,
review, and download. After 5 minutes without user activity the page stops polling
(`assets/inactivity-pause.js`), so a forgotten tab cannot keep the service running.
Runs normally finish in well under a minute; results that are not downloaded before
the instance scales down are lost, and the file can be processed again using the
replace-run confirmation.

Do not raise maximum instances above one until run files move to Cloud Storage and
processing is dispatched to durable Cloud Run Jobs.
