# HapApp Python

Dash interface for HapApp microhaplotype workflows. The project vendors a snapshot of `HapApp_utils` in `vendor/HapApp_utils`, so the app does not depend on a sibling utility checkout at runtime.

## Start

Install and run with Pixi:

```bash
pixi install
pixi run hapapp-python
```

The app opens automatically in your default browser. To start the server without opening a browser, run `pixi run hapapp-python --no-open`.

Pixi installs the Python app dependencies plus the command-line bioinformatics tools used by the workflows:

- Python/PyPI: `dash`, `dash-bootstrap-components`, `dash-uploader`, `pandas`, `biopython`, `cutadapt`
- Conda/Bioconda: `blast`, `hmmer` (`esl-sfetch`), `seqkit`, `mmseqs2`

## Docker

Build the image from the repository root:

```bash
docker build --platform linux/amd64 -t hapapp-python .
```

Run the app on <http://localhost:8050>:

```bash
docker run --rm --platform linux/amd64 -p 8050:8050 hapapp-python
```

The image uses the checked-in `pixi.lock` file and serves Dash on `0.0.0.0:8050`. Workflow uploads and run outputs are stored under `/tmp/hapapp_python_runs` inside the container. To keep those files after the container exits, mount a volume:

```bash
docker run --rm --platform linux/amd64 -p 8050:8050 -v hapapp-runs:/tmp/hapapp_python_runs hapapp-python
```

## Workflows

The app has two tabs.

`MADC Hap Assignment` uses disk-backed browser file pickers for the MADC report, SNP ID LUT, base allele DB FASTA, base match-count LUT, optional indel-added DB/LUT files, and an optional duplicate-tags file. Defaults are first sample column `17`, design length `81`, sequence length `109`, coverage `90`, identity `85`, and code version `v1`.

`Core Ref/Alt DB` uses the same disk-backed browser file pickers for the probe design file, chromosome length file, MADC report, and reference genome FASTA. Uploaded files are staged as filesystem paths for the workflows instead of being passed through Dash callback state as base64 strings. Defaults are ref length `109` and flank length `150`.

Each run creates a session-specific directory under the system temp directory. Result ZIP downloads are built from that run directory. The vendored `vendor/HapApp_utils/data` directory is not used for run outputs.

## Project Layout

```text
assets/                  Dash CSS assets
src/hapapp_python/       Dash app package
vendor/HapApp_utils/     Vendored utility snapshot
workflows/               Parameterized bash workflows used by the app
pixi.toml                Reproducible Python and bioinformatics environment
pyproject.toml           Python package metadata
```

## Direct Workflow Use

The scripts in `workflows/` can also be called directly. Run either script with `--help` for required arguments:

```bash
bash workflows/build02_madc_haps.sh --help
bash workflows/build01_ref_alt_core_db.sh --help
```
