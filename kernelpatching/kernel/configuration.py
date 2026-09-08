"""Kernel configuration support for Fedora kernel builds."""
from __future__ import annotations

from kernelpatching.constants import RELEASE_RE
from kernelpatching.errors import Error
from kernelpatching.storage.files import write_json
from kernelpatching.system.console import say
from kernelpatching.system.process import logged
from kernelpatching.system.process import run
from pathlib import Path
import difflib
import re


def config_values(text: str) -> dict[str, str]:
    values = {}
    for line in text.splitlines():
        match = re.fullmatch(r"(CONFIG_[A-Za-z0-9_]+)=(.*)", line)
        disabled = re.fullmatch(r"# (CONFIG_[A-Za-z0-9_]+) is not set", line)
        if match:
            values[match[1]] = match[2]
        elif disabled:
            values[disabled[1]] = "n"
    return values



def configure(tree: Path, directory: Path, config: bytes, suffix: str, jobs: int) -> tuple[str, list[str]]:
    config_file = tree / ".config"
    config_file.write_bytes(config)
    (directory / "fedora-original.config").write_bytes(config)
    make = ["make", f"-j{jobs}", "CC=gcc", "HOSTCC=gcc", "KBUILD_BUILD_VERSION=1"]
    old = config_values(config.decode())
    if old.get("CONFIG_RUST") == "y":
        logged([*make, "rustavailable"], tree, directory / "configure.log")
    changes = ["--set-str", "LOCALVERSION", suffix, "--disable", "LOCALVERSION_AUTO",
               "--set-str", "SYSTEM_TRUSTED_KEYS", "",
               "--set-str", "SYSTEM_REVOCATION_KEYS", "",
               "--set-str", "MODULE_SIG_KEY", "certs/signing_key.pem",
               "--set-str", "BUILD_SALT", suffix.lstrip("-")]
    run([tree / "scripts/config", "--file", config_file, *changes], cwd=tree)
    (directory / "fedora-adapted.config").write_bytes(config_file.read_bytes())
    logged([*make, "listnewconfig"], tree, directory / "new-options.log")
    logged([*make, "olddefconfig"], tree, directory / "configure.log")
    current_text = config_file.read_text(encoding="utf-8")
    current = config_values(current_text)
    (directory / "final.config").write_text(current_text, encoding="utf-8")
    (directory / "config.diff").write_text("".join(difflib.unified_diff(
        config.decode().splitlines(True), current_text.splitlines(True),
        fromfile="Fedora baseline", tofile="Vanilla configuration")), encoding="utf-8")
    records = [{"option": key, "before": old.get(key), "after": current.get(key)}
               for key in sorted(old.keys() | current.keys()) if old.get(key) != current.get(key)]
    write_json(directory / "config-changes.json", records)
    required = {"CONFIG_MODULES", "CONFIG_BLK_DEV_INITRD", "CONFIG_DEVTMPFS"}
    required |= {k for k in ("CONFIG_RUST", "CONFIG_DEBUG_INFO_BTF", "CONFIG_MODULE_SIG",
                            "CONFIG_MODULE_SIG_ALL", "CONFIG_SECURITY_SELINUX",
                            "CONFIG_EFI", "CONFIG_EFI_STUB") if old.get(k) == "y"}
    lost = sorted(key for key in required if current.get(key) != "y")
    if lost:
        raise Error("Required configuration options were lost: " + ", ".join(lost)
                    + f". Review {directory / 'config.diff'}.")
    release = run([*make, "-s", "kernelrelease"], cwd=tree).stdout.strip()
    if not RELEASE_RE.fullmatch(release) or not release.endswith(suffix) or len(release) > 64:
        raise Error(f"Unexpected kernel release: {release!r}")
    lost_count = sum(old.get(x["option"]) in {"m", "y"} and x["after"] not in {"m", "y"}
                     for x in records)
    say(f"Configuration: {len(records)} changes; {lost_count} previously enabled options were lost.\n"
        f"Details: {directory / 'config.diff'}")
    return release, make
