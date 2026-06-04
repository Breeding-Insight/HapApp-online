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

- Python/PyPI: `dash`, `dash-bootstrap-components`, `dash-uploader`, `pandas`, `biopython`, `cutadapt`
- Conda/Bioconda: `blast`

## Docker

Build the image from the repository root:

```bash
docker build --platform linux/amd64 -t hapapp-online .
```

Run the app on <http://localhost:8050>:

```bash
docker run --rm --platform linux/amd64 -p 8050:8050 hapapp-online
```

The image uses the checked-in `pixi.lock` file and serves Dash on `0.0.0.0:8050`. Workflow uploads and run outputs are stored under `/tmp/hapapp_online_runs` inside the container. To keep those files after the container exits, mount a volume:

```bash
docker run --rm --platform linux/amd64 -p 8050:8050 -v hapapp-runs:/tmp/hapapp_online_runs hapapp-online
```

## Workflow

`MADC Hap Assignment` accepts an uploaded raw DArT/MADC report and a species panel selection. The selected panel supplies the SNP ID LUT, allele DB FASTA, match-count LUT, optional indel/duplicate-tag files, and workflow parameters from `src/hapapp_python/panels.toml`. This workflow is used to assign fixed allele IDs, pre-process the MADC file for quality, and update the microhaplotype fasta db as needed with novel unique microhaplotypes.

The bundled `Demo panel (bundled example)` points at small example files in `vendor/HapApp_utils/data/demo_panel` and can be paired with `vendor/HapApp_utils/data/demo_panel/demo_raw_MADC.csv` for UI testing and Docker demonstrations. The demo panel is not a production allele database.

Species panels can also point at private GitHub `blob` or `tree` URLs. Set `HAPAPP_GITHUB_TOKEN` in the server environment before using those panels. GitHub-backed panel files are downloaded fresh into that run's temp work directory under `panel_files/`, so one run cannot reuse or contaminate the next run's panel inputs.

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
