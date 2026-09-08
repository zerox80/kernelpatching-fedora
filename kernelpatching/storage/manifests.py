"""Storage manifests support for Fedora kernel builds."""
from __future__ import annotations

from kernelpatching.constants import RELEASE_RE
from kernelpatching.errors import Error
from kernelpatching.system.host import fedora_version
import platform
import re


def build_target() -> dict:
    return {"fedora_version": fedora_version(), "architecture": platform.machine()}



def validate_target(manifest: dict) -> None:
    release = manifest.get("kernel_release", "")
    if not isinstance(release, str) or not RELEASE_RE.fullmatch(release):
        raise Error("Invalid kernel release in the manifest.")
    if manifest.get("schema", 1) == 1:
        if not re.search(r"-vanilla44\.[0-9]+$", release):
            raise Error("Invalid kernel release in the legacy manifest.")
        target = {"fedora_version": 44, "architecture": manifest.get("baseline", {}).get(
            "architecture", platform.machine())}
    elif manifest.get("schema") == 2:
        target = manifest.get("target")
        if not isinstance(target, dict) or not isinstance(target.get("fedora_version"), int):
            raise Error("The build manifest does not specify a Fedora target.")
        marker = rf"-vanilla\.fc{target['fedora_version']}\.[0-9]+$"
        if not re.search(marker, release):
            raise Error("The kernel release does not match the Fedora target.")
    else:
        raise Error("Unknown manifest version; update the application.")
    if target != build_target():
        raise Error(f"Build target {target} does not match this system {build_target()}. "
                    "Rebuild the kernel after the Fedora upgrade.")
