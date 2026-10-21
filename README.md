# Planetary Plume AI

Uncertainty-aware deep learning for planetary plume candidate detection under
imaging variations.

> **Research status: dataset gate passed with conditions; no model work yet.**
>
> - Zenodo 2556063 has been verified as a **label-only** dataset for 308 real
>   NASA images. It is accepted for a **narrow Io pilot**, not for the full
>   research objective. See `docs/dataset_verification.md`.
> - The documented plume-angle convention is implemented and tested, but a
>   residual LPSC Figure 1 inconsistency remains; sector labels are not yet
>   usable for publication-grade claims or training.
> - The model architecture is **UNDECIDED**.
> - No model has been trained and no results exist.
> - The independent candidate-annotation GUI is implemented, but **no human
>   annotations have been produced or compared yet**. The reviewer must perform
>   the independent review.
> - No data, checkpoints, or credentials are bundled with this repository.

This repository contains the project foundation and the independent
plume-candidate annotation workflow: environment diagnostics, configuration
loading, a format-agnostic dataset audit, validated acquisition and angle
conversion, and tests. It deliberately stops before model selection or training.
The dataset audit must establish what task the data can legitimately support
first.

## Purpose

The long-term objective is to develop and evaluate a machine-learning system that
can flag candidate plumes in spacecraft imagery and report predictive uncertainty.
A credible system must also be tested against realistic imaging variations such
as noise, compression, resolution, contrast, and viewing geometry.

The project does **not** assume:

- that a proposed dataset exists, is accessible, or is licensed for this use;
- that its files contain usable labels;
- that plumes, negatives, and confounders are already separated;
- that any particular architecture is appropriate.

## Current status

| Item | Status |
| --- | --- |
| Repository scaffold | Complete |
| Environment diagnostic | Complete |
| YAML configuration validation | Complete |
| Generic dataset inventory and dimension audit | Complete |
| Automated tests for the foundation | Complete |
| Dataset provenance, labels, and license verification | Complete with conditions (Zenodo 2556063) |
| Annotation manifest and Galileo sidecar parsing | Complete |
| Io sample acquisition and image validation | Complete (12 images) |
| Plume-angle convention validation | Documented conversion implemented; residual LPSC Figure 1 inconsistency |
| Independent candidate annotation GUI | Complete (local PySide6; released labels hidden) |
| Independent human review | **Not performed** (the reviewer must run it) |
| Task formulation (classification / detection / segmentation) | **Undecided** |
| Model architecture | **Undecided** |
| Training and evaluation | **Not started** |

## Research integrity rules

Every data source must be assigned to exactly one of these categories, and the
categories must not be pooled without a documented scientific justification:

1. **Observed planetary plume data** — real spacecraft observations, including
   raw, calibrated, or otherwise processed products. Provenance and processing
   level must be recorded.
2. **Synthetic or simulated data** — rendered, modeled, or otherwise generated
   images. Synthetic data is never presented as an observation.
3. **Negative examples and confounders** — images without plume candidates, plus
   features that can mimic plumes (for example limb haze, clouds, stars, cosmic
   rays, detector artifacts, or compression artifacts). A confounder is not
   automatically a negative label; the labeling decision must be documented.

A directory name is not evidence of a label. The audit script describes files; it
does not verify annotations, provenance, licensing, class balance, or scientific
suitability.

## Repository layout

```text
planetary-plume-ai/
├── README.md
├── requirements.txt
├── requirements-dev.txt
├── requirements-gui.txt
├── pytest.ini
├── .gitignore
├── .env.example
├── config/
│   └── default.yaml
├── src/
│   └── planetary_plume/
│       ├── __init__.py
│       ├── acquisition.py
│       ├── angle_convention.py
│       ├── angle_intervals.py
│       ├── annotation_store.py
│       ├── annotations.py
│       ├── config.py
│       ├── convention.py
│       ├── dataset_audit.py
│       ├── display.py
│       ├── environment.py
│       ├── image_readers.py
│       ├── manifest.py
│       ├── pds.py
│       ├── qt_canvas.py
│       ├── review_app.py
│       ├── review_compare.py
│       ├── review_manifest.py
│       ├── review_manifest_builder.py
│       ├── validation.py
│       └── viewport.py
├── scripts/
│   ├── acquire_annotations.py
│   ├── acquire_images.py
│   ├── annotate_candidates.py
│   ├── audit_dataset.py
│   ├── build_manifest.py
│   ├── build_review_manifest.py
│   ├── check_environment.py
│   ├── compare_annotations.py
│   ├── diagnose_angle_convention.py
│   └── validate_dataset.py
├── notebooks/
├── annotations/
│   └── independent/          # independent JSON, sanitized manifest, label map
├── data/
│   └── .gitkeep
├── outputs/
│   └── .gitkeep
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_acquisition.py
│   ├── test_angle_convention.py
│   ├── test_angle_intervals.py
│   ├── test_annotation_store.py
│   ├── test_annotations.py
│   ├── test_convention.py
│   ├── test_dataset_audit.py
│   ├── test_environment.py
│   ├── test_image_readers.py
│   ├── test_manifest.py
│   ├── test_pds_mapping.py
│   ├── test_qt_canvas.py
│   ├── test_review_app_independence.py
│   ├── test_review_compare.py
│   ├── test_review_manifest.py
│   ├── test_review_manifest_builder.py
│   ├── test_scripts_smoke.py
│   ├── test_validation.py
│   └── test_viewport_display.py
└── docs/
    ├── angle_convention_investigation.md
    ├── dataset_validation.md
    ├── dataset_verification.md
    ├── experiment_log.md
    ├── independent_annotation.md
    └── research_plan.md
```

`dataset_audit.py` and `requirements-dev.txt` are small additions to the
requested layout. The audit logic lives in the package so that it can be tested
and reused from notebooks; `scripts/audit_dataset.py` is a thin command-line
wrapper.

## Requirements

- Python 3.11 or newer. **Python 3.13 is recommended and was used for the
  verification environment** because PyTorch and other ML wheels often lag the
  newest Python release.
- Windows, macOS, or Linux. Local development here is CPU-only.
- Git for version control.

Core dependencies are intentionally minimal: PyYAML, NumPy, and Pillow. PyTorch
is **not** installed by `requirements.txt`. It is a large dependency and is not
needed for the foundation; install it when the dataset gate has passed and model
work begins. See [Optional: PyTorch](#optional-pytorch).

The desktop annotation GUI uses PySide6. It is optional for the core analysis and
test suite and is installed from a separate file:

```powershell
python -m pip install -r requirements-gui.txt
```

## Local setup on Windows

Open PowerShell in the repository folder.

```powershell
cd planetary-plume-ai
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-dev.txt
```

If Python 3.13 is not installed, replace `py -3.13` with `python` or another
supported version. If PowerShell blocks activation, either allow it for the
current shell only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

or call the environment's interpreter directly without activating:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
```

### Run the environment diagnostic

```powershell
python scripts/check_environment.py
```

The diagnostic reports the Python version and executable, operating system,
installed package versions, and whether PyTorch can see a CUDA GPU. A missing
PyTorch installation is reported as a warning during this phase, not a failure.
It exits with a non-zero status if a core dependency is missing or the
configuration is invalid.

To treat every warning as a failure:

```powershell
python scripts/check_environment.py --strict
```

### Run the tests

```powershell
python -m pytest
```

The tests create small temporary images and do not require a GPU, network access,
PyTorch, or an external dataset.

To measure coverage of the package:

```powershell
python -m pytest --cov=planetary_plume --cov-report=term-missing
```

### Optional: PyTorch

Install the CPU build only when you need it:

```powershell
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
```

Do not add GPU-specific packages on a CPU-only machine. On Kaggle or Colab, use
the preinstalled PyTorch after checking its version; do not assume a GPU is
available.

## Dataset audit

The audit accepts any directory and makes no assumptions about dataset format or
labels. It reports file counts, extensions, sizes, directory structure, and
image dimensions for formats Pillow can read.

```powershell
python scripts/audit_dataset.py "D:\path\to\dataset"
```

Write a machine-readable copy for the experiment log:

```powershell
python scripts/audit_dataset.py "D:\path\to\dataset" --json outputs\dataset_audit.json
```

By default the script uses `dataset.root` from the configuration, or
`paths.data_dir` if `root` is `null`. You can also pass a path explicitly. The
default dimension sample is 500 images; set `--max-images 0` to inspect every
matching image.

What the audit **does**:

- counts all files and directories, including files it cannot interpret;
- summarizes file extensions and total size;
- shows the top-level directory layout and maximum depth;
- samples image dimensions and color modes using Pillow;
- reports unreadable image files.

What the audit **does not** do:

- determine whether files contain plumes;
- interpret labels, masks, FITS headers, or mission metadata;
- verify provenance, licensing, annotation quality, or class balance;
- decide whether the dataset is suitable for the research question.

FITS files are counted as files but are not opened by the generic audit. The
dataset-validation pipeline has a limited FITS reader for the verified LORRI
products only.

## Zenodo 2556063 acquisition and Io validation

The dataset is a **label bundle**, not an image archive. The pipeline downloads
the 152 KB annotations, builds a manifest, resolves a small stratified Io
sample, downloads images from PDS, and renders overlays for manual inspection.
All data and generated artifacts stay in `data/` and `outputs/` (ignored by Git).

```powershell
python scripts/acquire_annotations.py --delay 0
python scripts/build_manifest.py
python scripts/acquire_images.py --per-stratum 3 --delay 0.5 --dry-run
python scripts/acquire_images.py --per-stratum 3 --delay 0.5
python scripts/validate_dataset.py --output-dir outputs\angle_investigation\convention_v1 --overlay-review outputs\validation\io_sample\overlay_review.json --overlay-status "CONVENTION V1 - 0 up clockwise from fitted center; LPSC Fig 1 caveat"
python scripts/diagnose_angle_convention.py
```

Key rules enforced by the pipeline:

- annotations are parsed read-only and hashed;
- Galileo and LORRI identifiers use separate resolvers;
- ambiguous or missing PDS mappings are reported, never silently substituted;
- downloads use `.part` files with HTTP Range resume and never overwrite a
  final file by default;
- overlays carry the documented angle convention and an explicit status banner.

**Current status:** the documented angle convention (`0 = up`, clockwise, from
the fitted limb center) is implemented and tested in
`src/planetary_plume/angle_convention.py`; see
`docs/angle_convention_investigation.md`. A residual inconsistency remains: the
LPSC 2019 Figure 1 appears to place one light-blue sector where the released
intervals do not. Limb circles align on the 12-image Io sample, but plume-sector
alignment remains visually ambiguous on the six positives. Use the conversion
for exploratory pipeline work only; do not train a model or make
publication-grade sector claims until the residual is resolved.

## Independent candidate annotation (labels hidden)

A local PySide6 application lets the reviewer inspect the 12-image Io pilot and
record candidate directions or angular intervals **before** seeing the released
plume-sector labels. It is a human annotation tool, not a detector.

```powershell
# once: build the sanitized review manifest from the validated acquisition log
python scripts\build_review_manifest.py

# launch the application
python scripts\annotate_candidates.py
```

The GUI reads only `annotations/independent/review_manifest.json`, which contains
image identity, dimensions, product paths, and fitted limb geometry. It does not
read released plume intervals or positive/negative labels, does not prepopulate
candidate locations, and has no comparison feature. Released annotations remain
untouched in `data/raw/zenodo_2556063/annotations/`.

Independent annotations are saved as versioned JSON under
`annotations/independent/`. After saving the reviews, run the separate comparison
stage explicitly:

```powershell
python scripts\compare_annotations.py
```

The comparison matches by verified `image_id` (never filename guesses), handles
intervals crossing 0°/360°, reports agreement/disagreement/inconclusive and
missing/ambiguous mappings, writes timestamped non-overwriting reports under
`outputs/comparisons/`, and states that agreement does not prove a feature is a
physical plume.

Full protocol, storage schema, comparison statuses, and limitations:
`docs/independent_annotation.md`.

## Configuration

`config/default.yaml` holds project settings. Relative paths are resolved against
the repository root, not the current working directory, so scripts behave the
same from `scripts/`, notebooks, or a cloud runtime.

Environment variables can override selected values:

| Variable | Overrides |
| --- | --- |
| `PLUME_CONFIG` | Path to the YAML configuration, when `--config` is not supplied |
| `PLUME_DATA_DIR` | `paths.data_dir` |
| `PLUME_OUTPUT_DIR` | `paths.outputs_dir` |
| `PLUME_DATASET_ROOT` | `dataset.root` |

`.env.example` documents these names, but **the project does not load `.env`
files automatically**. Set the variables in your shell, notebook, or cloud
environment. This avoids adding a dependency and prevents secrets from being
loaded implicitly.

Example for a Kaggle dataset mount:

```powershell
$env:PLUME_DATA_DIR = "/kaggle/input/my-dataset"
python scripts/audit_dataset.py
```

## Local → GitHub → cloud workflow

1. **Local (Windows, CPU):** develop and test the foundation. Run
   `python -m pytest` before every push.
2. **GitHub:** commit source, configuration, tests, and documentation. Never
   commit datasets, checkpoints, credentials, or generated outputs.
3. **Kaggle or Colab:** clone the repository, install the minimal requirements,
   point `PLUME_DATA_DIR` at the mounted data, and run the same diagnostic and
   audit scripts. Training will be added only after the dataset gate is passed.

Example for a notebook cell:

```python
!git clone https://github.com/<your-account>/planetary-plume-ai.git
%cd planetary-plume-ai
!python -m pip install -r requirements.txt -r requirements-dev.txt
!python scripts/check_environment.py
```

Kaggle may require internet access to be enabled for the clone and install.
Colab may disconnect or change GPU availability. The project does not assume a
specific GPU model or guaranteed free GPU access, and it does not implement cloud
authentication or automatic uploads.

## Data and output policy

- `data/` and `outputs/` are ignored by Git except for their `.gitkeep` files.
- Independent annotation JSON, the sanitized review manifest, and the
  comparison-only label map under `annotations/independent/` are ignored by Git
  by default; the directory README and `.gitkeep` are tracked.
- Model checkpoints and common serialized model formats are ignored.
- `.env` files are ignored; `.env.example` is tracked.
- Generated audit JSON belongs in `outputs/`, which is not committed.
- Any dataset that is legally redistributable should be documented separately;
  do not add it to this repository by default.

## Unresolved research decisions

These decisions are intentionally open:

- Which dataset, mission, instrument, and processing level will be used, and
  whether its license permits the intended use.
- Whether the available annotations support image-level classification, patch
  classification, object detection, or pixel-level segmentation.
- What counts as a positive, a negative, and a confounder.
- Whether synthetic or simulated data will be used at all, and if so, how it will
  be kept separate from observed data.
- Which architecture and input representation are appropriate.
- Which uncertainty method (for example ensembles, Monte Carlo dropout, or
  calibration post-processing) is scientifically and computationally justified.
- Which metrics and split protocol will be preregistered before test-set
  evaluation.

See `docs/research_plan.md` for the dataset-verification gate and the proposed
experimental direction.

## Documentation

- `docs/research_plan.md` — objective, data rules, verification gate, proposed
  experiments, and open questions.
- `docs/experiment_log.md` — template for experiment IDs, configurations,
  dataset versions, seeds, metrics, and observations.
- `docs/independent_annotation.md` — independent-review protocol, GUI usage,
  annotation JSON schema, comparison statuses, and manual-annotation limitations.

No citations or research results are asserted in this initial scaffold; the
literature review is pending.
