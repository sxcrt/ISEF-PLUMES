# Dataset validation — Zenodo 2556063 Io sample

**Date:** 2026-10-20  
**Scope:** annotation manifest, identifier mapping, and a 12-image Io sample.  
**Companion document:** `docs/dataset_verification.md`  
**Audit ID:** `AUD-20261020-01`  
**Model work:** none; no architecture was selected and no training was run.

This report records the actual pipeline results. It does not claim that the
dataset is fully validated.

> **Update 2026-10-20:** the angle convention was investigated separately in
> `docs/angle_convention_investigation.md`. The documented 0-up clockwise
> conversion is implemented and tested; a residual LPSC Figure 1 inconsistency
> remains. Existing overlays and reports in this directory are preserved.

## Commands

```powershell
python scripts/acquire_annotations.py --delay 0
python scripts/build_manifest.py
python scripts/acquire_images.py --per-stratum 3 --delay 0.5
python scripts/validate_dataset.py --overlay-review outputs/validation/io_sample/overlay_review.json --overlay-status "UNVERIFIED - angle convention not established"
python scripts/diagnose_angle_convention.py
python -m pytest
```

Artifacts are under `outputs/` and `data/` (both ignored by Git). Source
annotations were not modified.

**Test result after the convention work:** `python -m pytest` — 81 passed,
0 failed. Coverage: `python -m pytest --cov=planetary_plume` — 85% statement
coverage.

## Annotation manifest

| Metric | Result |
|---|---:|
| Annotations parsed | 308 |
| Plume-positive | 112 |
| Plume-negative | 196 |
| Plume angular intervals | 287 |
| Files with more than one interval | 79 |
| Limb points range | 3–18 |
| Files with only 3 limb points | 116 (38%) |
| Annotators | mcameron 101; gdoran 123; wkiri 84 |

Manifest mapping status:

| Status | Count | Meaning |
|---|---:|---|
| `sidecar_mapped` | 60 | Galileo labels with a unique `galileo_image_ids.txt` entry |
| `unresolved_sidecar` | 1 | Galileo label with no sidecar entry (`4852r_label.yml`) |
| `label_stem_candidate` | 207 | LORRI/MESSENGER filename-stem candidates; not yet PDS-resolved |
| `unresolved_adapter` | 40 | Cassini labels; no adapter in this milestone |

The manifest is at `outputs/manifests/zenodo_2556063_manifest.json` and `.csv`.

## Io sample acquisition

The deterministic sample selected 3 positive and 3 negative annotations from
each Io family:

| Family | Positive | Negative | Total |
|---|---:|---:|---:|
| Galileo SSI | 3 | 3 | 6 |
| New Horizons LORRI | 3 | 3 | 6 |
| **Total** | **6** | **6** | **12** |

Results:

| Metric | Result |
|---|---:|
| Sample annotations | 12 |
| PDS products resolved | 12 / 12 |
| Images available (downloaded + existing) | 12 |
| Images validated | 12 |
| Missing mappings in sample | 0 |
| Ambiguous mappings in sample | 0 |
| Duplicate product IDs in sample | 0 |
| Duplicate image SHA256 in sample | 0 |
| Image bytes | 68,165,192 |

The first LORRI download attempt returned HTTP 403 because the PDS Small Bodies
host rejected the initial custom User-Agent. The acquisition layer was corrected
to use a descriptive project User-Agent with a URL, and the retry succeeded.
The existing Galileo files were skipped rather than overwritten.

PDS per-product expected checksums were not available from the harvested Solr
metadata. The pipeline records each downloaded file's size and SHA256, and the
validator recomputes the SHA256 against the acquisition log. This detects
post-download corruption; it is not an independent publisher checksum.

Formats loaded:

| Family | Format | Dimensions | Data type |
|---|---|---|---|
| Galileo SSI | PDS3 with detached label | 800×800 | `uint8` |
| New Horizons LORRI | FITS primary HDU | 1024×1024 | `>f4` (32-bit float) |

## Overlay inspection

Twelve overlays were rendered at native resolution and inspected manually. A
status of `aligned` for a negative means the limb circle follows the visible
limb; no plume sector exists to assess.

| Result | Count |
|---|---:|
| Limb geometry visually aligned | 12 / 12 |
| Negative overlays (limb-only check) | 6 |
| Positive overlays with ambiguous plume-sector alignment | 6 |
| Positive overlays with confidently aligned plume sectors | 0 |

Limb-circle RMS residuals ranged from 0.07 to 1.07 px. Examples:

- Galileo `3178r`: RMS 1.07 px; lower-limb sector coincides with a faint
  extension, but a single sample is not enough to validate the sector label.
- LORRI `lor_0034769759`: RMS 0.14 px; narrow upper-left sector; plume is faint
  and not confidently separable from noise.
- LORRI `lor_0034821020` and `lor_0034829600`: disks are saturated; sectors
  cannot be confidently separated from saturation or smear.

A supplementary angular-brightness diagnostic compared the documented
convention (`0 = up, clockwise`) with five alternatives. The highest-scoring
convention varied across the six positives (`right_ccw_math`, `up_cw`,
`right_cw_screen`, and `down_cw` all appeared), so brightness alone did not
select a convention. The diagnostic JSON is
`outputs/validation/io_sample/angle_convention_diagnostic.json`. Later
primary-source work (`docs/angle_convention_investigation.md`) established the
documented conversion from the dataset README and the KDD Figure 6 axis; the
brightness diagnostic is retained as a caution, not as the deciding evidence.

**Decision:** the documented conversion is implemented in
`src/planetary_plume/angle_convention.py` and may be used for exploratory Io
pipeline work. Do not use the sector labels for model training or
publication-grade claims until the LPSC Figure 1 inconsistency is resolved. The
original overlays remain labelled `UNVERIFIED` and are preserved as historical
diagnostics; new overlays are under `outputs/angle_investigation/convention_v1/`.

## Remaining scientific uncertainties

1. **Angular reference convention.** The README states direction but not origin.
   Resolve before any sector-based task.
2. **Physical truth.** The labels are annotations of bright material, not
   confirmed plumes.
3. **Negative definition.** Annotation negatives are not verified physical
   absences.
4. **Coverage.** Only 12 of 308 source products were acquired and validated.
5. **Confounding.** Target, instrument, and annotator are confounded; the Io
   subset is the only same-target positive/negative subset.
6. **Metadata and splits.** Acquisition metadata and leakage-resistant splits
   must be constructed from PDS; none are provided.
7. **Missing sidecar entry.** One Galileo Europa label is unresolved and is not
   part of the Io sample.

## Gate decision

**PASS WITH CONDITIONS for a narrow Io pilot.** The pipeline reproduces the
manifest, resolves exact Io products, downloads safely, reads both formats, and
validates the sample. The documented angle conversion is implemented; the LPSC
Figure 1 inconsistency must be resolved before publication-grade sector claims
or training. The dataset remains unsuitable as the sole primary dataset for the
full research objective.
