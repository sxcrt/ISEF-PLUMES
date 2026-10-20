"""Environmental and dependency diagnostics for reproducible development.

PyTorch is treated as optional during the foundation phase. A missing PyTorch
installation, or one without CUDA support, is reported rather than raised so
that CPU-only development and testing always work.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import platform
import sys
from dataclasses import dataclass

# (distribution name, import name) pairs. Distribution names are what pip
# installs; import names are what Python imports.
CORE_PACKAGES: tuple[tuple[str, str], ...] = (
    ("PyYAML", "yaml"),
    ("numpy", "numpy"),
    ("Pillow", "PIL"),
)
ML_PACKAGES: tuple[tuple[str, str], ...] = (("torch", "torch"),)
DEV_PACKAGES: tuple[tuple[str, str], ...] = (("pytest", "pytest"),)

_GROUP_LABELS = {
    "core": "Core",
    "ml": "Machine learning",
    "dev": "Development",
}


@dataclass(frozen=True)
class PackageStatus:
    """Installation state of one Python distribution."""

    distribution: str
    import_name: str
    group: str
    installed: bool
    version: str | None


@dataclass(frozen=True)
class TorchStatus:
    """PyTorch import and CUDA status."""

    installed: bool
    version: str | None = None
    cuda_available: bool = False
    cuda_device_count: int = 0
    devices: tuple[str, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class EnvironmentReport:
    """Complete diagnostic snapshot for the current interpreter."""

    python_version: str
    python_executable: str
    platform: str
    system: str
    machine: str
    packages: tuple[PackageStatus, ...]
    torch: TorchStatus

    def missing(self, group: str) -> tuple[PackageStatus, ...]:
        """Return missing packages in one group (``core``, ``ml``, or ``dev``)."""

        return tuple(
            package
            for package in self.packages
            if package.group == group and not package.installed
        )


def _package_status(distribution: str, import_name: str, group: str) -> PackageStatus:
    version: str | None = None
    installed = False

    try:
        version = importlib.metadata.version(distribution)
        installed = True
    except importlib.metadata.PackageNotFoundError:
        # A module can be importable without distribution metadata (for
        # example, when it is vendored into another environment).
        try:
            if importlib.util.find_spec(import_name) is not None:
                installed = True
                version = "unknown (no distribution metadata)"
        except (ImportError, AttributeError, ValueError):
            installed = False

    return PackageStatus(
        distribution=distribution,
        import_name=import_name,
        group=group,
        installed=installed,
        version=version,
    )


def _torch_status() -> TorchStatus:
    try:
        import torch
    except Exception as exc:  # ImportError or a broken native library load.
        return TorchStatus(
            installed=False,
            error=f"{type(exc).__name__}: {exc}",
        )

    version = getattr(torch, "__version__", "unknown")

    try:
        cuda_available = bool(torch.cuda.is_available())
    except Exception as exc:
        return TorchStatus(
            installed=True,
            version=version,
            error=f"CUDA check failed: {type(exc).__name__}: {exc}",
        )

    device_count = 0
    devices: list[str] = []
    if cuda_available:
        try:
            device_count = int(torch.cuda.device_count())
        except Exception as exc:
            devices.append(f"Device count check failed: {type(exc).__name__}: {exc}")

        for index in range(device_count):
            try:
                props = torch.cuda.get_device_properties(index)
                memory_gib = props.total_memory / (1024**3)
                devices.append(
                    f"{props.name} (compute capability "
                    f"{props.major}.{props.minor}, {memory_gib:.1f} GiB)"
                )
            except Exception as exc:
                devices.append(
                    f"Device {index}: unavailable ({type(exc).__name__}: {exc})"
                )

    return TorchStatus(
        installed=True,
        version=version,
        cuda_available=cuda_available,
        cuda_device_count=device_count,
        devices=tuple(devices),
    )


def collect_environment() -> EnvironmentReport:
    """Collect Python, platform, package, and PyTorch information."""

    packages = tuple(
        _package_status(distribution, import_name, "core")
        for distribution, import_name in CORE_PACKAGES
    ) + tuple(
        _package_status(distribution, import_name, "ml")
        for distribution, import_name in ML_PACKAGES
    ) + tuple(
        _package_status(distribution, import_name, "dev")
        for distribution, import_name in DEV_PACKAGES
    )

    return EnvironmentReport(
        python_version=sys.version.split()[0],
        python_executable=sys.executable,
        platform=platform.platform(),
        system=platform.system(),
        machine=platform.machine(),
        packages=packages,
        torch=_torch_status(),
    )


def _format_package(package: PackageStatus) -> str:
    if not package.installed:
        return f"  [MISSING] {package.distribution}"
    return f"  [OK]      {package.distribution} {package.version}"


def format_environment_report(report: EnvironmentReport) -> str:
    """Render a human-readable diagnostic report."""

    lines = [
        "Environment diagnostic",
        "======================",
        f"Python: {report.python_version}",
        f"Executable: {report.python_executable}",
        f"Platform: {report.platform}",
        f"System: {report.system}",
        f"Machine: {report.machine}",
        "",
        "Installed packages",
        "------------------",
    ]

    for group in ("core", "ml", "dev"):
        label = _GROUP_LABELS[group]
        lines.append(f"{label}:")
        lines.extend(
            _format_package(package)
            for package in report.packages
            if package.group == group
        )

    lines.extend(["", "PyTorch and CUDA", "-----------------"])
    torch = report.torch

    if not torch.installed:
        lines.append("  Installed: no")
        if torch.error:
            lines.append(f"  Import error: {torch.error}")
        lines.append(
            "  PyTorch is not installed. This is acceptable during the "
            "foundation phase; CPU-only development is unaffected."
        )
    else:
        lines.append(f"  Installed: yes ({torch.version})")
        lines.append(f"  CUDA available: {'yes' if torch.cuda_available else 'no'}")
        if torch.error:
            lines.append(f"  Error: {torch.error}")
        if torch.cuda_available:
            lines.append(f"  CUDA device count: {torch.cuda_device_count}")
            for index, device in enumerate(torch.devices):
                lines.append(f"    [{index}] {device}")
        else:
            lines.append(
                "  No CUDA GPU detected. The project must continue to run on CPU."
            )

    return "\n".join(lines)
