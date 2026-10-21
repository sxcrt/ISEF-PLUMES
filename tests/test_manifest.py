"""Tests for manifest export and summary formatting."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from planetary_plume.annotations import build_inventory
from planetary_plume.manifest import (
    CSV_FIELDS,
    format_manifest_summary,
    manifest_payload,
    write_manifest,
)


def _make_bundle(tmp_path: Path) -> Path:
    root = tmp_path / "bundle"
    io = root / "galileo_ssi_io"
    io.mkdir(parents=True)
    (io / "0085r_label.yml").write_text(
        "\n".join(
            [
                "plumes:",
                "  intervals:",
                "  - [2.85, 3.02]",
                "  user: mcameron",
                "points:",
                "- [10, 20]",
                "- [30, 20]",
                "- [20, 40]",
                "user: mcameron",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (io / "1300r_label.yml").write_text(
        "\n".join(
            [
                "points:",
                "- [10, 20]",
                "- [30, 20]",
                "- [20, 40]",
                "user: mcameron",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "galileo_image_ids.txt").write_text(
        "0085r_label.yml 11I0012\n1300r_label.yml G7I0001\n",
        encoding="utf-8",
    )
    return root


def test_manifest_payload_has_explicit_provenance(tmp_path: Path) -> None:
    inventory = build_inventory(_make_bundle(tmp_path))

    payload = manifest_payload(inventory, generated_at="2026-10-20T00:00:00+00:00")

    assert payload["manifest_version"] == 1
    assert payload["source"]["doi"] == "10.5281/zenodo.2556063"
    assert payload["summary"]["total_annotations"] == 2
    assert payload["summary"]["plume_positive"] == 1
    assert payload["notes"]
    assert len(payload["records"]) == 2
    assert payload["records"][0]["annotation_relative_path"].endswith("_label.yml")


def test_write_manifest_writes_json_and_csv_without_touching_source(tmp_path: Path) -> None:
    root = _make_bundle(tmp_path)
    inventory = build_inventory(root)
    before = (root / "galileo_ssi_io" / "0085r_label.yml").read_bytes()

    paths = write_manifest(inventory, tmp_path / "outputs", generated_at="2026-10-20T00:00:00+00:00")

    assert paths["json"].is_file()
    assert paths["csv"].is_file()
    assert (root / "galileo_ssi_io" / "0085r_label.yml").read_bytes() == before

    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert payload["generated_at_utc"] == "2026-10-20T00:00:00+00:00"
    assert len(payload["records"]) == 2

    with paths["csv"].open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert tuple(rows[0].keys()) == CSV_FIELDS
    assert len(rows) == 2
    assert rows[0]["plume_status"] == "True"
    assert json.loads(rows[0]["plume_intervals"]) == [[2.85, 3.02]]


def test_manifest_summary_states_limitations(tmp_path: Path) -> None:
    inventory = build_inventory(_make_bundle(tmp_path))

    text = format_manifest_summary(inventory)

    assert "Annotations parsed: 2" in text
    assert "does not contain image pixels" in text
    assert "not PDS product IDs" in text
