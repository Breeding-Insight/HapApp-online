# HapApp

Dash interface for HapApp microhaplotype workflows. The project vendors a snapshot of `HapApp_utils` in `vendor/HapApp_utils`, so the app does not depend on a sibling utility checkout at runtime.

## Prerequisites

Before installation of either the python version or use of the Docker image, you will need to install one of two software packages. For the python version, we used pixi to assist with the installation of the required dependencies. Please first install pixi to your local system by following the instructions here: https://github.com/prefix-dev/pixi

If you would prefer the Docker image (our recommendation), you do not need to worry about installing the previously mentioned pixi tool. First, you will need to have Docker or Singularity (for HPC) installed on your system. If you are using a Mac or PC, you can download the Docker Desktop program here: https://www.docker.com/products/docker-desktop/

## A User-Friendly Interface for `HapApp_utils`

HapApp provides a point-and-click interface for the available `HapApp_utils` scripts. These existing workflows can be run from the command-line, but may be difficult for environment troubleshooting. This interface uses the same workflows, but allows for a more approachable input.

<img width="1256" height="939" alt="Screenshot 2026-05-06 at 11 45 26 AM" src="https://github.com/user-attachments/assets/65c1e12a-8685-405e-92dd-1b2a995cb862" />


## Start

Install and run with Pixi:

```bash
pixi install
pixi run hapapp-online
```

The app opens automatically in your default browser. To start the server without opening a browser, run `pixi run hapapp-online --no-open`.

Pixi installs the Python app dependencies plus the command-line bioinformatics tools used by the workflows:

- Python/PyPI: `dash`, `dash-bootstrap-components`, `dash-uploader`, `pandas`, `biopython`, `cutadapt`, `python-dotenv`
- Conda/Bioconda: `blast`

## Configuration

For local development, copy the example environment file:

```bash
cp config/local.env.example config/local.env
```

Both Pixi and local Docker Compose read `config/local.env`. Deployed VM environments use `config/development.env` and `config/production.env` (copy from the corresponding `.example` files).

## Docker Compose

Compose builds the docker image and mounts the selected environment-specific file under `/app/config/`. The app keeps Dash's internal `HAPAPP_PORT=8050` inside each mounted env file. The Compose overlays publish different VM host ports: local `8050`, development `5050`, and production `5081`.

Development and production Compose overlays also mount the VM TLS certificate and key at `/cert.pem` and `/key.pem`. Keep `TLS_ENABLED=true`, `TLS_CERT_PATH=/cert.pem`, and `TLS_KEY_PATH=/key.pem` in the deployed env file for end-to-end HTTPS inside the container. The container runs as UID/GID `10001`, so the mounted key must be readable by that runtime user or group.

Local Docker development, with source directories mounted into the container:

```bash
cp config/local.env.example config/local.env
docker compose -f docker-compose.yml -f docker-compose.local.yml up --build
```

Development VM:

```bash
cp config/development.env.example config/development.env
docker compose -f docker-compose.yml -f docker-compose.development.yml up --build -d
```

Production VM:

```bash
cp config/production.env.example config/production.env
docker compose -f docker-compose.yml -f docker-compose.production.yml up --build -d
```

Before starting a deployment for the first time, run `schema_hapapp.sql` and then `permissions_hapapp.sql` on the SQL Server with a database-owner account. Both scripts explicitly target `HaploSearch`; the schema script creates the authorization table and all HapApp tables with the final GitHub publication states. The permissions script uses `hapapp_runtime_user` for development and production by default and automatically recognizes local Docker's `sa`/`dbo` connection. Set its optional override only when a server's `MSSQL_USER` has a different name. Production startup verifies the live `HaploSearch` publication constraint and fails clearly if the full schema has not been installed.

## Workflow

`MADC Hap Assignment` accepts an uploaded raw DArT/MADC report and automatically identifies its species panel by matching every MADC CloneID against the configured panel SNP ID LUTs. Uploads that do not uniquely match an available panel are blocked. The identified panel supplies the SNP ID LUT, allele DB FASTA, match-count LUT, optional indel/duplicate-tag files, and workflow parameters from `src/hapapp_python/panels.toml`. This workflow is used to assign fixed allele IDs, pre-process the MADC file for quality, and update the microhaplotype fasta db as needed with novel unique microhaplotypes.

The bundled `Demo panel (bundled example)` points at small example files in `vendor/HapApp_utils/data/demo_panel` and can be paired with `vendor/HapApp_utils/data/demo_panel/demo_raw_MADC.csv` for UI testing and Docker demonstrations. The demo panel is not a production allele database.

Species panels can also point at private GitHub `blob` or `tree` URLs. Set `HAPAPP_GITHUB_TOKEN` before using those panels. GitHub-backed panel files are downloaded fresh into that run's temp work directory under `panel_files/`, so one run cannot reuse or contaminate the next run's panel inputs.

GitHub-backed production panels pin every input to the species branch's exact commit at run start. When novel alleles are found, HapApp publishes the processed fixed-allele-ID MADC, contribution metadata, and new database version files in one commit, then advances the branch with a non-forced atomic update. If no novel alleles are found, no GitHub commit or database version change is made; the finalized MADC, metadata, and workflow log are shared with Breeding Insight through the review archive. If another contribution advances that species first, the losing database-changing run is marked stale and must be reprocessed. Expired `publishing` claims are reconciled against the branch at application startup so a crash after GitHub accepts a commit cannot permanently strand the database record. Configure `github_madc_dir` and `github_metadata_dir` on each publishable panel. See [docs/github-publication.md](docs/github-publication.md) for the concurrency model, repository permissions, recovery settings, and rollout checklist.

When a completed MADC run's results modal opens, it displays the recognized-accession and new-allele summary and requires a sharing decision. Downloading means the user agrees to share the processed MADC, metadata, and workflow log with Breeding Insight for review. Runs with novel alleles publish the database-changing contribution to the configured GitHub branch before archival and download. Zero-new-allele runs show a warning, skip GitHub entirely, retain the current database version, and archive the review materials to Dropbox. Previously tracked combinations of source filename and formal project ID are rejected before processing. Set `HAPAPP_DROPBOX_ACCESS_TOKEN` to enable the archive. Optional destination folders can be customized with `HAPAPP_DROPBOX_MADC_FOLDER` and `HAPAPP_DROPBOX_LOG_FOLDER`; by default they are `/HapApp/MADC review` and `/HapApp/MADC logs`.

Each run creates a session-specific directory under the system temp directory. Result ZIP downloads are built from that run directory. The vendored `vendor/HapApp_utils/data` directory is not used for run outputs.

## Project Layout

```text
assets/                  Dash CSS assets
src/hapapp_python/       Dash app package
src/hapapp_python/panels.toml
                         Editable MADC species panel registry
vendor/HapApp_utils/     Vendored utility snapshot
workflows/               Parameterized bash workflows used by the app
pixi.toml                Reproducible Python and bioinformatics environment
pyproject.toml           Python package metadata
```

## Direct Workflow Use

The MADC workflow script in `workflows/` can also be called directly. Run it with `--help` for required arguments:

```bash
bash workflows/build02_madc_haps.sh --help
```
