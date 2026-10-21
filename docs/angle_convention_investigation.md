# Angle convention investigation

**Date:** 2026-10-20  
**Dataset:** Zenodo 2556063, *Planetary body limb and plume labels for NASA images*  
**Related audit:** `AUD-20261020-01`, `AUD-20261020-02`  
**Model work:** none

This investigation establishes the documented coordinate and angle convention,
implements it explicitly, and records a residual inconsistency in one published
figure. It does not claim that every plume annotation is visually validated.

## 1. Sources examined

| Source | What it establishes | Status |
|---|---|---|
| Zenodo record and `README.txt` | Labels are YAML; limb points are `(x,y)=(col,row)`; plume intervals are radians, “starting with 0 radians (up) and proceeding clockwise”; limb is a least-squares circle fit | Primary documentation |
| KDD 2019 paper, *Enabling Onboard Detection of Events of Scientific Interest for the Europa Clipper Spacecraft* (DOI [10.1145/3292500.3330656](https://doi.org/10.1145/3292500.3330656)) | Plume search uses an annulus from 101% to 120% of body radius, divided into 1024 annular sectors; Figure 6 axis is labelled “Direction (degrees clockwise from up)”; annulus is unwrapped with center = straight up; footnote 3 cites this dataset | Primary implementation description |
| LPSC 2019 abstract 7026, *Automatic Plume Detection for the Europa Imaging System* (bibcode `2019LPICo2151.7026D`) | Figure 1 shows labeled plumes for LORRI observation `LOR_0035092817_0X630`; Figure 2 shows algorithm detections; labels are manual ground truth | Primary figure, but low-resolution and possibly an earlier label version |
| PDS labels for Galileo SSI and New Horizons LORRI | PDS/FITS line/sample origin is lower-left for LORRI (`LINE_DISPLAY_DIRECTION=UP`, `SAMPLE_DISPLAY_DIRECTION=RIGHT`); Galileo `SUB_SPACECRAFT_LINE=214.13` and `SUB_SPACECRAFT_SAMPLE=287.37` match the annotation limb center directly | Primary image metadata |
| GitHub, Zenodo, grep.app, ACM, NASA NTRS, NASA software catalog | Searches for original annotation tool, figure script, or public implementation | **No public code found** |

Specific search evidence:

- GitHub users `wkiri` and `GDoran` have no public plume-annotation repository.
- `grep.app` searches for `plume_annotations`, `galileo_image_ids`, exact interval
  values, and the dataset title returned no public implementation.
- Zenodo/DataCite list no related software or “is supplement to” code record.
- The ACM landing page and the KDD PDF did not expose a code or supplement link
  in our inspection.
- NTRS and the NASA software catalog returned no matching implementation.

## 2. Documented conventions

### 2.1 Dataset annotation frame

- Image coordinates are `(x, y) = (col, row)`.
- The limb is a set of points; a least-squares circle fit defines the limb.
- The plume annotation is a set of angular intervals in **radians**.
- The README states: “Angles are specified starting with 0 radians (up) and
  proceeding clockwise.”
- The README does not explicitly name the angular origin.

### 2.2 Published implementation description

The KDD paper’s Figure 6 has a lower-right annulus panel with the x-axis:

> **Direction (degrees clockwise from up)**

The same figure caption says the annulus is “unwrapped so that center
corresponds to straight up.” The paper describes the annulus as “surrounding the
body” and spanning 101%–120% of the body’s estimated radius, with 1024 annular
sectors. This is consistent with the dataset README’s direction and zero, but
uses degrees rather than radians.

### 2.3 Image orientation

The raw LORRI PDS/FITS label states that `LINE_DISPLAY_DIRECTION=UP` and
`SAMPLE_DISPLAY_DIRECTION=RIGHT` imply a **lower-left** origin. The Galileo label
gives `SUB_SPACECRAFT_LINE=214.13`, `SUB_SPACECRAFT_SAMPLE=287.37`; the fitted
annotation limb center for `0085r` is approximately `(284.8, 213.7)`. The LORRI
label for `LOR_0035092817` gives `APPROX_TARGET_LINE=440`,
`APPROX_TARGET_SAMPLE=456`; the annotation fit is `(442.2, 428.3)`, consistent
with line 440 as a top-down row, not a lower-left row (which would place the
center near row 584). The annotation coordinates therefore use the **stored row
order treated as top-down** for display, not a vertically flipped lower-left
frame. This is an important distinction: the conversion utility does not apply a
PDS/FITS vertical flip.

## 3. Mathematical definition used

For a fitted limb center `(cx, cy)`, a native annotation point `(x, y)` maps to:

```text
theta = atan2(x - cx, -(y - cy)) mod 2*pi
```

with:

- `x` = column index, increasing right;
- `y` = row index, increasing down in the annotation display frame;
- `theta = 0` pointing up (negative row direction);
- `theta` increasing clockwise;
- `theta = pi/2` pointing right, `pi` down, `3*pi/2` left.

The inverse is:

```text
x = cx + r * sin(theta)
y = cy - r * cos(theta)
```

This is implemented in `src/planetary_plume/angle_convention.py` and used by
`validation.render_overlay`. The original annotations are never rewritten.

```python
from planetary_plume.angle_convention import (
    angle_to_image_point,
    image_point_to_angle,
)

theta = image_point_to_angle((x, y), (cx, cy))
point = angle_to_image_point((cx, cy), radius, theta)
```

## 4. Evidence and tests

Implemented tests in `tests/test_angle_convention.py`:

- cardinal directions: up = 0, right = pi/2, down = pi, left = 3*pi/2;
- inverse point placement and round-trip radius/angle;
- degrees/radians conversion;
- interval polygon geometry;
- invalid values and intervals.

Image orientation is tested separately in `tests/test_image_readers.py`:

- synthetic FITS row 0 is the first displayed/top row;
- synthetic PDS3 row order and line-prefix handling;
- no vertical flip is applied by the readers.

The 12-image Io sample was re-rendered with the explicit conversion utility.
New overlays are under:

```text
outputs/angle_investigation/convention_v1/overlays/
```

The earlier overlays and reports are preserved under:

```text
outputs/validation/io_sample/
```

The new overlays carry the banner:

> `CONVENTION V1 - 0 up clockwise from fitted center; LPSC Fig 1 caveat`

Limb-circle alignment remains good on all 12 sample overlays (RMS 0.07–1.07 px).
The six positive overlays remain visually ambiguous at the plume-sector level,
as recorded in the prior review. The new conversion does not make those
ambiguous features clearer, and I do not claim improved plume alignment.

## 5. Residual inconsistency: LPSC Figure 1

The LPSC abstract’s Figure 1 shows the same LORRI observation
`LOR_0035092817_0X630` that is in the annotation bundle. Its light-blue labeled
regions appear at approximately the upper-left and lower-left of the body.

The released label file contains:

```text
[1.5377, 1.9477] rad  -> about 88–112 degrees clockwise from up
[3.8264, 4.0036] rad  -> about 219–229 degrees clockwise from up
```

Under the documented convention, these are a right/down-right sector and a
lower-left sector. The lower-left sector is consistent with the published
figure; the upper-left region is not explained by the released intervals. A
simple 90-degree rotation does not reconcile both regions.

Possible explanations, in order of plausibility:

1. The figure used an earlier or different annotation version than the released
   YAML (the ZIP was created 2019-02-03; the LPSC abstract was March 2019).
2. The figure includes an additional plume/detection that is not in the released
   label file.
3. The figure’s plotting code used a different display orientation or offset.

There is no public figure-generation code to distinguish these. I therefore
record this as a **residual label-content inconsistency**, not as proof that the
0-up convention is wrong. The convention itself is supported by the README, the
KDD Figure 6 axis, and the PDS target-center check. The README’s Galileo `0085r`
example is also consistent: its intervals (`2.854–3.352` rad) place sectors at
the lower limb under 0-up, where the Galileo image shows a faint plume/extension.

## 6. Decision

**GO with conditions for the documented conversion.** The conversion is
explicit, unit-tested, and based on two independent primary descriptions
(dataset README and KDD Figure 6 axis). It may be used for the Io pilot’s
technical pipeline and exploratory analysis.

**NO-GO for publication-grade sector claims or model training yet.** The LPSC
Figure 1 inconsistency and the absence of original code mean the labels are not
fully independently validated. The six positive sample overlays also remain
visually ambiguous at the sector level.

The smallest useful independent verification experiment is:

1. Obtain the original annotation-tool or figure-generation code from the
   authors, or a written confirmation of the angular origin and the LPSC
   figure’s label version.
2. If code is unavailable, have an independent human annotate 3–5 images
   (including `lor_0035092817` and `N1635814521`) with an explicit protocol:
   mark the limb, then mark plume sectors using the documented 0-up clockwise
   convention.
3. Compare the independent annotations to the released YAML at the sector level.
   Only then should sector labels be used for training or publication claims.

## 7. Files and outputs

- `src/planetary_plume/angle_convention.py` — explicit coordinate/angle conversion.
- `tests/test_angle_convention.py` — cardinal, inverse, interval, and invalid-value tests.
- `tests/test_image_readers.py` — separate row-order/orientation tests.
- `validation.py` — overlay rendering now uses the conversion utility.
- `outputs/angle_investigation/convention_v1/` — new overlays and validation report.
- `outputs/angle_investigation/published_figure_check/` — downloaded LORRI check
  image and diagnostic overlays for the LPSC figure comparison.
- Existing `outputs/validation/io_sample/` artifacts were not overwritten.

## 8. Test result

`python -m pytest`: **81 passed, 0 failed**.  
`python -m pytest --cov=planetary_plume`: **85% statement coverage**.

No model was selected or trained.

## Sources

1. Zenodo record and annotation bundle — <https://zenodo.org/records/2556063>
2. Zenodo API metadata — <https://zenodo.org/api/records/2556063>
3. KDD 2019 paper — <https://doi.org/10.1145/3292500.3330656>
4. LPSC 2019 abstract 7026 — <https://ui.adsabs.harvard.edu/abs/2019LPICo2151.7026D/abstract>
5. LORRI PDS label for the published-figure observation — <https://pds-smallbodies.astro.umd.edu/holdings/nh-j-lorri-3-jupiter-v3.0/data/20070301_003509/lor_0035092817_0x630_sci.lbl>
6. Galileo PDS product (example `0085r`) — <https://pds-imaging.jpl.nasa.gov/pds/prod?q=OFSN+%3D+/data/galileo/galileo_orbiter//go_0020/e11/io/c042073/0085r.img+AND+RT+%3D+RAW>
7. FITS standard — <https://fits.gsfc.nasa.gov/fits_standard.html>
8. PDS — <https://pds.nasa.gov/>

