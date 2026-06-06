"""Dependency safety net.

Hermes does not install a plugin's Python dependencies, so on a fresh machine an
import of SQLAlchemy/Alembic would hard-crash before the user sees why. This
module probes a list of requirement specs at startup and, if anything is missing,
logs a clear report + registers a ``/byoh-doctor`` slash command + lets the
caller short-circuit registration — the agent keeps working without the plugin's
features instead of crashing.

(With ``byoh-bridge`` packaged, the fix is just ``pip install`` of the plugin —
its deps come transitively. This stays as the belt-and-suspenders net.)
"""

from __future__ import annotations

import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger("byoh_bridge.deps")

# Conservative spec regex; matches `pkg`, `pkg==1.2`, `pkg>=1.0,<2`, etc.
_SPEC_RE = re.compile(
    r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*"
    r"(?:\[[A-Za-z0-9_,\-]+\])?"
    r"(?:[<>=!~]=?[A-Za-z0-9_.\-+,*<>=!~]+)?"
    r"$"
)


@dataclass
class DepEntry:
    spec: str
    package: str
    specifier: Optional[str]
    installed: Optional[str] = None
    satisfied: bool = False


@dataclass
class DepStatus:
    entries: list[DepEntry] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(e.satisfied for e in self.entries)

    @property
    def missing(self) -> list[DepEntry]:
        return [e for e in self.entries if e.installed is None]

    @property
    def mismatched(self) -> list[DepEntry]:
        return [e for e in self.entries if e.installed is not None and not e.satisfied]

    def install_command(self) -> str:
        unmet = [e.spec for e in self.entries if not e.satisfied]
        specs = " ".join(f'"{s}"' for s in unmet) or "byoh-bridge"
        return f"{Path(sys.executable)} -m pip install {specs}"


# ── Public API ──────────────────────────────────────────────────────────────


def check(requirements: Iterable[str]) -> DepStatus:
    """Probe each requirement spec against the installed environment."""
    status = DepStatus()
    for raw in requirements:
        spec = raw.strip()
        if not spec or spec.startswith("#"):
            continue
        if not _SPEC_RE.match(spec):
            logger.warning("[byoh] skipping malformed dependency spec %r", spec)
            continue
        package = _package_name(spec)
        specifier = _specifier(spec) or None
        installed = _installed_version(package)
        status.entries.append(
            DepEntry(
                spec=spec,
                package=package,
                specifier=specifier,
                installed=installed,
                satisfied=installed is not None and _satisfies(installed, specifier),
            )
        )
    return status


def render_report(app_name: str, status: DepStatus) -> str:
    lines: list[str] = []
    if status.ok:
        lines.append(f"✓ {app_name}: all dependencies satisfied")
    else:
        lines.append(f"✗ {app_name}: missing or out-of-range dependencies")
    for e in status.entries:
        marker = "✓" if e.satisfied else "✗"
        lines.append(
            f"   {marker} {e.package:<16} {e.installed or '(not installed)':<12} (required: {e.specifier or '(any)'})"
        )
    if not status.ok:
        lines += ["", "To fix:", f"  {status.install_command()}", "", "Then restart Hermes."]
    return "\n".join(lines)


def install_help_command(ctx, app_name: str, requirements: Iterable[str]) -> None:
    """Register ``/byoh-doctor`` so the user can see dep status in any chat."""
    reqs = list(requirements)

    def handler(_raw_args: str) -> str:
        return render_report(app_name, check(reqs))

    try:
        ctx.register_command(
            "byoh-doctor",
            handler=handler,
            description=f"Show {app_name} dependency status + the install command.",
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("[byoh] could not register /byoh-doctor: %s", exc)


# ── Internals ─────────────────────────────────────────────────────────────


def _package_name(spec: str) -> str:
    m = re.match(r"^([A-Za-z0-9_][A-Za-z0-9_.\-]*)", spec)
    return m.group(1) if m else spec


def _specifier(spec: str) -> str:
    m = re.match(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*(?:\[[A-Za-z0-9_,\-]+\])?", spec)
    return spec[m.end():] if m else ""


def _installed_version(package: str) -> Optional[str]:
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:
        return None
    try:
        return version(package)
    except PackageNotFoundError:
        return None
    except Exception:
        return None


def _satisfies(installed: str, specifier: Optional[str]) -> bool:
    if not specifier:
        return True
    try:
        from packaging.specifiers import SpecifierSet
        from packaging.version import Version

        return Version(installed) in SpecifierSet(specifier)
    except Exception as exc:  # pragma: no cover
        logger.warning("[byoh] could not parse spec %r vs %r: %s", specifier, installed, exc)
        return True  # fail open
