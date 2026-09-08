"""Operations install support for Fedora kernel builds."""
from __future__ import annotations

from kernelpatching.system.offline import assert_no_pending_offline_updates

from kernelpatching.constants import PACKAGE_NAME
from kernelpatching.errors import Error
from kernelpatching.kernel.baseline import official_kernels
from kernelpatching.packaging.rpms import validate_packages
from kernelpatching.storage.files import write_json
from kernelpatching.storage.manifests import validate_target
from kernelpatching.system.boot import secure_boot
from kernelpatching.system.console import say
from kernelpatching.system.process import privileged
from kernelpatching.system.process import run
from pathlib import Path
import json
import shutil


def install_command(packages: list[Path]) -> list[str]:
    return ["dnf", "--setopt=installonly_limit=0",
            f"--setopt=installonlypkgs=kernel,kernel-devel,{PACKAGE_NAME},{PACKAGE_NAME}-devel",
            "--setopt=install_weak_deps=False", "--setopt=localpkg_gpgcheck=0",
            "--setopt=assumeyes=False", "--setopt=defaultyes=False", "install",
            *map(str, packages)]



def install(args) -> None:
    directory = args.directory.expanduser().resolve()
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "built" or manifest.get("schema") not in {1, 2}:
        raise Error("This directory does not contain a successfully completed build.")
    validate_target(manifest)
    packages = validate_packages(directory, manifest)
    state = secure_boot()
    if state not in {"disabled", "not-uefi"}:
        raise Error(f"Secure Boot is {state}. Installation requires disabled "
                    "Secure Boot; custom EFI/MOK signing is not implemented.")
    for program in ("sudo", "dnf", "grubby", "dracut", "kernel-install", "depmod"):
        if not shutil.which(program):
            raise Error(f"An installation prerequisite is missing: {program}")
    release = manifest["kernel_release"]
    image = Path(f"/boot/vmlinuz-{release}")
    if image.exists() or Path(f"/lib/modules/{release}").exists():
        raise Error(f"{release} already exists. Existing kernel installations will not be overwritten.")
    if shutil.disk_usage("/boot").free < 512 * 1024 ** 2:
        raise Error("Less than 512 MiB is available in /boot; installation is blocked.")
    before = official_kernels()
    if not any(Path(f"/boot/vmlinuz-{p['release']}").is_file() for p in before):
        raise Error("No official Fedora fallback kernel is present in /boot.")
    assert_no_pending_offline_updates()
    previous = run(["sudo", "--", "grubby", "--default-kernel"]).stdout.strip()
    if not previous.startswith("/boot/vmlinuz-") or not Path(previous).is_file():
        raise Error("The previous GRUB default kernel could not be determined reliably.")
    previous_info = run(["sudo", "--", "grubby", f"--info={previous}"]).stdout
    if Path(previous).name not in previous_info:
        raise Error("The previous default kernel does not have an available GRUB entry.")
    write_json(directory / "installation.json", {"previous_default": previous,
               "kernel_release": release, "official_kernels_before": before,
               "status": "started"})
    success = False
    try:
        # DNF displays the resolved transaction and asks for confirmation.
        privileged(install_command(packages))
        for package in manifest["packages"]:
            run(["rpm", "-q", package["nevra"]])
        after = {p["package"] for p in official_kernels()}
        if any(p["package"] not in after for p in before):
            raise Error("A previously installed official kernel package is missing after installation.")
        privileged(["depmod", "-a", release])
        initramfs = Path(f"/boot/initramfs-{release}.img")
        # Run this explicitly after RPM scriptlets so failures are visible.
        privileged(["dracut", "--force", "--kver", release, initramfs])
        if not image.is_file() or not initramfs.is_file() or initramfs.stat().st_size == 0:
            raise Error("The kernel image or initramfs is missing after installation.")
        info = run(["sudo", "--", "grubby", f"--info={image}"]).stdout
        if f"vmlinuz-{release}" not in info or f"initramfs-{release}.img" not in info:
            raise Error("The GRUB entry is missing or points to the wrong initramfs.")
        success = True
    finally:
        # Restore the previous default even after DNF, Dracut, or scriptlet failures.
        desired = str(image) if success and args.make_default else previous
        privileged(["grubby", f"--set-default={desired}"])
        actual = run(["sudo", "--", "grubby", "--default-kernel"]).stdout.strip()
        if actual != desired:
            raise Error(f"The GRUB default was not applied. Expected: {desired}; received: {actual}")
        write_json(directory / "installation.json", {"previous_default": previous,
                   "current_default": actual, "kernel_release": release,
                   "status": "installed" if success else "failed; inspect system before retry"})
    say(f"Installed: {release}\nDefault kernel: {actual}\n"
        "No automatic reboot. Select the new kernel in GRUB and test it.\n"
        "Rebuild external modules such as NVIDIA or VirtualBox first if required.")
