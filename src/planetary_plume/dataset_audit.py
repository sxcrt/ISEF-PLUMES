"""Format-agnostic dataset inventory and image-dimension sampling.

The audit deliberately avoids interpreting labels, masks, or mission metadata.
It answers "what files are here?" and nothing more. Directory names must never be
treated as scientific labels without independent verification.
"""

from __future__ import annotations

import os
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

DEFAULT_IMAGE_EXTENSIONS: tuple[str, ...] = (
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".bmp",
    ".webp",
)


class DatasetAuditError(RuntimeError):
    """Raised when the requested dataset directory cannot be audited."""


@dataclass(frozen=True)
class TopLevelSummary:
    """File count and size for one immediate child directory."""

    name: str
    files: int
    bytes: int


@dataclass(frozen=True)
class DatasetAudit:
    """Descriptive snapshot of a directory tree."""

    root: Path
    total_files: int
    total_directories: int
    total_bytes: int
    root_files: int
    max_depth: int
    extension_counts: dict[str, int]
    top_level: tuple[TopLevelSummary, ...]
    image_files: int
    images_inspected: int
    sampled: bool
    dimension_counts: dict[str, int]
    mode_counts: dict[str, int]
    unreadable_images: tuple[str, ...]
    walk_errors: tuple[str, ...]


def _normalize_extensions(extensions: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()

    for index, extension in enumerate(extensions):
        if not isinstance(extension, str) or not extension.startswith("."):
            raise DatasetAuditError(
                f"Image extension at index {index} must start with a dot."
            )
        lowered = extension.lower()
        if lowered not in seen:
            seen.add(lowered)
            normalized.append(lowered)

    return tuple(normalized)


def _sample_paths(
    paths: Sequence[Path], limit: int
) -> tuple[list[Path], bool]:
    """Select an evenly spaced deterministic sample.

    ``limit <= 0`` means "inspect every path". Sampling is reported explicitly so
    that dimension statistics are never mistaken for a census.
    """

    if limit <= 0 or len(paths) <= limit:
        return list(paths), False
    if limit == 1:
        return [paths[len(paths) // 2]], True

    step = (len(paths) - 1) / (limit - 1)
    indices = sorted({round(index * step) for index in range(limit)})
    return [paths[index] for index in indices], True


def audit_dataset(
    root: str | Path,
    *,
    image_extensions: Sequence[str] = DEFAULT_IMAGE_EXTENSIONS,
    dimension_sample_size: int = 500,
) -> DatasetAudit:
    """Inventory a directory tree and sample image dimensions.

    Args:
        root: Directory to inspect. It may contain any file types.
        image_extensions: Extensions Pillow should attempt to open. These are not
            claims about the dataset format; all extensions are counted.
        dimension_sample_size: Number of image files to inspect. ``0`` inspects
            all matching files. Sampling is deterministic and evenly spaced.

    Raises:
        DatasetAuditError: If the path is missing, not a directory, or has an
            invalid sampling limit.
    """

    if (
        isinstance(dimension_sample_size, bool)
        or not isinstance(dimension_sample_size, int)
        or dimension_sample_size < 0
    ):
        raise DatasetAuditError("dimension_sample_size must be a non-negative integer.")

    audit_root = Path(root).expanduser().resolve(strict=False)
    if not audit_root.exists():
        raise DatasetAuditError(f"Dataset directory does not exist: {audit_root}")
    if not audit_root.is_dir():
        raise DatasetAuditError(f"Dataset path is not a directory: {audit_root}")

    extension_set = set(_normalize_extensions(image_extensions))
    extension_counts: Counter[str] = Counter()
    image_paths: list[Path] = []
    top_level_data: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    walk_errors: list[str] = []

    total_files = 0
    total_directories = 0
    total_bytes = 0
    root_files = 0
    max_depth = 0

    def on_walk_error(error: OSError) -> None:
        location = getattr(error, "filename", None) or "<unknown>"
        walk_errors.append(f"{location}: {error.strerror or error}")

    for current_dir, dirnames, filenames in os.walk(
        audit_root, onerror=on_walk_error, followlinks=False
    ):
        current_path = Path(current_dir)
        relative_dir = current_path.relative_to(audit_root)
        directory_depth = len(relative_dir.parts)
        max_depth = max(max_depth, directory_depth)
        total_directories += len(dirnames)

        for filename in filenames:
            path = current_path / filename
            relative_path = path.relative_to(audit_root)
            relative_parts = relative_path.parts
            total_files += 1

            extension = path.suffix.lower() or "(no extension)"
            extension_counts[extension] += 1

            try:
                size = path.stat().st_size
            except OSError as exc:
                walk_errors.append(f"{path}: {exc}")
                size = 0
            total_bytes += size

            if len(relative_parts) == 1:
                root_files += 1
            else:
                top_level_entry = top_level_data[relative_parts[0]]
                top_level_entry[0] += 1
                top_level_entry[1] += size

            if path.suffix.lower() in extension_set:
                image_paths.append(path)

    image_paths.sort(key=lambda item: item.as_posix().lower())
    sampled_paths, sampled = _sample_paths(image_paths, dimension_sample_size)

    dimensions: Counter[str] = Counter()
    modes: Counter[str] = Counter()
    unreadable: list[str] = []

    for path in sampled_paths:
        try:
            with Image.open(path) as image:
                width, height = image.size
                mode = image.mode
            dimensions[f"{width}x{height}"] += 1
            modes[mode] += 1
        except (OSError, UnidentifiedImageError, ValueError) as exc:
            relative = path.relative_to(audit_root).as_posix()
            unreadable.append(f"{relative}: {type(exc).__name__}: {exc}")
        except Exception as exc:  # A malformed file must not abort the audit.
            relative = path.relative_to(audit_root).as_posix()
            unreadable.append(f"{relative}: {type(exc).__name__}: {exc}")

    top_level = tuple(
        TopLevelSummary(name=name, files=values[0], bytes=values[1])
        for name, values in sorted(
            top_level_data.items(), key=lambda item: item[0].casefold()
        )
    )

    return DatasetAudit(
        root=audit_root,
        total_files=total_files,
        total_directories=total_directories,
        total_bytes=total_bytes,
        root_files=root_files,
        max_depth=max_depth,
        extension_counts=dict(extension_counts),
        top_level=top_level,
        image_files=len(image_paths),
        images_inspected=len(sampled_paths),
        sampled=sampled,
        dimension_counts=dict(dimensions),
        mode_counts=dict(modes),
        unreadable_images=tuple(unreadable),
        walk_errors=tuple(walk_errors),
    )


def format_bytes(value: int) -> str:
    """Format a byte count using binary units."""

    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or unit == "TiB":
            if unit == "B":
                return f"{int(amount)} {unit}"
            return f"{amount:.1f} {unit}"
        amount /= 1024

    return f"{amount:.1f} TiB"


def format_audit(
    report: DatasetAudit,
    *,
    max_extensions: int = 15,
    max_unreadable: int = 10,
) -> str:
    """Render a human-readable audit report."""

    lines = [
        "Dataset audit (descriptive only)",
        "================================",
        f"Root: {report.root}",
        f"Files: {report.total_files:,}",
        f"Directories (excluding root): {report.total_directories:,}",
        f"Maximum directory depth: {report.max_depth}",
        f"Total size: {format_bytes(report.total_bytes)}",
        f"Files directly in root: {report.root_files:,}",
        "",
        "File extensions",
        "---------------",
    ]

    if not report.extension_counts:
        lines.append("  (no files found)")
    else:
        ordered_extensions = sorted(
            report.extension_counts.items(), key=lambda item: (-item[1], item[0])
        )
        for extension, count in ordered_extensions[:max_extensions]:
            lines.append(f"  {extension:<16} {count:,}")
        omitted = len(ordered_extensions) - max_extensions
        if omitted > 0:
            lines.append(f"  ... {omitted:,} more extension(s) not shown")

    lines.extend(["", "Top-level entries", "-----------------"])
    if report.top_level:
        for entry in report.top_level:
            lines.append(
                f"  {entry.name}/  {entry.files:,} files, "
                f"{format_bytes(entry.bytes)}"
            )
    else:
        lines.append("  (no immediate child directories)")

    lines.extend(
        [
            "",
            "Image dimensions",
            "----------------",
            f"  Files matching configured image extensions: "
            f"{report.image_files:,}",
            f"  Files inspected with Pillow: {report.images_inspected:,}",
        ]
    )

    if report.sampled:
        lines.append(
            "  Sampling: deterministic even sample; this is not a full census. "
            "Set dimension_sample_size (or --max-images) to 0 to inspect all."
        )
    elif report.image_files:
        lines.append("  Sampling: all matching image files were inspected.")

    if report.dimension_counts:
        lines.append("  Dimensions:")
        for dimensions, count in sorted(
            report.dimension_counts.items(), key=lambda item: (-item[1], item[0])
        ):
            lines.append(f"    {dimensions:<16} {count:,}")

    if report.mode_counts:
        modes = ", ".join(
            f"{mode} ({count:,})"
            for mode, count in sorted(
                report.mode_counts.items(), key=lambda item: (-item[1], item[0])
            )
        )
        lines.append(f"  Color modes: {modes}")

    if not report.image_files:
        lines.append(
            "  No files matched the configured image extensions. Other file "
            "types are still counted above."
        )

    if report.unreadable_images:
        lines.append(
            f"  Unreadable or unsupported: {len(report.unreadable_images):,}"
        )
        for sample in report.unreadable_images[:max_unreadable]:
            lines.append(f"    {sample}")
        omitted = len(report.unreadable_images) - max_unreadable
        if omitted > 0:
            lines.append(f"    ... {omitted:,} more not shown")

    if report.walk_errors:
        lines.append("")
        lines.append(f"Walk errors: {len(report.walk_errors):,}")
        for error in report.walk_errors[:max_unreadable]:
            lines.append(f"  {error}")
        omitted = len(report.walk_errors) - max_unreadable
        if omitted > 0:
            lines.append(f"  ... {omitted:,} more not shown")

    lines.extend(
        [
            "",
            "Important",
            "---------",
            "  This report describes file structure only. It does not verify labels,",
            "  provenance, licensing, annotation quality, class balance, or",
            "  scientific suitability. Directory names are not labels. FITS and",
            "  other unsupported formats are counted but not opened.",
        ]
    )

    return "\n".join(lines)


def audit_to_dict(report: DatasetAudit) -> dict[str, object]:
    """Convert an audit report into JSON-serializable values."""

    return {
        "root": str(report.root),
        "total_files": report.total_files,
        "total_directories": report.total_directories,
        "total_bytes": report.total_bytes,
        "root_files": report.root_files,
        "max_depth": report.max_depth,
        "extension_counts": report.extension_counts,
        "top_level": [
            {"name": entry.name, "files": entry.files, "bytes": entry.bytes}
            for entry in report.top_level
        ],
        "image_files": report.image_files,
        "images_inspected": report.images_inspected,
        "sampled": report.sampled,
        "dimension_counts": report.dimension_counts,
        "mode_counts": report.mode_counts,
        "unreadable_images": list(report.unreadable_images),
        "walk_errors": list(report.walk_errors),
    }
