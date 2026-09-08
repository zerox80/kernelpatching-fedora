"""Storage files support for Fedora kernel builds."""
from __future__ import annotations

from pathlib import Path
import hashlib
import json


def sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()



def write_json(path: Path, data) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)
