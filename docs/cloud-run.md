# Cloud Run deployment

This deployment uses one Cloud Run service, a dedicated Cloud SQL for SQL Server
database, ORCID OAuth, GitHub, Dropbox, Secret Manager, and Direct VPC egress.
It does not use the existing `HaploSearch` database.

## 1. Database

Create a Cloud SQL for SQL Server instance with private IP and create a dedicated
database such as `HapApp`. Connect directly to that database as its owner and run:

1. `schema_hapapp.sql`
2. `permissions_hapapp.sql`
3. An `INSERT` into `dbo.users` for each ORCID iD allowed to sign in.

The SQL scripts deliberately operate on the currently selected application database
and refuse to run in `master`, `model`, `msdb`, or `tempdb`. Set `MSSQL_DATABASE` to
the dedicated database name. The Cloud Run service must use Direct VPC egress to the
VPC containing the Cloud SQL private IP.

## 2. ORCID

Create a separate production ORCID application for this deployment. Its redirect URI
must exactly match:

```text
https://YOUR-CLOUD-RUN-OR-CUSTOM-DOMAIN/auth/callback
```

You may set the same origin as `HAPAPP_PUBLIC_URL`. When it is omitted, HapApp uses
Cloud Run's trusted forwarded HTTPS host to construct the callback. Store
`ORCID_CLIENT_ID` and `ORCID_CLIENT_SECRET` in Secret Manager. Cloud Run terminates
HTTPS, so keep `TLS_ENABLED=false` inside the container.

## 3. Secrets and environment

Use `config/cloudrun.env.example` as the non-secret environment-variable checklist.
Create Secret Manager secrets for at least:

- `SECRET_KEY` (a random value of at least 32 characters)
- `MSSQL_PASSWORD`
- `ORCID_CLIENT_ID`
- `ORCID_CLIENT_SECRET`
- `HAPAPP_GITHUB_TOKEN`
- the configured Dropbox credentials

Cloud Run injects configuration directly into the process; no mounted `.env` file is
required. The app fails closed when its strong session secret or ORCID credentials
are missing from a Cloud Run revision, or when an explicitly configured public URL
does not use HTTPS.

## 4. Service settings

For the current polling and background-processing implementation, use these settings:

- container port: `8080` (the app honors Cloud Run's injected `PORT`)
- minimum instances: `1`
- maximum instances: `1`
- instance-based CPU allocation (no CPU throttling)
- session affinity: enabled
- startup CPU boost: enabled
- request timeout: `3600` seconds
- one application process
- public ingress, with application access controlled by ORCID
- Direct VPC egress for private Cloud SQL traffic

Example one-time deployment flags, after replacing the uppercase values:

```bash
gcloud run deploy hapapp \
  --source . \
  --region=REGION \
  --allow-unauthenticated \
  --port=8080 \
  --min=1 \
  --max=1 \
  --concurrency=8 \
  --cpu=2 \
  --memory=4Gi \
  --timeout=3600 \
  --cpu-boost \
  --no-cpu-throttling \
  --session-affinity \
  --network=VPC_NETWORK \
  --subnet=VPC_SUBNET \
  --vpc-egress=private-ranges-only \
  --set-env-vars="APP_ENV=production,HAPAPP_ENV_FROM_PROCESS=1,TLS_ENABLED=false,MSSQL_SERVER=SQL_PRIVATE_IP,MSSQL_PORT=1433,MSSQL_DATABASE=HapApp,MSSQL_USER=hapapp_runtime_user,MSSQL_DRIVER=/app/.pixi/envs/default/lib/libtdsodbc.so,HAPAPP_DATABASE_PREFLIGHT=true,HAPAPP_GITHUB_PUBLISHING_RECOVERY_ENABLED=true,HAPAPP_TEST_ALFALFA_PANEL_REPO=https://github.com/ORG/SPECIES_REPOSITORY" \
  --set-secrets="SECRET_KEY=hapapp-session-secret:latest,MSSQL_PASSWORD=hapapp-sql-password:latest,ORCID_CLIENT_ID=hapapp-orcid-client-id:latest,ORCID_CLIENT_SECRET=hapapp-orcid-client-secret:latest,HAPAPP_GITHUB_TOKEN=hapapp-github-token:latest"
```

Apply the remaining Dropbox settings from `config/cloudrun.env.example` when that
archive is enabled. After the first deployment, register the displayed HTTPS service
URL plus `/auth/callback` in the dedicated ORCID application. You may also save that
origin as `HAPAPP_PUBLIC_URL`. Do not commit real credentials.

## 5. Repository deployment

The root `Dockerfile` follows the Cloud Run container contract and the application
honors Cloud Run's injected `PORT`. In Cloud Run, choose **Connect repository**,
select this repository and branch, and choose **Dockerfile** as the build type.
Alternatively, create a Cloud Build trigger using `cloudbuild.yaml` after the service
has received its one-time networking, environment, secret, and scaling configuration.
Subsequent builds update only the deployed image.

## Current scaling boundary

The run registry and active workflow threads are still process-local. Keeping exactly
one warm instance with CPU always allocated makes the existing workflow usable on
Cloud Run, but it does not make an in-flight MADC workflow survive a platform restart.
The GitHub `publishing` claim is recoverable, but preprocessing itself is not yet a
durable Cloud Run Job. Do not raise maximum instances above one until run files and
workflow state are moved to Cloud Storage/SQL and processing is dispatched to Cloud
Run Jobs.
