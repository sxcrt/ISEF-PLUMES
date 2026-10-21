# Independent plume-candidate annotation

**Date:** 2026-10-20  
**Status:** local PySide6 annotation application implemented; no human review has
been performed and no independent annotations have been fabricated.  
**Protocol version:** `independent-annotation-v1`  
**Data format version:** `1`

This document describes a human annotation tool, not a plume detector. The tool
lets a reviewer inspect the 12-image Io pilot and record candidate directions or
angular intervals **before** seeing the released plume-sector labels.

## 1. What the tool does

- Loads the same PDS3 Galileo SSI and FITS New Horizons LORRI products used by
  the existing validation pipeline through
  `planetary_plume.image_readers.load_image`.
- Displays image identity, target, instrument, dimensions, format, and product
  path.
- Provides zoom, pan, brightness, and contrast controls. Display changes never
  modify source files.
- Draws the fitted limb circle as an optional reference.
- Lets the reviewer click an approximate direction or drag a clockwise angular
  interval around the fitted limb.
- Converts every screen position to native image coordinates and then to the
  project's established angle convention: **0° up, increasing clockwise, origin
  at the fitted limb-circle center**.
- Stores the reviewer's own candidates, classifications, confidence, notes,
  image-level flags, timestamps, protocol version, and completion state.
- Supports multiple candidates per image, editing, and deletion.

The tool does **not**:

- detect plumes automatically;
- display released plume sectors;
- display released positive/negative labels;
- prepopulate candidate locations;
- compare against released labels;
- claim that a candidate is a confirmed physical plume.

## 2. Independence design

The application is isolated from the released labels in four ways.

### 2.1 Sanitized review manifest

`annotations/independent/review_manifest.json` is the only image metadata file the
GUI reads. It contains:

- verified `image_id` (for example `galileo_ssi:11I0012` or
  `new_horizons_lorri:LOR_0034769759_0X630_SCI`);
- display name, target, instrument, dimensions, format, product ID;
- source image path, detached PDS label path when applicable, image SHA256;
- fitted limb-circle center, radius, and RMS residual.

It contains **no** released plume intervals and **no** positive/negative status.
`load_review_manifest` recursively rejects files containing keys such as
`plume_status`, `plume_intervals`, `plumes`, `positive`, `negative`, or
`ground_truth`.

The manifest is sorted by neutral identifiers (`product_family`, `image_id`),
not by released class. This prevents the image order from leaking labels.

### 2.2 One-time builder

`python scripts/build_review_manifest.py` joins the existing released annotation
manifest to the existing PDS acquisition log by exact annotation path and SHA256.
It uses the existing `annotation_record_from_dict`, `fit_circle`, and
`load_image` code.

The builder reads limb points because the fitted limb circle is a required
reference. It deliberately discards the released plume intervals and class
status. It writes:

- `annotations/independent/review_manifest.json` — GUI-safe;
- `annotations/independent/release_label_map.json` — comparison-only mapping of
  verified `image_id` values to released YAML paths. **Do not open this file
  during independent review.** The GUI does not read it.

Existing files are not overwritten. Pass `--force` only when you intentionally
want the old manifest and label map moved to timestamped `.bak` files.

### 2.3 Separate annotation storage

Independent annotations live in `annotations/independent/`, not in
`data/raw/zenodo_2556063/annotations/`, not in `outputs/`, and not next to the
released YAML files. Generated JSON files in this directory are ignored by Git by
default. The directory README and `.gitkeep` remain tracked.

### 2.4 No comparison in the GUI

The GUI does not import the released-label parser or the comparison module. A
static test enforces this, and a headless runtime test checks that no displayed
widget text contains released-label field names. Comparison is a separate
command-line stage that requires a saved annotation file.

## 3. Install

The core project dependencies must already be installed. For the desktop GUI,
install PySide6:

```powershell
cd C:\Users\lite\Desktop\ISEF-PLUMES
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-gui.txt
```

If you do not want to activate the environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-gui.txt
```

PySide6 6.12.0 was installed and tested with Python 3.13.15 on Windows. The core
analysis and test suite do not require PySide6; GUI tests are skipped when it is
not installed.

## 4. Build the sanitized manifest once

The existing pilot must be acquired and validated first, so that these files
exist:

- `outputs/manifests/zenodo_2556063_manifest.json`
- `outputs/acquisition/io_sample/acquisition_log.json`

Then run:

```powershell
python scripts\build_review_manifest.py
```

Expected result: 12 images, one sanitized review manifest, and one comparison-only
label map. The script does not write to `outputs/`, does not modify source images,
and does not modify any released YAML file.

If the manifest or label map already exists, the builder refuses to overwrite it.
Use `--force` only after deciding that the old files should be preserved as
timestamped backups.

## 5. Launch the application

The small launch command is:

```powershell
python scripts\annotate_candidates.py
```

Using the environment interpreter directly:

```powershell
.\.venv\Scripts\python.exe scripts\annotate_candidates.py
```

Optional arguments:

```powershell
python scripts\annotate_candidates.py `
  --manifest annotations\independent\review_manifest.json `
  --session annotations\independent\independent_review.json `
  --reviewer "your-name"
```

The reviewer name is stored in a new annotation file. If omitted, the OS user name
is used. Do not use another person's name.

The application opens with a banner confirming that released plume sectors and
class labels are not loaded or shown.

## 6. Conduct an independent review

### 6.1 Before you start

- Do not open `data/raw/zenodo_2556063/annotations/**/*_label.yml`.
- Do not open `outputs/validation/`, `outputs/angle_investigation/`, or
  `outputs/manifests/zenodo_2556063_manifest.json` during the review.
- Do not open `annotations/independent/release_label_map.json`.
- Do not run `scripts/compare_annotations.py` until all reviews you intend to
  compare are saved and complete.
- If you accidentally see released labels, record that in the image notes and
  mark the image `NEEDS_REVIEW`; treat the review as compromised.

### 6.2 Inspect an image

1. Select an image from the left list. The list shows only your own review state,
   never released class.
2. Check the image identity, target, instrument, dimensions, format, and product
   path in the right panel.
3. Use the mouse wheel to zoom and the **Navigate / pan** mode to drag the image.
   **Fit** returns to the whole image; **1:1** shows native pixels.
4. Adjust **Brightness** and **Contrast** if faint structure is hard to see. These
   are display-only changes; the source product and its SHA256 are untouched.
5. Toggle **Limb circle** to show or hide the fitted circle. The circle is drawn
   from the released limb points; only the limb geometry is used, never the plume
   sectors.

### 6.3 Mark a candidate direction

1. Choose **Mark direction (click)**.
2. Click the image at the approximate direction of the candidate.
3. The status bar shows the resulting angle in degrees clockwise from up.
4. Choose `PLAUSIBLE` or `UNCERTAIN` and `LOW`, `MEDIUM`, or `HIGH`.
5. Optionally add candidate notes.
6. Click **Add candidate**.

A direction is stored as a zero-width interval. It is an approximate bearing, not
a measured feature width.

### 6.4 Mark an angular interval

1. Choose **Mark interval (drag clockwise)**.
2. Press at the interval start and drag clockwise to the end, then release.
3. The preview and the pending-geometry label show start, end, width, and whether
   the interval crosses 0°/360°.
4. Classify the candidate and click **Add candidate**.

The interval is always the clockwise sweep from press to release. A drag that is
shorter than 0.5° becomes a direction. If you drag counterclockwise, the clockwise
sweep may be larger than 180°; check the displayed width before adding.

Intervals such as 350°→10° are valid and are stored as crossing 0°. They are not
silently split or reordered.

### 6.5 Multiple candidates, editing, and deleting

- Add as many candidates as needed for an image.
- Select a candidate in the list to load its classification, confidence, and
  notes.
- To change its geometry, select it, draw a new direction or interval, then click
  **Update selected**.
- **Delete selected** removes the candidate after confirmation.
- Editing an existing candidate preserves its creation timestamp and updates its
  update timestamp.
- Any candidate change or change to the negative assessment reopens a completed
  review. Re-complete it before the default complete-only comparison.

### 6.6 Negative assessment and image flags

- Check **No candidate identified in this image** to record an explicit negative
  assessment. This clears any candidate annotations for that image and cannot
  coexist with them.
- Check **AMBIGUOUS** if the image itself is ambiguous.
- Check **NEEDS_REVIEW** if the image needs a second look or if the review was
  compromised.
- Use **Image notes** for observing conditions, display stretch, feature
  description, or reasons for ambiguity.

### 6.7 Complete and save

1. Ensure the image has either at least one candidate or the
   **No candidate identified** checkbox.
2. Click **Mark review complete and save**, or press `Ctrl+S` to save without
   completing.
3. The review state changes to `COMPLETE` and the list item turns green.
4. Use **Reopen review and save** if you need to change a completed review.

The application does not auto-save. It prompts before switching images or closing
if there are unsaved changes. A one-generation `.bak` copy of the previous saved
file is created on each save.

## 7. Where annotations are stored

Default path:

```text
annotations/independent/independent_review.json
```

The file is versioned JSON with these top-level fields:

```json
{
  "format": "planetary-plume-independent-annotations",
  "format_version": 1,
  "protocol_version": "independent-annotation-v1",
  "convention": {
    "zero": "up",
    "direction": "clockwise",
    "origin": "fitted_limb_center",
    "canonical_units": "radians",
    "display_units": "degrees"
  },
  "reviewer": "your-name",
  "created_at_utc": "...",
  "updated_at_utc": "...",
  "images": []
}
```

Each image review records:

- `image_id`, display name, product family, source product path, product SHA256;
- target, instrument, width, height, fitted limb circle;
- `candidates`: candidate ID, classification, confidence, geometry, notes,
  creation/update timestamps;
- `no_candidate_identified`, `image_flags`, image notes;
- `is_complete`, `completed_at_utc`, creation/update timestamps.

Each candidate geometry records both radians (canonical, matching the project
convention) and degrees (display), plus `width` and `crosses_zero`. The loader
verifies that the stored degree/width values are consistent with the canonical
radians; it rejects inconsistent records rather than guessing.

`NO_CANDIDATE_IDENTIFIED` is an image-level outcome in the GUI. The JSON model
also accepts a single `NO_CANDIDATE_IDENTIFIED` candidate record with no geometry
as an alternate representation; it cannot coexist with other candidates.

The file is written atomically. If the file changed on disk since it was loaded,
the save is refused rather than silently overwriting another process's edits. Do
not run two GUI instances against the same session file.

Generated JSON under `annotations/independent/` is ignored by Git by default.
Copy `independent_review.json` to a separate backup location if you need a
versioned research record. The `.bak` file protects only the immediately previous
save.

## 8. Run the separate comparison stage

Run this **only after** you have completed and saved the independent annotations
you intend to compare. The GUI never runs this comparison and never displays its
results.

```powershell
python scripts\compare_annotations.py
```

Useful options:

```powershell
python scripts\compare_annotations.py `
  --session annotations\independent\independent_review.json `
  --review-manifest annotations\independent\review_manifest.json `
  --label-map annotations\independent\release_label_map.json `
  --annotations-root data\raw\zenodo_2556063\annotations\plume_annotations `
  --tolerance-deg 10
```

Defaults:

- compare only reviews marked **complete**; incomplete saved reviews are excluded
  and counted in the report;
- `--include-incomplete` also compares saved incomplete reviews; they are reported
  as `INCONCLUSIVE` and should be treated as provisional;
- reporting tolerance is 10°;
- outputs are written under `outputs/comparisons/` with a UTC timestamp in the
  filename; an existing file is never overwritten.

### 8.1 Matching

Images are matched by the verified `image_id` from the acquisition pipeline, not
by filename similarity. The comparison checks the released annotation SHA256
against the label map and refuses to use stale or missing files. Duplicate
mappings are reported as `AMBIGUOUS_MAPPING`; they are never resolved by guessing.

### 8.2 Result statuses

- `AGREEMENT` — both annotations are negative, or every released interval is
  matched by at least one reviewed candidate and every reviewed candidate matches
  at least one released interval.
- `INCONCLUSIVE` — incomplete review, image flagged `AMBIGUOUS`/`NEEDS_REVIEW`,
  source image SHA mismatch, partial overlap, near miss within the reporting
  tolerance, or inconsistent released-label data.
- `DISAGREEMENT` — no reviewed candidate overlaps or lies near a released interval,
  or the review and release disagree about whether any candidate is present.
- `MISSING_MAPPING`, `AMBIGUOUS_MAPPING`, `MISSING_RELEASED_ANNOTATION`,
  `STALE_RELEASED_ANNOTATION`, `INVALID_RELEASED_ANNOTATION`,
  `MISSING_REVIEW_MANIFEST_IMAGE` — input or mapping problems, reported explicitly.

The report includes angular overlap, nearest distance, matched interval counts,
partial-coverage flags, and the reviewer's candidate details. It states clearly
that agreement is annotation similarity, not proof of a physical plume.

## 9. Limitations of manual visual annotation

- Manual annotation is subjective. Two reviewers can reasonably mark different
  candidate directions or interval boundaries.
- Brightness/contrast stretching changes what is visible. Record substantial
  display changes in the image notes. The stretch is not part of the source
  product.
- The limb circle comes from released limb points. It is a geometry reference, not
  an independent limb measurement.
- Clicking gives an approximate bearing; dragging gives an approximate angular
  extent. Neither is a calibrated measurement of plume height, width, or physical
  extent.
- The 12-image Io pilot is small and not a representative sample of all plume
  morphologies, instruments, exposure levels, or viewing geometries.
- Released labels are not validated physical truth. Agreement does not prove that
  a feature is a physical plume; disagreement does not prove that either
  annotation is wrong.
- The tool does not model detector artifacts, cosmic rays, limb haze, clouds, or
  other confounders.
- The session file is single-reviewer and single-writer. It has no merge protocol
  for concurrent reviewers.
- Timestamps use the local machine clock in UTC; clock errors are not detected.
- The application deliberately uses no ML model and no automatic candidate
  generation.

## 10. Tests and verification

Run the complete suite:

```powershell
python -m pytest
```

Coverage:

```powershell
python -m pytest --cov=planetary_plume --cov-report=term-missing
```

Observed on 2026-10-20 with Python 3.13.15:

- `python -m pytest`: **170 passed, 0 failed**.
- Coverage: **84%** of package statements.
- Headless integration smoke test: all **12/12** real pilot images loaded in the
  PySide6 application.
- The comparison CLI was smoke-tested with a temporary session; it produced JSON
  and Markdown reports and printed the non-confirmation disclaimer.
- No model was trained. No human annotations were fabricated.

The tests cover cardinal angles (up/right/down/left), screen-to-image transforms,
zero-crossing intervals, multiple candidates, save/load/edit/delete, release-label
isolation (static and headless runtime), missing images, invalid records, and
comparison agreement/disagreement/ambiguity cases.

## 11. Troubleshooting

**`ModuleNotFoundError: No module named 'PySide6'`**  
Install the GUI requirements: `python -m pip install -r requirements-gui.txt`.

**`Review manifest not found`**  
Run `python scripts\build_review_manifest.py` after the acquisition and validation
outputs exist.

**`Annotation file changed on disk`**  
Another process or editor changed the session file. Reload the application before
saving. Do not run two instances against the same file.

**`Image could not be loaded`**  
The review manifest points to a missing or unreadable product, or the image SHA256
or dimensions no longer match the manifest. The source images are not modified by
the GUI. Re-run the acquisition/validation pipeline or rebuild the review
manifest after restoring the image. The review is disabled for that image rather
than silently annotated without pixels.

**The app cannot find images after moving the repository**  
The review manifest stores absolute product paths. Move the old manifest aside and
rebuild it with `python scripts\build_review_manifest.py --force`, then reload the
application. The builder preserves old files as timestamped backups. Existing
session reviews are checked against the image SHA256 and limb geometry, so
unchanged products remain valid.

**Comparison says `MISSING_MAPPING` / `AMBIGUOUS_MAPPING`**  
The label map is incomplete or has duplicate verified IDs. Do not guess a
filename. Rebuild the sanitized manifest/label map from the validated acquisition
log.

**Comparison says `STALE_RELEASED_ANNOTATION`**  
The released YAML no longer matches its recorded SHA256. Do not compare against
the changed file without establishing provenance.
