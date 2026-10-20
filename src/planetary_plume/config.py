"""Load and validate the project YAML configuration.

Configuration is validated explicitly so that mistakes produce a clear error
instead of a mysterious failure later in an experiment. Relative paths are
resolved against the repository root to keep local and cloud runs consistent.
"""

from __future__ import annotations

import copy
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = DEFAULT_PROJECT_ROOT / "config" / "default.yaml"

_ENV_OVERRIDES = (
    ("paths", "data_dir", "PLUME_DATA_DIR"),
    ("paths", "outputs_dir", "PLUME_OUTPUT_DIR"),
    ("dataset", "root", "PLUME_DATASET_ROOT"),
)


class ConfigError(ValueError):
    """Raised when configuration is missing, malformed, or inconsistent."""


@dataclass(frozen=True)
class ProjectSettings:
    name: str
    random_seed: int


@dataclass(frozen=True)
class PathSettings:
    data_dir: Path
    outputs_dir: Path


@dataclass(frozen=True)
class DatasetSettings:
    root: Path | None
    image_extensions: tuple[str, ...]
    dimension_sample_size: int


@dataclass(frozen=True)
class AppConfig:
    project: ProjectSettings
    paths: PathSettings
    dataset: DatasetSettings
    source_path: Path


def _expect_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigError(
            f"'{label}' must be a mapping/object, got {type(value).__name__}."
        )
    return value


def _require(mapping: Mapping[str, Any], key: str, section: str) -> Any:
    if key not in mapping:
        raise ConfigError(f"Missing required key '{section}.{key}'.")
    return mapping[key]


def _reject_unknown_keys(
    mapping: Mapping[str, Any], allowed: set[str], section: str
) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        formatted = ", ".join(repr(key) for key in unknown)
        expected = ", ".join(repr(key) for key in sorted(allowed))
        raise ConfigError(
            f"Unknown key(s) in '{section}': {formatted}. Expected: {expected}."
        )


def _non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"'{label}' must be a non-empty string.")
    return value.strip()


def _non_negative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ConfigError(f"'{label}' must be a non-negative integer.")
    return value


def _resolve_path(value: Any, label: str, project_root: Path) -> Path:
    raw = _non_empty_string(value, label)
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = project_root / path
    return path.resolve(strict=False)


def _parse_project(raw: Mapping[str, Any]) -> ProjectSettings:
    project = _expect_mapping(_require(raw, "project", "root"), "project")
    _reject_unknown_keys(project, {"name", "random_seed"}, "project")

    name = _non_empty_string(_require(project, "name", "project"), "project.name")
    random_seed = _non_negative_int(
        _require(project, "random_seed", "project"), "project.random_seed"
    )
    return ProjectSettings(name=name, random_seed=random_seed)


def _parse_paths(raw: Mapping[str, Any], project_root: Path) -> PathSettings:
    paths = _expect_mapping(_require(raw, "paths", "root"), "paths")
    _reject_unknown_keys(paths, {"data_dir", "outputs_dir"}, "paths")

    data_dir = _resolve_path(
        _require(paths, "data_dir", "paths"), "paths.data_dir", project_root
    )
    outputs_dir = _resolve_path(
        _require(paths, "outputs_dir", "paths"), "paths.outputs_dir", project_root
    )
    return PathSettings(data_dir=data_dir, outputs_dir=outputs_dir)


def _parse_dataset(raw: Mapping[str, Any], project_root: Path) -> DatasetSettings:
    dataset = _expect_mapping(_require(raw, "dataset", "root"), "dataset")
    _reject_unknown_keys(
        dataset, {"root", "image_extensions", "dimension_sample_size"}, "dataset"
    )

    raw_root = _require(dataset, "root", "dataset")
    root: Path | None
    if raw_root is None:
        root = None
    else:
        root = _resolve_path(raw_root, "dataset.root", project_root)

    raw_extensions = _require(dataset, "image_extensions", "dataset")
    if not isinstance(raw_extensions, list) or not raw_extensions:
        raise ConfigError("'dataset.image_extensions' must be a non-empty list.")

    extensions: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_extensions):
        label = f"dataset.image_extensions[{index}]"
        extension = _non_empty_string(item, label).lower()
        if not extension.startswith("."):
            raise ConfigError(f"'{label}' must start with a dot, got {extension!r}.")
        if extension not in seen:
            seen.add(extension)
            extensions.append(extension)

    dimension_sample_size = _non_negative_int(
        _require(dataset, "dimension_sample_size", "dataset"),
        "dataset.dimension_sample_size",
    )

    return DatasetSettings(
        root=root,
        image_extensions=tuple(extensions),
        dimension_sample_size=dimension_sample_size,
    )


def _apply_env_overrides(data: dict[str, Any]) -> None:
    for section, key, variable in _ENV_OVERRIDES:
        value = os.environ.get(variable)
        if value is None or not value.strip():
            continue

        section_value = data.get(section)
        if not isinstance(section_value, dict):
            section_value = {}
            data[section] = section_value
        section_value[key] = value.strip()


def load_config(
    path: str | Path | None = None,
    *,
    project_root: str | Path | None = None,
    use_env: bool = True,
) -> AppConfig:
    """Load, validate, and return the project configuration.

    Args:
        path: YAML file to load. If omitted, ``PLUME_CONFIG`` is used when it is
            set; otherwise ``config/default.yaml`` is loaded.
        project_root: Base directory for relative paths. Defaults to the
            repository root. This is separate from the config file location.
        use_env: Apply ``PLUME_DATA_DIR``, ``PLUME_OUTPUT_DIR``, and
            ``PLUME_DATASET_ROOT`` overrides. Tests disable this for isolation.

    Raises:
        ConfigError: If the file is missing, invalid YAML, or fails validation.
    """

    env_config = os.environ.get("PLUME_CONFIG") if use_env else None
    if path is None:
        config_path = Path(env_config) if env_config else DEFAULT_CONFIG_PATH
    else:
        config_path = Path(path)

    config_path = config_path.expanduser()
    if not config_path.is_absolute():
        config_path = Path.cwd() / config_path
    config_path = config_path.resolve(strict=False)

    if not config_path.is_file():
        raise ConfigError(f"Configuration file not found: {config_path}")

    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Could not read configuration {config_path}: {exc}") from exc

    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {config_path}: {exc}") from exc

    if raw is None:
        raise ConfigError(f"Configuration file is empty: {config_path}")

    try:
        root_map = _expect_mapping(raw, "configuration root")
        _reject_unknown_keys(root_map, {"project", "paths", "dataset"}, "root")

        data = copy.deepcopy(dict(root_map))
        if use_env:
            _apply_env_overrides(data)

        resolved_project_root = (
            Path(project_root).expanduser().resolve()
            if project_root is not None
            else DEFAULT_PROJECT_ROOT
        )

        project = _parse_project(data)
        paths = _parse_paths(data, resolved_project_root)
        dataset = _parse_dataset(data, resolved_project_root)
    except ConfigError as exc:
        raise ConfigError(f"Invalid configuration in {config_path}: {exc}") from exc

    return AppConfig(
        project=project,
        paths=paths,
        dataset=dataset,
        source_path=config_path,
    )
