"""Tests for environment and configuration utilities.

These tests do not require a GPU, network access, PyTorch, or external data.
"""

from __future__ import annotations

import sys
import textwrap
import types
from pathlib import Path
from typing import Any

import pytest

from planetary_plume.config import (
    DEFAULT_PROJECT_ROOT,
    ConfigError,
    load_config,
)
from planetary_plume.environment import (
    EnvironmentReport,
    PackageStatus,
    TorchStatus,
    _torch_status,
    collect_environment,
    format_environment_report,
)

VALID_CONFIG = """\
project:
  name: test-project
  random_seed: 7
paths:
  data_dir: workspace/data
  outputs_dir: workspace/outputs
dataset:
  root: null
  image_extensions:
    - .png
    - .JPG
  dimension_sample_size: 10
"""


def _write_config(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


def _minimal_report(torch_status: TorchStatus) -> EnvironmentReport:
    return EnvironmentReport(
        python_version="3.13.0",
        python_executable="C:/Python/python.exe",
        platform="Windows-11",
        system="Windows",
        machine="AMD64",
        packages=(
            PackageStatus("PyYAML", "yaml", "core", True, "6.0.2"),
            PackageStatus("numpy", "numpy", "core", True, "2.2.0"),
            PackageStatus("Pillow", "PIL", "core", True, "11.0.0"),
            PackageStatus(
                "torch",
                "torch",
                "ml",
                torch_status.installed,
                torch_status.version,
            ),
            PackageStatus("pytest", "pytest", "dev", True, "8.3.0"),
        ),
        torch=torch_status,
    )


def test_collect_environment_reports_python_and_packages() -> None:
    report = collect_environment()

    assert report.python_version
    assert report.python_executable
    assert report.system
    assert report.machine
    assert {package.group for package in report.packages} == {
        "core",
        "ml",
        "dev",
    }

    report_text = format_environment_report(report)
    assert "Environment diagnostic" in report_text
    assert "Python:" in report_text
    assert "PyTorch and CUDA" in report_text
    assert "CUDA available" in report_text or "PyTorch is not installed" in report_text


def test_format_report_handles_missing_torch() -> None:
    report = _minimal_report(
        TorchStatus(
            installed=False,
            error="ModuleNotFoundError: No module named 'torch'",
        )
    )

    report_text = format_environment_report(report)

    assert "[MISSING]" in report_text
    assert "PyTorch is not installed" in report_text
    assert "ModuleNotFoundError" in report_text
    assert report.missing("core") == ()
    assert [package.distribution for package in report.missing("ml")] == ["torch"]


def _fake_torch_module(cuda_available: bool) -> types.ModuleType:
    module = types.ModuleType("torch")
    module.__version__ = "2.7.0"

    class FakeCuda:
        @staticmethod
        def is_available() -> bool:
            return cuda_available

        @staticmethod
        def device_count() -> int:
            return 1 if cuda_available else 0

        @staticmethod
        def get_device_properties(index: int) -> Any:
            if index != 0:
                raise IndexError(index)
            return types.SimpleNamespace(
                name="Fake GPU",
                major=8,
                minor=6,
                total_memory=16 * 1024**3,
            )

    module.cuda = FakeCuda()
    return module


def test_torch_status_detects_fake_cuda_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "torch", _fake_torch_module(cuda_available=True))

    status = _torch_status()

    assert status.installed is True
    assert status.version == "2.7.0"
    assert status.cuda_available is True
    assert status.cuda_device_count == 1
    assert status.devices == ("Fake GPU (compute capability 8.6, 16.0 GiB)",)


def test_torch_status_handles_cpu_only_torch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "torch", _fake_torch_module(cuda_available=False))

    status = _torch_status()

    assert status.installed is True
    assert status.cuda_available is False
    assert status.cuda_device_count == 0
    assert status.devices == ()


def test_format_report_handles_cuda_device() -> None:
    report = _minimal_report(
        TorchStatus(
            installed=True,
            version="2.7.0",
            cuda_available=True,
            cuda_device_count=1,
            devices=("Example GPU (compute capability 8.6, 16.0 GiB)",),
        )
    )

    report_text = format_environment_report(report)

    assert "Installed: yes (2.7.0)" in report_text
    assert "CUDA available: yes" in report_text
    assert "[0] Example GPU" in report_text


def test_default_config_loads_and_resolves_paths() -> None:
    config = load_config(use_env=False)

    assert config.project.name == "planetary-plume-ai"
    assert config.project.random_seed == 42
    assert config.paths.data_dir == (DEFAULT_PROJECT_ROOT / "data").resolve()
    assert config.paths.outputs_dir == (DEFAULT_PROJECT_ROOT / "outputs").resolve()
    assert config.dataset.root is None
    assert ".png" in config.dataset.image_extensions
    assert config.dataset.dimension_sample_size > 0


def test_config_resolves_relative_paths_against_project_root(tmp_path: Path) -> None:
    project_root = tmp_path / "repository"
    project_root.mkdir()
    config_path = _write_config(tmp_path, VALID_CONFIG)

    config = load_config(config_path, project_root=project_root, use_env=False)

    assert config.paths.data_dir == (project_root / "workspace" / "data").resolve()
    assert config.paths.outputs_dir == (
        project_root / "workspace" / "outputs"
    ).resolve()
    assert config.dataset.image_extensions == (".png", ".jpg")
    assert config.dataset.dimension_sample_size == 10
    assert config.source_path == config_path.resolve()


def test_config_environment_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "repository"
    project_root.mkdir()
    config_path = _write_config(tmp_path, VALID_CONFIG)

    monkeypatch.setenv("PLUME_DATA_DIR", "cloud/data")
    monkeypatch.setenv("PLUME_OUTPUT_DIR", "cloud/outputs")
    monkeypatch.setenv("PLUME_DATASET_ROOT", "cloud/raw")

    config = load_config(config_path, project_root=project_root)

    assert config.paths.data_dir == (project_root / "cloud" / "data").resolve()
    assert config.paths.outputs_dir == (
        project_root / "cloud" / "outputs"
    ).resolve()
    assert config.dataset.root == (project_root / "cloud" / "raw").resolve()


def test_config_rejects_missing_section(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        """\
        project:
          name: incomplete
          random_seed: 1
        paths:
          data_dir: data
          outputs_dir: outputs
        """,
    )

    with pytest.raises(ConfigError, match="dataset"):
        load_config(config_path, use_env=False)


def test_config_rejects_unknown_key(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        VALID_CONFIG.replace("  root: null", "  root: null\n  label_column: guess"),
    )

    with pytest.raises(ConfigError, match="Unknown key"):
        load_config(config_path, use_env=False)


def test_config_rejects_invalid_extension(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        VALID_CONFIG.replace("    - .png", "    - png"),
    )

    with pytest.raises(ConfigError, match="dot"):
        load_config(config_path, use_env=False)


def test_config_rejects_boolean_seed(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        VALID_CONFIG.replace("random_seed: 7", "random_seed: true"),
    )

    with pytest.raises(ConfigError, match="non-negative integer"):
        load_config(config_path, use_env=False)


def test_config_rejects_invalid_yaml(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, "project: [unterminated")

    with pytest.raises(ConfigError, match="Invalid YAML"):
        load_config(config_path, use_env=False)


def test_config_rejects_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.yaml"

    with pytest.raises(ConfigError, match="not found"):
        load_config(missing, use_env=False)
