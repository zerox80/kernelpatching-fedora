"""System boot support for Fedora kernel builds."""
from __future__ import annotations

from kernelpatching.system.process import run
from pathlib import Path
import shutil


def secure_boot() -> str:
    if not Path("/sys/firmware/efi").is_dir():
        return "not-uefi"
    variable = Path("/sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c")
    try:
        data = variable.read_bytes()
        if len(data) == 5 and data[4] in (0, 1):
            return "enabled" if data[4] else "disabled"
    except OSError:
        pass
    if shutil.which("mokutil"):
        result = run(["mokutil", "--sb-state"], check=False)
        if result.returncode == 0:
            if "SecureBoot enabled" in result.stdout:
                return "enabled"
            if "SecureBoot disabled" in result.stdout:
                return "disabled"
    return "unknown"
