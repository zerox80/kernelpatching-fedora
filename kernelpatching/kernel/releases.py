"""Kernel releases support for Fedora kernel builds."""
from __future__ import annotations
import urllib.request

from kernelpatching.constants import VERSION_RE
from kernelpatching.constants import RC_VERSION_RE
from kernelpatching.errors import Error
import json


def validate_version(version: str, *, allow_rc: bool = False) -> str:
    is_rc = bool(RC_VERSION_RE.fullmatch(version))
    if not VERSION_RE.fullmatch(version) and not is_rc:
        raise Error("Use a kernel version such as 7.2.4 or 7.3-rc2; paths and other suffixes are not accepted.")
    if is_rc and not allow_rc:
        raise Error("Release candidates require explicit opt-in: build --version " + version + " --allow-rc")
    if tuple(map(int, version.partition("-rc")[0].split(".")[:2])) < (6, 12):
        raise Error("Kernel 6.12 or newer is required.")
    return version



def latest_version() -> str:
    request = urllib.request.Request("https://www.kernel.org/releases.json",
                                     headers={"User-Agent": "fedora-vanilla-builder/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = json.loads(response.read(2_000_000))
    version = validate_version(data["latest_stable"]["version"])
    if not any(r.get("version") == version and not r.get("iseol", False)
               and r.get("moniker") in {"stable", "mainline", "longterm"}
               for r in data["releases"]):
        raise Error("kernel.org returned inconsistent stable release metadata.")
    return version
