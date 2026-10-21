# Experiment Log

> **No model experiments have been recorded.** Two dataset audits are recorded
> below. Do not add invented results, backfilled metrics, or entries for runs
> that did not happen.

## Rules

- Record every actual run, including failed and inconclusive runs.
- Use one ID per run: `EXP-YYYYMMDD-NN` (for example, `EXP-20261020-01`).
- Use `AUD-YYYYMMDD-NN` for dataset audits.
- Link the exact configuration, Git commit, dataset version, and random seed(s).
- Never paste credentials, access tokens, or private data paths into this file.
- Keep large artifacts (checkpoints, audit JSON) outside Git and reference their
  location instead.
- Update an entry only with a dated note; do not silently rewrite history.

## Summary table

| ID | Date | Type | Question | Data version | Primary metric | Status |
| --- | --- | --- | --- | --- | --- | --- |
| AUD-20261020-01 | 2026-10-20 | Dataset audit | Is Zenodo 2556063 usable for a scoped Io plume pilot? | 1.0.0 (DOI 10.5281/zenodo.2556063) | Mapping/validation counts; manual overlay review | pass-with-conditions (narrow Io pilot) |
| AUD-20261020-02 | 2026-10-20 | Convention audit | What is the exact plume-angle convention, and does it explain the labels? | 1.0.0 (DOI 10.5281/zenodo.2556063) | Documented convention; cardinal/orientation tests; published-figure comparison | pass-with-conditions (conversion GO; publication claims NO-GO) |

## Dataset audit records

### AUD-20261020-01

- **Date:** 2026-10-20
- **Base Git commit:** `f630ab2` (initial commit); the audit pipeline and docs are working-tree changes for this milestone.
- **Dataset name (as published):** Planetary body limb and plume labels for NASA images
- **Proposed source / DOI / URL:** https://zenodo.org/records/2556063; DOI 10.5281/zenodo.2556063; concept DOI 10.5281/zenodo.2556062
- **Retrieval date:** 2026-10-20
- **Local or cloud path (do not commit data):** `data/raw/zenodo_2556063/` (ignored by Git)
- **License and terms:** Annotation bundle is CC BY-SA 4.0. Source images are separate NASA/PDS products; NASA content is generally not subject to U.S. copyright, with attribution and no-endorsement conditions. See `docs/dataset_verification.md`.
- **Citation requirement:** Cite DOI 10.5281/zenodo.2556063; CC BY attribution also applies.
- **Provenance (producer, mission/instrument, processing level):** JPL authors; real Cassini ISS, Galileo SSI, MESSENGER MDIS, and New Horizons LORRI products. Sample formats: PDS3 EDR/REDR and FITS RDR. Annotation bundle contains labels only, no image pixels.
- **File count / total size:** Annotation ZIP 151,704 bytes; 308 YAML annotations plus `README.txt` and `galileo_image_ids.txt`. Acquired Io sample: 12 images, 68,165,192 bytes (6 Galileo, 6 LORRI).
- **Audit command:**
  - `python scripts/acquire_annotations.py --delay 0`
  - `python scripts/build_manifest.py`
  - `python scripts/acquire_images.py --per-stratum 3 --delay 0.5`
  - `python scripts/validate_dataset.py --overlay-review outputs/validation/io_sample/overlay_review.json --overlay-status "UNVERIFIED - angle convention not established"`
  - `python scripts/diagnose_angle_convention.py`
  - `python -m pytest`
- **Test result at AUD-01:** 72 passed, 0 failed; 85% statement coverage. After the convention work (AUD-02), 81 passed.
- **Audit JSON location (outside Git):** `outputs/acquisition/annotation_acquisition.json`; `outputs/manifests/zenodo_2556063_manifest.json`; `outputs/acquisition/io_sample/acquisition_log.json`; `outputs/acquisition/io_sample/mapping_report.json`; `outputs/validation/io_sample/validation_report.json`; `outputs/validation/io_sample/overlay_review.json`; `outputs/validation/io_sample/angle_convention_diagnostic.json`.
- **Observed / synthetic / negative / confounder composition:** 112 plume-positive annotations and 196 annotation negatives. No synthetic data indicated. Negatives are absence of a `plumes` key, not verified physical absences; confounders are not labelled.
- **Label description and granularity:** Limb points (3–18; circle fit intended) and zero or more plume angular intervals in radians; 287 intervals total. No masks, boxes, confidence, plume type, height, or extent.
- **Known duplicates or sequence relationships:** No exact duplicate label files or filenames found. Near-duplicate frames and shared observation sequences are likely, especially within Enceladus and Io; sequence groups were not reconstructed. The 12 acquired products are unique.
- **Known limitations and missing metadata:** Only 112 positives; only Io has both classes; no image pixels in the deposit; annotation negatives are not physical negatives; instrument/target/annotator are confounded (mcameron = all Cassini Enceladus + all Galileo SSI, gdoran = all Mercury, wkiri = all LORRI Io); no acquisition metadata or splits; mixed processing levels/formats; one Galileo label (`4852r_label.yml`) lacks a sidecar image-ID entry; plume-angle reference convention remains unresolved.
- **Acquisition note:** the first LORRI attempt failed with HTTP 403 because the PDS Small Bodies host rejected the initial custom User-Agent. A descriptive project User-Agent with a URL was accepted; the retry succeeded. Galileo files were skipped rather than overwritten.
- **Gate decision:** pass-with-conditions
- **Decision rationale:** The annotation bundle identity, license, counts, and 12/12 Io sample mappings were verified. All 12 sample images loaded and validated, and limb circles aligned with the visible limb (RMS 0.07-1.07 px). The pilot is therefore technically feasible, but the plume-angle convention could not be established confidently on the six positive overlays, so the dataset is not yet usable for training/evaluation of plume sectors. It is not suitable as the sole dataset for the full objective.
- **Dated update (2026-10-20, AUD-02):** the documented 0-up clockwise conversion is now implemented and tested; see `docs/angle_convention_investigation.md`. The LPSC Figure 1 inconsistency remains the publication-grade blocker.
- **Follow-up actions:** (1) Resolve the angular reference/orientation convention on additional positive images or with an independent plume catalog; (2) if resolved, freeze an Io-only task and group split; (3) join PDS acquisition metadata for all sampled products; (4) seek complementary data for Europa positives, same-target Enceladus negatives, and pixel-level masks; (5) do not train a model until the angle-convention blocker is closed.

### AUD-20261020-02

- **Date:** 2026-10-20
- **Base Git commit:** `f630ab2`; convention utility, tests, and docs are working-tree changes for this milestone.
- **Question:** What is the exact mathematical definition, origin, and direction of the plume angles, and does the documented convention explain the released labels?
- **Sources examined:** Zenodo `README.txt`; KDD 2019 paper DOI 10.1145/3292500.3330656 (Figure 6 and Section 3.3.1); LPSC 2019 abstract 7026 (Figures 1–2); PDS labels for Galileo SSI and New Horizons LORRI; GitHub, Zenodo, grep.app, ACM, NTRS, and NASA software catalog searches for original code.
- **Documented facts:** The dataset uses `(x,y)=(col,row)` and plume intervals in radians, with 0 up and increasing clockwise. The KDD paper describes a 101%–120% annulus, 1024 annular sectors, and a Figure 6 axis labelled “Direction (degrees clockwise from up)” with the annulus unwrapped so center = straight up.
- **Coordinate finding:** The raw LORRI PDS/FITS label declares a lower-left origin (`LINE_DISPLAY_DIRECTION=UP`, `SAMPLE_DISPLAY_DIRECTION=RIGHT`), but the annotation points use stored row order as top-down display coordinates. Galileo `SUB_SPACECRAFT_LINE=214.13` / `SUB_SPACECRAFT_SAMPLE=287.37` match the fitted annotation limb center `(284.8, 213.7)` directly. The conversion therefore uses `x=column` right and `y=row` down without a PDS/FITS vertical flip.
- **Implemented definition:** `theta = atan2(x - cx, -(y - cy)) mod 2*pi`, with `(cx,cy)` the fitted limb-circle center; inverse `x = cx + r*sin(theta)`, `y = cy - r*cos(theta)`.
- **Implementation:** `src/planetary_plume/angle_convention.py`; `validation.render_overlay` now uses it. New overlays are under `outputs/angle_investigation/convention_v1/`; the prior overlays/reports under `outputs/validation/io_sample/` were not overwritten.
- **Residual inconsistency:** LPSC 2019 Figure 1 shows the same LORRI observation `LOR_0035092817_0X630` with light-blue regions that appear at upper-left and lower-left; the released intervals under 0-up map to right/lower-right and lower-left. One sector is consistent, one is not. Without code or author confirmation, this cannot be attributed to a convention error, an earlier labeling version, or an extra detection.
- **Tests:** `python -m pytest` — 81 passed, 0 failed; 85% statement coverage. New tests cover cardinal directions, inverse conversion, interval polygons, PDS3/FITS row order, and overlay rendering.
- **Gate decision:** pass-with-conditions. **GO** for the documented conversion in exploratory Io pipeline work. **NO-GO** for model training or publication-grade sector claims until the LPSC Figure 1 inconsistency is resolved or independent human annotation confirms the sector labels.
- **Follow-up actions:** (1) request the original annotation-tool/figure script or author confirmation; (2) if unavailable, obtain independent human annotation for 3–5 images with an explicit 0-up clockwise protocol; (3) do not train or make sector-level scientific claims before that check.

## Dataset audit record template

Copy this block for each candidate dataset. An audit is descriptive and does not
by itself establish scientific suitability.

```markdown
### AUD-YYYYMMDD-01

- **Date:**
- **Dataset name (as published):**
- **Proposed source / DOI / URL:**
- **Retrieval date:**
- **Local or cloud path (do not commit data):**
- **License and terms:**
- **Citation requirement:**
- **Provenance (producer, mission/instrument, processing level):**
- **File count / total size:**
- **Audit command:**
- **Audit JSON location (outside Git):**
- **Observed / synthetic / negative / confounder composition:**
- **Label description and granularity:**
- **Known duplicates or sequence relationships:**
- **Known limitations and missing metadata:**
- **Gate decision:** pending | pass | pass-with-conditions | fail
- **Decision rationale:**
- **Follow-up actions:**
```

## Experiment entry template

```markdown
### EXP-YYYYMMDD-01

- **Date:**
- **Status:** planned | running | completed | failed | inconclusive
- **Question / hypothesis:**
- **Dataset audit ID:**
- **Dataset version / checksum:**
- **Configuration file:**
- **Git commit:**
- **Random seed(s):**
- **Environment:** Python version, key package versions, CPU/GPU model
- **Split protocol:** (train / validation / test, grouping method)
- **Command:**

```bash
# Exact command used
```

#### Metrics

| Metric | Validation | Test | 95% CI | Notes |
| --- | --- | --- | --- | --- |
| | | | | |

#### Uncertainty and robustness results

- Calibration:
- Risk–coverage / selective prediction:
- Per-stratum or corruption results:

#### Observations

- What happened, including unexpected behavior and failure cases.
- What does **not** follow from these results.

#### Decision and next step

- Decision:
- Reason:
- Next experiment:
- Artifacts (checkpoints, logs, figures) and locations:
```

## Change history

| Date | Change | Author |
| --- | --- | --- |
| 2026-10-20 | Created the experiment log template. No experiments run. | Project initialization |
