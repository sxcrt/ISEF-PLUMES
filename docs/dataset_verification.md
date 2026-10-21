# Dataset verification — Zenodo 2556063

**Status:** verified with conditions; suitable only for a narrowly scoped Io pilot.
**Verification date:** 2026-10-20
**Dataset DOI:** [10.5281/zenodo.2556063](https://doi.org/10.5281/zenodo.2556063)  
**Concept DOI:** [10.5281/zenodo.2556062](https://doi.org/10.5281/zenodo.2556062)

This document records what was verified, what was inferred, and what remains
unresolved. It does **not** declare the dataset fully validated or suitable for
the full research objective.

## Method

- Retrieved Zenodo and DataCite metadata.
- Downloaded the 151,704-byte `plume_annotations.zip`; its MD5 matches the
  Zenodo API value (`f2c479e5f5cd10720c99ad820f14bceb`).
- Parsed all 308 YAML annotations without modifying them.
- Resolved sample source products in NASA PDS and read their native headers.
- Acquired and validated a 12-image Io sample: 6 Galileo SSI and 6 New Horizons
  LORRI, balanced 3 positive / 3 negative per family.
- Rendered overlays and inspected them manually. Details are in
  `docs/dataset_validation.md`.

## Verdict

The record is real and correctly identified, but **it is not an image dataset**.
It is a 152 KB bundle of human annotations for 308 real NASA images; the pixels
must be obtained separately from PDS. It contains **112 plume-positive** and
**196 plume-negative** annotations, with **287 angular plume intervals**.

The labels are genuine annotations of observed spacecraft data, not synthetic
and not unrelated imagery. They can support a **narrow Io pilot** on
image-level/angular plume-candidate detection after the unresolved angle
convention is addressed. They cannot support general planetary plume detection,
Europa plume positives, pixel-level segmentation, or strong cross-instrument
robustness claims.

## Verified facts

| Item | Verified value |
|---|---|
| Title | *Planetary body limb and plume labels for NASA images* |
| Creators | Marissa Cameron, Gary Doran, Kiri Wagstaff (JPL) |
| Version / date | 1.0.0; published 2019-02-03; record last modified 2020-01-24 |
| License | CC BY-SA 4.0; open access |
| Deposit | One file, `plume_annotations.zip`, 151,704 bytes |
| Contents | 308 `.yml` labels, `README.txt`, `galileo_image_ids.txt`; **no images** |
| Positive / negative | 112 / 196 |
| Plume intervals | 287 total; 79 files contain more than one |
| Annotators | `mcameron` 101, `gdoran` 123, `wkiri` 84 |
| Limb points | 3–18 per image; 116/308 (38%) have only 3 |
| Directory counts | Enceladus 40; Callisto 7; Europa 22; Ganymede 13; Io (Galileo) 19; Mercury 123; Io (LORRI) 84 |
| Mapping status | 60 Galileo labels mapped through the sidecar; 1 Galileo label lacks a sidecar entry; 247 labels are only filename-stem candidates or unsupported |
| Source data | Real NASA Cassini ISS, Galileo SSI, MESSENGER MDIS, and New Horizons LORRI products |
| Synthetic content | None indicated; all sampled labels map to real PDS products |

The Zenodo record has **no formal “is supplement to” publication relation**.
Three dataset authors are authors of a 2019 LPSC abstract, *Automatic Plume
Detection for the Europa Imaging System* (bibcode `2019LPICo2151.7026D`) [12].
That is a likely context, not a formal dataset paper.

## Annotation semantics

- **Limb:** 3–18 points in `(x,y)` = `(col,row)` order; a least-squares circle
  fit is intended to model the limb. No fit residuals or uncertainty are stored.
- **Plume:** zero or more angular intervals in radians. The README states that
  angles start at 0 radians (up) and proceed clockwise. The **angular reference
  point is not explicitly defined**.
- **Negative:** the `plumes` key is absent. There is no explicit
  `plumes: []` or `has_plume` field.
- **Not present:** pixel masks, bounding boxes, confidence scores, plume type,
  plume height/extent, acquisition metadata, train/test splits, or a manifest.

## Provenance

The directory-level target/instrument mapping comes from the bundle README, not
from filename guessing. Sample source checks:

| Annotation | PDS product | Format | Native frame |
|---|---|---|---|
| Cassini `N1635781564_1` | `1_N1635781564.118` | PDS3 EDR | 1024×1024, 16-bit |
| MESSENGER `EN0108828545M` | `MSGRMDS_1001/DATA/2008_014/EN0108828545M.IMG` | PDS3 EDR | 1024×1024, 8-bit |
| LORRI `lor_0034583519_0x630_sci` | `LOR_0034583519_0X630_SCI` | FITS RDR | 1024×1024, 32-bit float |
| Galileo `G2C0004` | `2900r.img` in `go_0017` | PDS3 REDR | 800×800, 8-bit |

The source images are genuine mission products. The annotation coordinates fall
inside the native frame bounds, and the acquired Io sample loaded successfully.
This is not a verification of every one of the 308 products.

## Inferences

- The LPSC 2019 abstract is likely the immediate scientific context.
- The annotations were probably drawn on the native full-resolution frames,
  because the coordinate ranges fit those frames; the full set was not checked.
- Near-duplicate frames and shared observation sequences are likely, especially
  within the Enceladus and Io sequences. Exact duplicate labels were not found,
  but sequence groups were not reconstructed.
- The full image download is roughly 1 GB estimated, mostly LORRI FITS files.

## Unresolved questions and blockers

1. **Plume-angle reference convention.** The documented convention is
   `0 = up, clockwise`, with the angular origin at the fitted limb-circle center.
   This is supported by the dataset README and the KDD 2019 Figure 6 axis
   (“Direction (degrees clockwise from up)”). The conversion is implemented in
   `src/planetary_plume/angle_convention.py`; see
   `docs/angle_convention_investigation.md`. A residual inconsistency remains:
   LPSC 2019 Figure 1 appears to place one light-blue sector where the released
   intervals do not. Sector labels are **not** yet publication-grade, and no
   model should be trained on them until the residual is resolved.
2. **Physical truth of labels.** “Plume” means any bright material emitted from
   the body. The labels are not independently confirmed plumes.
3. **Negative selection.** The README does not document how negatives were
   chosen. “Negative” means no plume was annotated, not physically plume-free.
4. **All-product retrieval.** Only 12 Io products were downloaded and validated;
   the other 296 were not.
5. **Inter-rater agreement.** Each file has one annotator; no image has multiple
   annotations.
6. **Missing sidecar entry.** `galileo_ssi_europa/4852r_label.yml` has no entry
   in `galileo_image_ids.txt`; it is explicitly marked unresolved.
7. **Cassini and MESSENGER adapters.** These families are marked unsupported in
   this milestone. No PDS URLs were invented for them.

## Limitations for the research objective

- **Only 112 plume-positive annotations** across the full dataset; the effective
  sample is smaller because frames are correlated within sequences.
- **Only Io has both positive and negative annotations.** Enceladus is 40/40
  positive, so there are no same-target Enceladus negatives.
- **The dataset contains annotation files, not image pixels.** It is a label
  layer over PDS data, not a self-contained benchmark.
- **Annotation negatives are not necessarily physically plume-free.** They are
  operational negatives and may contain limb haze, stars, cosmic rays, or
  artifacts that were not labelled.
- **Instrument, target, and annotator differences are confounded.** `mcameron`
  labelled all Enceladus and Galilean-moon images, `gdoran` all Mercury, and
  `wkiri` all LORRI Io. All Enceladus labels are positive; all Mercury, Europa,
  Callisto, and Ganymede labels are negative. A model can learn target or
  annotator identity instead of plume physics.
- **No pixel masks or plume extent.** The labels are angular limb sectors, not
  segmentation masks.
- **No metadata or splits.** Time, filter, exposure, phase angle, resolution,
  and processing level must be joined from PDS. No leakage-resistant split is
  provided.
- **Mixed processing levels and formats.** EDR, REDR, and RDR; 800×800 and
  1024×1024; 8/16/32-bit; 3–1000 ms exposures.
- **License share-alike.** The annotations are CC BY-SA 4.0; derived label sets
  must be shared alike. Source images remain under separate NASA/PDS terms.

## Suitability decision

**PASS WITH CONDITIONS for a narrow Io pilot; FAIL as the sole primary dataset
for the full research objective.**

The defensible subset is Io-only: LORRI Io for a single-domain experiment with
controlled corruptions (84 labels: 60 positive / 24 negative), and Galileo Io as
a small external cross-instrument test (19 labels: 12 positive / 7 negative).
Enceladus is positive-only and should not be used to claim negative-class
performance. Europa, Callisto, and Ganymede are negative-only and should not be
used to claim plume detection.

## Sources

1. Zenodo record — <https://zenodo.org/records/2556063>
2. Zenodo API metadata — <https://zenodo.org/api/records/2556063>
3. DataCite metadata — <https://api.datacite.org/dois/10.5281/zenodo.2556063>
4. Annotation bundle — <https://zenodo.org/api/records/2556063/files/plume_annotations.zip/content>
5. CC BY-SA 4.0 — <https://creativecommons.org/licenses/by-sa/4.0/>
6. NASA media guidelines — <https://www.nasa.gov/nasa-brand-center/images-and-media/>
7. PDS Imaging Atlas — <https://pds-imaging.jpl.nasa.gov/search>
8. Cassini PDS label — <https://pds-imaging.jpl.nasa.gov/data/cassini/cassini_orbiter/coiss_2058/data/1635694741_1635809286/N1635781564_1.LBL>
9. MESSENGER raw EDR — <https://pds-imaging.jpl.nasa.gov/data/messenger/MSGRMDS_1001/DATA/2008_014/EN0108828545M.IMG>
10. LORRI PDS label — <https://pds-smallbodies.astro.umd.edu/holdings/nh-j-lorri-3-jupiter-v3.0/data/20070224_003458/lor_0034583519_0x630_sci.lbl>
11. Galileo PDS product — <https://pds-imaging.jpl.nasa.gov/pds/prod?q=OFSN+%3D+/data/galileo/galileo_orbiter//go_0017/g2/callisto/c036032/2900r.img+AND+RT+%3D+RAW>
12. LPSC 2019 abstract — <https://ui.adsabs.harvard.edu/abs/2019LPICo2151.7026D/abstract>
13. PDS — <https://pds.nasa.gov/>
