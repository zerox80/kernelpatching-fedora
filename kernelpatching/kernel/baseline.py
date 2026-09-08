"""Kernel baseline support for Fedora kernel builds."""
from __future__ import annotations

from kernelpatching.constants import VERSION_RE
from kernelpatching.errors import Error
from kernelpatching.models import Baseline
from kernelpatching.security.fedora_keys import fedora_signing_ids
from kernelpatching.system.console import say
from kernelpatching.system.host import fedora_version
from kernelpatching.system.process import run
from kernelpatching.system.rpm import checked_rpm_file
from kernelpatching.system.rpm import rpm_file_digests
from pathlib import Path
import hashlib
import json
import platform
import re


def official_kernels() -> list[dict[str, str]]:
    target = fedora_version()
    trusted_ids = fedora_signing_ids(target)
    tags = set(run(["rpm", "--querytags"]).stdout.splitlines())
    if "OPENPGP" in tags:
        signature_format = "[%{OPENPGP:pgpsig};]"
    else:
        known = [x for x in ("RSAHEADER", "DSAHEADER", "SIGPGP", "SIGGPG") if x in tags]
        if not known:
            raise Error("RPM does not expose a supported OpenPGP signature query format.")
        signature_format = ";".join("%{" + tag + ":pgpsig}" for tag in known)
    query = "%{NAME}|%{VERSION}|%{RELEASE}|%{ARCH}|%{VENDOR}|" + signature_format + "\n"
    rows = run(["rpm", "-q", "kernel-core", "--qf", query], check=False).stdout
    candidates = []
    for line in rows.splitlines():
        fields = line.split("|")
        if len(fields) != 6:
            continue
        name, version, release, arch, vendor, signature = fields
        if (name == "kernel-core" and VERSION_RE.fullmatch(version)
                and re.fullmatch(r"[0-9]+(?:\.[0-9]+)*\.fc" + str(target), release)
                and arch == platform.machine() and vendor == "Fedora Project"
                and trusted_ids.intersection(x.upper() for x in
                    re.findall(r"Key ID ([A-Fa-f0-9]{16})\b", signature, re.I))):
            candidates.append({"version": version, "rpm_release": release,
                               "release": f"{version}-{release}.{arch}",
                               "package": f"kernel-core-{version}-{release}.{arch}",
                               "arch": arch, "signature": signature, "fedora_version": target})
    return sorted(candidates,
                  key=lambda x: (tuple(map(int, x["version"].split("."))) +
                                 (0,) * (3 - len(x["version"].split("."))),
                                 tuple(map(int, x["rpm_release"].split(".fc")[0].split(".")))), reverse=True)



def choose_baseline(work: Path, requested: str | None = None, refresh=False) -> tuple[Baseline, bytes]:
    target = fedora_version()
    metadata = work / "baseline.json"
    snapshot = work / "fedora-base.config"
    if metadata.exists() and not refresh:
        base = Baseline(**json.loads(metadata.read_text(encoding="utf-8")))
        if not base.fedora_version:
            match = re.search(r"\.fc([0-9]+)\.", base.release)
            base.fedora_version = int(match[1]) if match else 0
        data = snapshot.read_bytes()
        if hashlib.sha256(data).hexdigest() != base.sha256:
            raise Error("The saved Fedora baseline configuration has been modified.")
        if base.fedora_version != target or base.architecture != platform.machine():
            say("The saved baseline belongs to a different Fedora release or "
                "architecture; selecting a matching official baseline.")
        elif requested and requested != base.release:
            raise Error("The saved baseline does not match. Use build --refresh-base or a different --work-dir.")
        else:
            return base, data
    candidates = official_kernels()
    if requested:
        candidates = [x for x in candidates if x["release"] == requested]
    if not candidates:
        raise Error(f"No matching official Fedora {target} kernel-core package is installed.")
    selected = candidates[0]
    # /boot/config is often an RPM %ghost copy without its own file digest.
    # Use the packaged file under /lib/modules instead.
    algorithm, files = rpm_file_digests(selected["package"])
    config_paths = {f"/lib/modules/{selected['release']}/config",
                    f"/usr/lib/modules/{selected['release']}/config"}
    for filename, digest in files.items():
        if filename not in config_paths or not digest:
            continue
        data = checked_rpm_file(Path(filename), algorithm, digest)
        source_rpm = run(["rpm", "-q", selected["package"], "--qf", "%{SOURCERPM}"]).stdout.strip()
        return Baseline(selected["release"], selected["package"], selected["arch"],
                        filename, hashlib.sha256(data).hexdigest(), selected["signature"],
                        target, source_rpm), data
    raise Error("The packaged configuration was not found in the selected kernel RPM.")
