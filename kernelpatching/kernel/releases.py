"""Kernel releases support for Fedora kernel builds."""
from __future__ import annotations
import urllib.request

from kernelpatching.constants import VERSION_RE
from kernelpatching.errors import Error
import json


def validate_version(version: str) -> str:
    if not VERSION_RE.fullmatch(version):
        raise Error("Use a stable kernel version such as 7.2.4; release candidates and paths are not accepted.")
    if tuple(map(int, version.split(".")[:2])) < (6, 12):
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
