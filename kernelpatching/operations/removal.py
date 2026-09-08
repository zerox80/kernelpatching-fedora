"""Operations removal support for Fedora kernel builds."""
from __future__ import annotations

from kernelpatching.system.offline import assert_no_pending_offline_updates

from kernelpatching.constants import RELEASE_RE
from kernelpatching.errors import Error
from kernelpatching.kernel.baseline import official_kernels
from kernelpatching.operations.inventory import kernel_inventory
from kernelpatching.operations.inventory import read_boot_default
from kernelpatching.operations.selection import select_kernel
from kernelpatching.system.console import say
from kernelpatching.system.process import privileged
from kernelpatching.system.process import run
from pathlib import Path
import platform
import shlex
import shutil


def removal_plan(release: str, entries: list[dict], official: list[dict],
                 running: str, default: str) -> list[str]:
    if not RELEASE_RE.fullmatch(release):
        raise Error("Specify an exact kernel release; wildcards and package names are not accepted.")
    selected = [entry for entry in entries if entry["release"] == release]
    if len(selected) != 1:
        raise Error("The kernel was not found uniquely. Run 'kernels' first.")
    if release == running:
        raise Error("The running kernel cannot be removed. Boot another kernel first.")
    if selected[0]["image"] == default:
        raise Error("The boot default cannot be removed. Select a different default first.")
    if not default.startswith("/boot/vmlinuz-"):
        raise Error("The boot default could not be determined reliably; removal is blocked.")
    if not any(p["release"] != release and Path(f"/boot/vmlinuz-{p['release']}").is_file()
               for p in official):
        raise Error("An official kernel for the current Fedora release must remain as a fallback.")
    return selected[0]["packages"]



def remove_kernel(args) -> None:
    entries = kernel_inventory()
    release = args.release
    if release is None:
        release = select_kernel(entries, platform.release(), read_boot_default())
        if release is None:
            return
        # Keep the exact selected release if installed packages changed during the menu.
        entries = kernel_inventory()
    # Reject invalid selections before using sudo to inspect the bootloader.
    if release == platform.release():
        raise Error("The running kernel cannot be removed. Boot another kernel first.")
    if not any(entry["release"] == release for entry in entries):
        raise Error("Kernel not found. Run 'kernels' first.")
    for program in ("sudo", "dnf", "grubby"):
        if not shutil.which(program):
            raise Error(f"A removal prerequisite is missing: {program}")
    assert_no_pending_offline_updates()
    official = official_kernels()
    default = run(["sudo", "--", "grubby", "--default-kernel"]).stdout.strip()
    if not Path(default).is_file():
        raise Error("The previous default kernel is missing; kernel removal is blocked.")
    packages = removal_plan(release, entries, official, platform.release(), default)
    command = ["dnf", "--setopt=clean_requirements_on_remove=False",
               "--setopt=protect_running_kernel=True", "--setopt=assumeyes=False",
               "--setopt=defaultyes=False", "remove", *packages]
    say(f"Selected kernel: {release}\n"
        f"Running kernel: {platform.release()}\n"
        f"Component packages for the selected version ({len(packages)}):\n"
        + "\n".join("  " + package for package in packages))
    say("Other installed kernel versions to keep:\n" + "\n".join(
        "  " + entry["release"] for entry in entries if entry["release"] != release))
    if args.dry_run:
        say("Preview only; no packages removed. DNF resolves dependencies during the actual removal command.\n"
            + shlex.join(["sudo", "--", *command]))
        return
    try:
        privileged(command)
        remaining = {entry["release"] for entry in kernel_inventory()}
        if release in remaining:
            raise Error("The selected kernel is still installed; inspect the DNF output.")
        for entry in entries:
            if entry["release"] != release and entry["release"] not in remaining:
                raise Error("Another kernel is missing after the transaction; inspect the DNF output.")
    finally:
        # Restore the boot default even if a package scriptlet partially fails.
        privileged(["grubby", f"--set-default={default}"])
        actual = run(["sudo", "--", "grubby", "--default-kernel"]).stdout.strip()
        if actual != default:
            raise Error(f"Check the previous boot default: {default}")
    say(f"Removed: {release}\nBuild files and configuration snapshots have been retained.")
