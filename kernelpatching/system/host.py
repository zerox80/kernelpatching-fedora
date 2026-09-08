"""System host support for Fedora kernel builds."""
from __future__ import annotations

from kernelpatching.constants import GIB
from kernelpatching.constants import MIN_FEDORA
from kernelpatching.errors import Error
from pathlib import Path
import os
import platform
import re
import shutil
import sys


def fedora_version() -> int:
    info = platform.freedesktop_os_release()
    version = info.get("VERSION_ID", "")
    if info.get("ID") != "fedora" or not re.fullmatch(r"[0-9]+", version):
        raise Error("A numbered Fedora release is required; Rawhide and Fedora derivatives are not supported.")
    if int(version) < MIN_FEDORA:
        raise Error(f"Fedora {MIN_FEDORA} or newer is required.")
    if info.get("RELEASE_TYPE", "stable") == "development":
        raise Error("Fedora development branches and Rawhide are not supported as stable targets.")
    return int(version)



def default_work_dir() -> Path:
    root = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    if not root.is_absolute():
        raise Error("XDG_STATE_HOME must be an absolute path.")
    return root / "fedora-vanilla-kernel" / f"fedora-{fedora_version()}-{platform.machine()}"



def host_check() -> None:
    if sys.version_info < (3, 12):
        raise Error("Python 3.12 or newer is required.")
    if os.geteuid() == 0:
        raise Error("Run as a regular user. Do not put sudo before python3.")
    fedora_version()
    if Path("/run/ostree-booted").exists():
        raise Error("Atomic/Silverblue/Kinoite systems managed by rpm-ostree are not supported.")
    if platform.machine() not in {"x86_64", "aarch64"}:
        raise Error("Supported architectures: x86_64 and aarch64 (native builds).")
    if not shutil.which("rpm"):
        raise Error("rpm is missing.")



def job_count() -> int:
    cpus = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 2)
    try:
        memory = Path("/proc/meminfo").read_text()
        available = int(re.search(r"^MemAvailable:\s+(\d+)", memory, re.M)[1]) * 1024
    except (OSError, TypeError):
        available = 4 * GIB
    return max(1, min(max(1, cpus - 1), available // (3 * GIB)))
