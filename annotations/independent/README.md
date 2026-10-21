# Independent annotations

This directory holds **your** independent plume-candidate annotations and the
sanitized review manifest used by the annotation GUI. It is separate from the
released labels under `data/raw/zenodo_2556063/annotations/`.

Generated and reviewer-created files are ignored by Git by default:

- `review_manifest.json` — sanitized image identity, dimensions, paths, and limb
  geometry only.
- `release_label_map.json` — comparison-only image-ID mapping. **Do not open this
  file during independent review.**
- `independent_review.json` — your saved annotations.
- `independent_review.json.bak` — one-generation backup written on save.

Build the manifest once, then launch the GUI:

```powershell
python scripts\build_review_manifest.py
python scripts\annotate_candidates.py
```

Do not edit these JSON files by hand while the application is open. See
`docs/independent_annotation.md` for the full protocol.
