# Research Plan

**Project:** Uncertainty-Aware Deep Learning for Planetary Plume Detection Under
Imaging Variations

**Status:** Dataset gate **passed with conditions** for a narrow Io pilot
(Zenodo 2556063). The model architecture is **UNDECIDED**; no model experiments
have been run. The documented plume-angle conversion is implemented; a residual
LPSC Figure 1 inconsistency remains unresolved for publication-grade claims.

**Last updated:** 2026-10-20

## 1. Research objective

Develop and evaluate a machine-learning system that identifies candidate
planetary plumes in spacecraft imagery and expresses predictive uncertainty, with
an explicit assessment of how performance changes under imaging variations.

The first deliverable is **not** a neural network. It is a verified data
foundation: a documented dataset, a defensible task definition, and a split and
evaluation protocol that can support scientific claims. A model trained on
unverified labels would produce numbers without meaning.

## 2. Research questions

These questions are conditional on the dataset gate in Section 5.

- **RQ1 (data sufficiency):** Does the available imagery contain enough verified,
  consistently labeled examples to support plume-candidate detection, and at what
  level of granularity (image, patch, object, or pixel)?
- **RQ2 (robustness):** How do detection performance and uncertainty estimates
  change under realistic imaging variations such as noise, compression,
  resolution changes, contrast changes, and viewing geometry?
- **RQ3 (uncertainty):** Are predictive uncertainty estimates calibrated, and can
  they support selective prediction or triage of candidate detections?

### Proposed hypotheses (untested)

- **H1:** A learned model can separate verified plume candidates from verified
  negatives better than trivial and classical baselines on held-out observations.
- **H2:** Performance degrades under at least some realistic imaging variations,
  and the degradation is not uniform across targets or acquisition conditions.
- **H3:** Uncertainty estimates identify a meaningful fraction of errors or
  out-of-distribution inputs, enabling risk-controlled triage.

These are hypotheses, not findings. They may be rejected or revised after the
data audit.

## 3. Scope and non-goals

**In scope (eventually):**

- a documented, legally usable dataset of spacecraft imagery;
- a clearly defined detection or classification task;
- reproducible baselines and model evaluation;
- controlled robustness tests;
- uncertainty quantification and calibration analysis.

**Out of scope for now:**

- claiming that the system detects plumes in a scientific sense before labels and
  validation exist;
- generating synthetic data;
- model selection or training;
- interpreting candidate detections as confirmed physical phenomena;
- cloud authentication, automatic uploads, or distributed training.

## 4. Data categories and mandatory separation

Every file or sample must be assigned to one category, with evidence recorded.

| Category | Definition | Current status |
| --- | --- | --- |
| **Observed plume candidates** | Real spacecraft observations asserted to contain a plume or plume candidate, with provenance and processing level recorded. | Partially verified: 112 annotated positives, Enceladus/Io only; documented angle convention, LPSC figure residual. |
| **Observed negatives** | Real observations from a comparable instrument and conditions, asserted not to contain a plume candidate. The negative definition must be explicit. | Partially verified: 196 annotation negatives; not verified physical absences. |
| **Confounders** | Limb haze, clouds, background stars, cosmic rays, detector artifacts, compression artifacts, or other features that can mimic a plume. These may overlap with negatives but are not automatically labels. | Not characterized or labelled. |
| **Synthetic / simulated** | Rendered, modeled, or otherwise generated images. Must be labeled as synthetic at the file and experiment level. | None indicated in the verified bundle. |

### Separation policy

1. Synthetic data is never described as observed data.
2. Observed, synthetic, and confounder categories are not pooled in training or
   evaluation without a written justification and a separate ablation that
   isolates the effect of pooling.
3. Directory names, filenames, and assumed mission conventions are not labels.
4. Any relabeling, exclusion, or merging decision is recorded in the experiment
   log with a reason.
5. The final test set should be observed data unless the research question is
   explicitly about synthetic-to-real transfer; in that case the claim must be
   phrased accordingly. This is a recommendation, not yet a finalized protocol.

## 5. Dataset verification gate

Zenodo 2556063 has been verified as a **label-only** dataset for 308 real NASA
images. It is accepted only for a **narrow Io pilot**; it is not accepted as the
sole dataset for the full research objective. The verification evidence and
unresolved questions are in `docs/dataset_verification.md`; the sample validation
is in `docs/dataset_validation.md`.

The generic audit script answers only the file-inventory portion of this gate.
The dedicated manifest/acquisition/validation pipeline is the stronger evidence
for this dataset.

### 5.1 Required evidence

| Check | Evidence required | Status |
| --- | --- | --- |
| Identity and provenance | Producer, mission/instrument, processing level, publication/DOI, contact, retrieval date | **Verified** (JPL/Zenodo; NASA PDS products; 12 Io products sampled) |
| License and terms | License text, redistribution permission, citation requirements | **Verified** (annotations CC BY-SA 4.0; images separate NASA/PDS terms) |
| File inventory | Audit output with counts, extensions, sizes, dimensions, unreadable files | **Verified** (308 YAML + 2 TXT; no images) |
| Annotation definition | What a positive means; who labeled it; image-level vs pixel-level; label files and schema | **Partial** (limb points + angular intervals; documented 0-up origin; LPSC figure residual; no masks) |
| Observation metadata | Target, time, filter, exposure, geometry, calibration state where available | **Not in dataset**; must be joined from PDS |
| Synthetic composition | Whether any files are simulated, and how they are identified | **Verified none indicated** in sampled products |
| Negatives and confounders | How negatives were selected; which confounders are present or labeled | **Partial/fail** (196 annotation negatives; selection undocumented; no confounder labels) |
| Duplicates and leakage | Exact/near duplicates, frame sequences, overlapping crops, source-level groups | **Partial** (no exact duplicate labels; sequences not reconstructed) |
| Class balance and coverage | Counts by class, target, instrument, and acquisition condition | **Verified** (112 pos/196 neg; only Io has both classes) |
| Redistribution | Whether data may be shared or must stay local/cloud-only | **Verified with conditions** (CC BY-SA annotations; NASA/PDS images separate) |
| Compute footprint | Total size and feasibility on CPU and free cloud GPUs | **Partial** (~1 GB estimated; 12-image sample 68 MB) |

### 5.2 Gate procedure

1. Obtain the dataset through a documented source. Record the DOI/URL, retrieval
   date, and checksum where practical.
2. Inspect the license and citation requirements before copying or processing.
3. Run:
   `python scripts/audit_dataset.py <path> --json outputs/dataset_audit.json`
4. Read the dataset documentation and, if present, the label schema. Do not infer
   labels from directory names.
5. Manually inspect a small, documented sample of files across categories.
6. Record whether observed, synthetic, negative, and confounder categories are
   separable and identifiable.
7. Write a dataset audit entry in `docs/experiment_log.md`.
8. Decide the task granularity that the labels legitimately support.

**Recorded outcome:** PASS WITH CONDITIONS for a narrow Io pilot; the full
research objective is not yet supported. The documented angle conversion is
implemented; the residual LPSC Figure 1 inconsistency is the remaining
publication-grade blocker.

### 5.3 Gate outcomes

- **PASS:** provenance, license, labels, and composition are documented; a
  defensible task and split are possible.
- **PASS WITH CONDITIONS:** usable for a narrower task or subset; conditions are
  written down (for example, image-level labels only).
- **FAIL:** provenance, license, or labels are insufficient. Do not train a model
  to compensate for missing scientific ground truth.

No model selection, training, or synthetic-data generation begins before this
decision is recorded.

## 6. Proposed experimental direction (conditional)

This section describes a possible path. It is not a commitment to an
architecture or a completed design.

### Phase 0 — Dataset audit and task definition

- Run the file inventory and document provenance, license, and labels.
- Determine whether the data supports classification, detection, or
  segmentation. The task must follow the labels, not the other way around.
- Define positive, negative, confounder, and exclusion criteria.
- Freeze a split protocol and primary metric before model development.

### Phase 1 — Baselines

Start with the simplest defensible baselines:

- trivial baselines (majority class or constant score) to expose class imbalance;
- a classical baseline using documented, reproducible features if feasible;
- a small convolutional network as the first learned baseline.

Baselines provide a reference point and reveal leakage or label problems early.

### Phase 2 — Model development (architecture UNDECIDED)

Candidate families, to be compared only if the data and compute justify them:

- image-level CNN classifier;
- patch-level classifier with aggregation;
- encoder–decoder segmentation network (only with pixel-level masks);
- transfer learning from a pretrained encoder (only if licensing and domain fit
  are acceptable).

Selection criteria: label granularity, dataset size, class balance, compute
budget, interpretability, and whether the model can be trained reproducibly.
No architecture is selected at this stage.

### Phase 3 — Imaging-variation robustness

Two kinds of variation must be distinguished:

1. **Real acquisition variation** observed in metadata: target, illumination,
   phase angle, exposure, filter, resolution, compression, and detector state.
   Evaluate performance by stratum where metadata permits.
2. **Controlled stress tests:** synthetic corruptions applied to held-out images,
   such as noise, blur, contrast changes, downsampling, JPEG compression, and
   small shifts or crops.

Controlled corruptions are not evidence about real instrument behavior. If both
are used, report them separately. Training-time augmentation is a separate
decision and requires justification.

### Phase 4 — Uncertainty

Candidate approaches (none selected):

- deep ensembles;
- Monte Carlo dropout;
- quantile or evidential heads;
- post-hoc calibration such as temperature scaling.

Evaluation should include calibration (for example reliability diagrams, expected
calibration error, Brier score), selective prediction / risk–coverage curves, and
out-of-distribution or corruption detection. The compute cost of ensembles must be
weighed against any benefit.

### Phase 5 — Evaluation and reporting

- Evaluate once on the frozen test set after model selection on validation data.
- Report per-stratum results, confidence intervals, and failure cases.
- Separate descriptive results from causal or physical interpretations.
- Record every actual run in `docs/experiment_log.md`.

## 7. Splitting and leakage policy

Randomly splitting individual frames is likely to leak information when frames
come from the same observation, timestep, or overlapping crop.

**Recommended default:** group splits by observation/source identifier, and check
for near duplicates before training. Keep targets, instruments, or acquisition
conditions disjoint where the research question requires generalization.

Alternatives:

- random frame-level split (only if frames are genuinely independent and
  documented as such);
- leave-one-target-out or leave-one-instrument-out (stronger generalization test,
  but may leave too little data).

The chosen protocol, and its limitations, must be recorded before evaluation.

## 8. Evaluation principles

The primary metric depends on the task and must be chosen before test-set use:

- **Classification:** AUROC and AUPRC, sensitivity at a fixed false-positive
  rate, calibration, and confusion matrices. Accuracy alone is insufficient under
  class imbalance.
- **Detection:** precision–recall behavior, localization thresholds, and
  false-positive rate per image.
- **Segmentation:** Dice and IoU with clearly defined matching rules.
- **Uncertainty:** calibration error, Brier score, risk–coverage, and
  uncertainty–error correlation.

Report bootstrap confidence intervals where meaningful. Do not select models on
the test set. Record negative and inconclusive results.

## 9. Reproducibility

Each experiment entry must include:

- configuration file and Git commit;
- dataset version, source, and audit reference;
- random seeds;
- Python, package, and hardware environment;
- exact command;
- metrics and observations;
- artifacts and where they are stored (outside Git if large).

## 10. Risks and mitigations

| Risk | Consequence | Mitigation |
| --- | --- | --- |
| Dataset license forbids use or redistribution | Project cannot use the data | Verify before processing; choose another documented source |
| Labels are absent or inconsistent | No supervised task is possible | Narrow the task, seek verified labels, or stop |
| Confounders dominate | Inflated performance and false scientific claims | Characterize confounders; stratify and inspect errors |
| Leakage across splits | Overstated generalization | Group splits; near-duplicate checks |
| Small dataset | Unstable estimates | Cross-validation, confidence intervals, simple models |
| Free cloud GPU unavailable | Training cannot run | CPU smoke tests; small models; no GPU assumption |
| Synthetic data mismatches observations | Misleading transfer claims | Keep categories separate; test on observed data |

## 11. Open questions

- What exactly does the candidate dataset contain, and under what license?
- Are labels image-level, patch-level, bounding boxes, or pixel masks?
- Who produced the labels, and what is the reported annotation protocol?
- Are negatives sampled from comparable conditions?
- Which confounders are present and identifiable?
- Is there enough data for a held-out observation-level test set?
- Which imaging variations are recorded in metadata versus only inferable?
- What compute budget is realistically available?
- Is uncertainty estimation better served by ensembles, approximate Bayesian
  methods, or post-hoc calibration for this dataset size?
- What result would count as evidence for or against each hypothesis?

## 12. Non-claims

This plan does not claim that:

- the proposed dataset is suitable, licensed, or correctly labeled;
- plumes are present in any particular file;
- a deep model is necessary or will outperform simpler baselines;
- any architecture or uncertainty method has been selected;
- any experiment has been run or any result obtained;
- any citation has been verified. The literature review is pending.
