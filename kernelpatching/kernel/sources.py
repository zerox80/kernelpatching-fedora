"""Kernel sources support for Fedora kernel builds."""
from __future__ import annotations

from kernelpatching.errors import Error
from pathlib import Path
from pathlib import PurePosixPath
import tarfile


def extract_sources(archive: Path, directory: Path, version: str) -> Path:
    expected = f"linux-{version}"
    directory.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:") as source:
        for member in source.getmembers():
            parts = PurePosixPath(member.name).parts
            if not parts or parts[0] != expected or ".." in parts or member.name.startswith("/"):
                raise Error(f"Unexpected path in the source archive: {member.name}")
        # The Python data filter rejects escaping links and device files.
        source.extractall(directory, filter="data")
    tree = directory / expected
    if not (tree / "Makefile").is_file() or not (tree / "scripts/config").is_file():
        raise Error("The kernel source archive is incomplete.")
    return tree
