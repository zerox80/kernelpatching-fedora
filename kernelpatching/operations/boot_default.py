"""Select and verify the default installed kernel through Fedora's grubby tool."""
from __future__ import annotations

from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess

from kernelpatching.constants import RELEASE_RE
from kernelpatching.errors import Error
from kernelpatching.operations.inventory import kernel_inventory, read_boot_default
from kernelpatching.operations.selection import select_kernel
from kernelpatching.system.boot import secure_boot
from kernelpatching.system.console import say
from kernelpatching.system.process import privileged, run


def resolve_tuned_initrds(names: list[str]) -> list[str]:
    """Resolve TuneD's optional BLS overlay from the same environment as grubby."""
    tokens = {"$tuned_initrd", "${tuned_initrd}"}
    if not tokens.intersection(names):
        return names
    # TuneD adds this token even when no overlay is configured. Do not expand
    # shell variables: GRUB's environment, not the process environment, owns it.
    output = run(["sudo", "--", "grub2-editenv", "/boot/grub2/grubenv", "list"]).stdout
    values = [line.partition("=")[2] for line in output.splitlines()
              if line.partition("=")[0] == "tuned_initrd"]
    if len(values) > 1:
        raise Error("Unrecognized GRUB environment: duplicate tuned_initrd values.")
    try:
        overlays = shlex.split(values[0]) if values else []
    except ValueError as error:
        raise Error("Unrecognized GRUB tuned_initrd value.") from error
    return [path for name in names for path in (overlays if name in tokens else [name])]


def validate_boot_entry(image: Path) -> None:
    """Check the exact GRUB entry and each initramfs it references."""
    if image.parent != Path("/boot") or not image.name.startswith("vmlinuz-"):
        raise Error(f"Unsupported boot kernel path: {image}")
    if not image.is_file() or image.stat().st_size == 0:
        raise Error(f"The kernel image is missing or empty: {image}")
    info = run(["sudo", "--", "grubby", f"--info={image}"]).stdout
    entries = []
    for block in re.split(r"(?m)(?=^index=)", info):
        entry = {}
        for line in block.splitlines():
            key, separator, value = line.partition("=")
            if separator and key in {"kernel", "initrd"}:
                values = shlex.split(value)
                if key in entry or len(values) != 1:
                    raise Error("Unrecognized GRUB entry format; no default was changed.")
                entry[key] = values[0]
        if entry.get("kernel") == str(image):
            entries.append(entry)
    if len(entries) != 1:
        raise Error(f"No unique GRUB entry was found for {image}.")
    initrds = []
    for name in resolve_tuned_initrds(shlex.split(entries[0].get("initrd", ""))):
        path = Path(name)
        if "$" in name or not path.is_absolute() or ".." in path.parts:
            raise Error(f"Unrecognized GRUB initramfs path: {name}")
        # Fedora's BLS grubby prefixes only the first initrd with /boot;
        # additional entries can still be relative to the boot filesystem root.
        if not path.is_relative_to(image.parent):
            path = image.parent / name.lstrip("/")
        initrds.append(path)
    expected = image.with_name("initramfs-" + image.name.removeprefix("vmlinuz-") + ".img")
    if expected not in initrds:
        raise Error(f"The GRUB entry does not reference the matching initramfs: {expected}")
    for path in initrds:
        if not path.is_file() or path.stat().st_size == 0:
            raise Error(f"A GRUB initramfs file is missing or empty: {path}")


def set_boot_default(args) -> None:
    entries = kernel_inventory()
    release = args.release
    if release is None:
        release = select_kernel(entries, platform.release(), read_boot_default(), action="set-default")
        if release is None:
            return
        entries = kernel_inventory()
    if not RELEASE_RE.fullmatch(release):
        raise Error("Specify an exact installed kernel release; wildcards and paths are not accepted.")
    selected = [entry for entry in entries if entry["release"] == release]
    if len(selected) != 1:
        raise Error("The kernel was not found uniquely. Run 'kernels' or 'set-default' again.")
    if selected[0]["kind"] != "Fedora kernel-core":
        state = secure_boot()
        if state not in {"disabled", "not-uefi"}:
            raise Error(f"Secure Boot is {state}. Selecting a custom kernel requires disabled "
                        "Secure Boot; custom EFI/MOK signing is not implemented.")
    for program in ("sudo", "grubby"):
        if not shutil.which(program):
            raise Error(f"A boot selection prerequisite is missing: {program}")
    image = Path(selected[0]["image"])
    validate_boot_entry(image)
    previous = run(["sudo", "--", "grubby", "--default-kernel"]).stdout.strip()
    if previous == str(image):
        say(f"Already the boot default: {release}\nNo boot configuration was changed.")
        return
    # Verify a usable previous entry before relying on it for failure recovery.
    validate_boot_entry(Path(previous))
    say(f"Current boot default: {previous}\nSelected boot default: {image}")
    command = ["grubby", f"--set-default={image}"]
    if args.dry_run:
        say("Preview only; no boot configuration changed.\n" + shlex.join(["sudo", "--", *command]))
        return
    try:
        privileged(command)
        actual = run(["sudo", "--", "grubby", "--default-kernel"]).stdout.strip()
        if actual != str(image):
            raise Error(f"The boot default did not match the selected kernel: {actual}")
    except (Error, OSError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        try:
            privileged(["grubby", f"--set-default={previous}"])
            restored = run(["sudo", "--", "grubby", "--default-kernel"]).stdout.strip()
            if restored != previous:
                raise Error(f"The boot default after recovery was {restored}")
        except (Error, OSError, subprocess.SubprocessError) as restore_error:
            raise Error(f"Changing the boot default failed: {error}\n"
                        f"Restoring the previous default also failed: {restore_error}\n"
                        "Restore it manually with: " + shlex.join(
                            ["sudo", "grubby", f"--set-default={previous}"])) from error
        say(f"The previous boot default was restored: {previous}")
        raise
    say(f"Boot default changed to: {release}\nIt will be selected on future boots. No reboot was started.")
