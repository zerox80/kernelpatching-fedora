"""Security fedora_keys support for Fedora kernel builds."""
from __future__ import annotations

from kernelpatching.errors import Error
from kernelpatching.system.process import run
from kernelpatching.system.rpm import checked_rpm_file
from kernelpatching.system.rpm import rpm_file_digests
from pathlib import Path
import platform
import re
import shutil
import tempfile
import time


def key_ids_from_colons(text: str) -> set[str]:
    """Read GPG key IDs directly without assumptions specific to v4 fingerprints."""
    ids = set()
    primary_ok = False
    now = int(time.time())
    for line in text.splitlines():
        fields = line.split(":")
        if len(fields) < 7 or fields[0] not in {"pub", "sub"}:
            continue
        valid = fields[1] not in {"r", "e", "d", "i"}
        valid &= not fields[6] or (fields[6].isdigit() and int(fields[6]) > now)
        if fields[0] == "pub":
            primary_ok = valid
        if primary_ok and valid and re.fullmatch(r"[A-Fa-f0-9]{16}", fields[4]):
            ids.add(fields[4].upper())
    return ids



def fedora_signing_ids(version: int) -> set[str]:
    if not shutil.which("gpg"):
        raise Error("gpg is missing. Run 'deps --install' first.")
    # The distribution-managed package is the trust anchor; do not hardcode an
    # annual signing key ID or trust keys from arbitrary repositories.
    algorithm, files = rpm_file_digests("fedora-gpg-keys")
    names = {f"RPM-GPG-KEY-fedora-{version}-primary",
             f"RPM-GPG-KEY-fedora-{version}-{platform.machine()}"}
    candidates = [Path(name) for name in files if Path(name).name in names and files[name]]
    if not candidates:
        raise Error(f"The Fedora {version} signing key is missing from fedora-gpg-keys. "
                    "Update the distribution packages; do not blindly trust an unrelated key.")
    ids = set()
    with tempfile.TemporaryDirectory(prefix="fedora-key-inspect-") as tmp:
        for path in candidates:
            checked_rpm_file(path, algorithm, files[str(path)])
            result = run(["gpg", "--no-options", "--homedir", tmp, "--batch", "--no-tty",
                          "--with-colons", "--show-keys", path])
            ids.update(key_ids_from_colons(result.stdout))
    if not ids:
        raise Error(f"No valid Fedora {version} signing keys were found.")
    return ids
