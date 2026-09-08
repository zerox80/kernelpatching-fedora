"""System rpm support for Fedora kernel builds."""
from __future__ import annotations

from kernelpatching.constants import RPM_HASHES
from kernelpatching.errors import Error
from kernelpatching.system.process import run
from pathlib import Path
import hashlib


def rpm_file_digests(package: str) -> tuple[str, dict[str, str]]:
    query = "%{FILEDIGESTALGO}\n[%{FILENAMES}\t%{FILEDIGESTS}\n]"
    lines = run(["rpm", "-q", package, "--qf", query]).stdout.splitlines()
    if not lines or lines[0] not in RPM_HASHES:
        raise Error(f"No supported strong RPM file digest is available for {package}.")
    return RPM_HASHES[lines[0]], dict(line.split("\t", 1) for line in lines[1:] if "\t" in line)



def checked_rpm_file(path: Path, algorithm: str, expected: str) -> bytes:
    data = path.read_bytes()
    if not expected or hashlib.new(algorithm, data).hexdigest() != expected.lower():
        raise Error(f"File does not match its RPM file digest: {path}")
    return data



def missing_packages(packages: list[str]) -> list[str]:
    # Accept renamed packages that provide the same RPM capability.
    return [name for name in packages if run(["rpm", "-q", "--whatprovides", name], check=False).returncode]
