"""Operations inventory support for Fedora kernel builds."""
from __future__ import annotations

from kernelpatching.constants import PACKAGE_NAME
from kernelpatching.constants import RELEASE_RE
from kernelpatching.errors import Error
from kernelpatching.system.console import say
from kernelpatching.system.process import run
import platform
import re
import shutil


def kernel_inventory() -> list[dict]:
    names = ["kernel", "kernel-core", "kernel-modules", "kernel-modules-core",
             "kernel-modules-extra", "kernel-devel", "kernel-devel-matched",
             PACKAGE_NAME, PACKAGE_NAME + "-devel"]
    query = "%{NAME}|%{VERSION}|%{RELEASE}|%{ARCH}|%{NEVRA}|[%{PROVIDENAME}=%{PROVIDEVERSION};]\n"
    output = run(["rpm", "-q", *names, "--qf", query], check=False).stdout
    packages = []
    for line in output.splitlines():
        parts = line.split("|")
        if len(parts) != 6 or parts[0] not in names or parts[3] != platform.machine():
            continue
        name, version, release, arch, nevra, provides = parts
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:+-]*", nevra):
            raise Error("Unexpected package identifier in the RPM database.")
        capabilities = dict(x.split("=", 1) for x in provides.split(";") if "=" in x)
        packages.append({"name": name, "version": version, "rpm_release": release,
                         "arch": arch, "nevra": nevra, "provides": capabilities})
    entries = []
    for package in packages:
        release = package["provides"].get("kernel-uname-r")
        if not release or not RELEASE_RE.fullmatch(release):
            continue
        if package["name"] == "kernel-core":
            family = {"kernel", "kernel-core", "kernel-modules", "kernel-modules-core",
                      "kernel-modules-extra", "kernel-devel", "kernel-devel-matched"}
            kind = "Fedora kernel-core"
        elif package["name"] == PACKAGE_NAME and re.search(r"-vanilla\.fc[0-9]+\.[0-9]+$", release):
            family, kind = {PACKAGE_NAME, PACKAGE_NAME + "-devel"}, "custom vanilla kernel"
        elif package["name"] == "kernel" and re.search(r"-vanilla44\.[0-9]+$", release):
            family, kind = {"kernel", "kernel-devel"}, "custom vanilla kernel (legacy v1)"
        else:
            continue
        siblings = sorted(p["nevra"] for p in packages if p["name"] in family and all(
            p[k] == package[k] for k in ("version", "rpm_release", "arch")))
        entries.append({"release": release, "kind": kind, "packages": siblings,
                        "image": f"/boot/vmlinuz-{release}"})
    return sorted(entries, key=lambda entry: [int(p) if p.isdigit() else p
                  for p in re.split(r"([0-9]+)", entry["release"])], reverse=True)



def read_boot_default() -> str:
    """Read an unprivileged display hint; removal validates it again with sudo."""
    default = ""
    if shutil.which("grubby"):
        result = run(["grubby", "--default-kernel"], check=False)
        if not result.returncode:
            default = result.stdout.strip()
    return default


def list_kernels() -> None:
    entries = kernel_inventory()
    if not entries:
        say("No supported kernel packages were found.")
        return
    default = read_boot_default()
    for entry in entries:
        marks = []
        if entry["release"] == platform.release():
            marks.append("running")
        if entry["image"] == default:
            marks.append("boot default")
        suffix = " [" + ", ".join(marks) + "]" if marks else ""
        say(f"{entry['release']} — {entry['kind']}{suffix}")
    say("Choose a kernel by number: remove (preview with: remove --dry-run)\n"
        "An exact release is also accepted: remove KERNEL_RELEASE")
