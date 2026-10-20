# Experiment Log

> **No experiments have been recorded.** This file defines the recording format.
> Do not add invented results, backfilled metrics, or entries for runs that did
> not happen.

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
| _(none yet)_ | | | | | | |

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
