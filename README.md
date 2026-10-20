# Planetary Plume AI

Uncertainty-aware deep learning for planetary plume candidate detection under
imaging variations.

> **Research status: foundation only.**
>
> - The dataset is **UNVERIFIED**. No candidate dataset, including any
>   previously suggested Zenodo dataset, has been inspected or accepted.
> - The model architecture is **UNDECIDED**.
> - No model has been trained, no experiment has been run, and no results exist.
> - No data, checkpoints, or credentials are bundled with this repository.

This repository currently contains the project foundation: environment
diagnostics, configuration loading, a format-agnostic dataset audit, and tests.
It deliberately stops before model selection or training. The dataset audit must
establish what task the data can legitimately support first.

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
| Dataset provenance, labels, and license verification | **Not started** |
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
├── pytest.ini
├── .gitignore
├── .env.example
├── config/
│   └── default.yaml
├── src/
│   └── planetary_plume/
│       ├── __init__.py
│       ├── config.py
│       ├── dataset_audit.py
│       └── environment.py
├── scripts/
│   ├── check_environment.py
│   └── audit_dataset.py
├── notebooks/
├── data/
│   └── .gitkeep
├── outputs/
│   └── .gitkeep
├── tests/
│   ├── __init__.py
│   ├── test_dataset_audit.py
│   └── test_environment.py
└── docs/
    ├── research_plan.md
    └── experiment_log.md
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

FITS files are counted as files but are not opened, because the project has not
verified that a FITS reader is needed. Add one only after the dataset format is
confirmed.

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

No citations or research results are asserted in this initial scaffold; the
literature review is pending.
