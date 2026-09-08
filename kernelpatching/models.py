"""Models support for Fedora kernel builds."""
from __future__ import annotations

import dataclasses


@dataclasses.dataclass
class Baseline:
    release: str
    package: str
    architecture: str
    path: str
    sha256: str
    signature: str
    fedora_version: int = 0  # Zero allows reading snapshots written by version 1.
    source_rpm: str = ""
