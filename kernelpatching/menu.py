"""Interactive command discovery and editable build presets."""
from __future__ import annotations

from pathlib import Path
import shlex
import sys

from kernelpatching.errors import Error
from kernelpatching.kernel.releases import validate_version
from kernelpatching.profiles import PROFILES, apply_profile
from kernelpatching.system.console import cli_command, say


class Cancelled(Exception):
    """Leave the menu without dispatching a command."""


def answer(prompt: str) -> str:
    try:
        value = input(prompt).strip()
    except EOFError:
        raise Cancelled from None
    if value.lower() in {"q", "quit"}:
        raise Cancelled
    return value


def choose(title: str, labels: list[str]) -> int:
    say(title)
    for number, label in enumerate(labels, 1):
        say(f"  {number}. {label}")
    while True:
        value = answer("Number (Enter or q to cancel): ")
        if not value:
            raise Cancelled
        if value in {str(number) for number in range(1, len(labels) + 1)}:
            return int(value) - 1
        say(f"Enter a number from 1 to {len(labels)}.")


def build_arguments(args) -> list[str]:
    """A reproducible command including overrides of profile booleans."""
    result = ["build", "--profile", args.profile, "--min-free-gib", str(args.min_free_gib)]
    for field in ("version", "jobs", "work_dir", "base_kernel"):
        value = getattr(args, field)
        if value is not None:
            result.extend(["--" + field.replace("_", "-"), str(value)])
    for field in ("prepare_only", "allow_rc"):
        result.append("--" + ("" if getattr(args, field) else "no-") + field.replace("_", "-"))
    if args.refresh_base:
        result.append("--refresh-base")
    return result


def build_menu(parser):
    names = list(PROFILES)
    index = choose("Choose a build profile:",
                   [f"{name} — {PROFILES[name].description}" for name in names])
    args = parser.parse_args(["build", "--profile", names[index]])
    apply_profile(args)
    say("Enter keeps the current value when editing; '-' resets values to the profile defaults. q cancels.\n"
        "Profiles keep the Fedora kernel configuration baseline. Builds do not install RPMs.")
    while True:
        version_label = args.version or ("required — edit setting 1" if args.profile == "rc" else "latest stable")
        say(f"\nProfile: {args.profile}\n"
            f"  1. Kernel version: {version_label}\n"
            f"  2. Parallel jobs: {args.jobs or 'automatic (CPU/RAM)'}\n"
            f"  3. Workspace: {args.work_dir or 'automatic (Fedora/architecture)'}\n"
            f"  4. Minimum free space: {args.min_free_gib} GiB\n"
            f"  5. Fedora baseline kernel: {args.base_kernel or 'automatic'}\n"
            f"  6. Refresh baseline: {'yes' if args.refresh_base else 'no'}\n"
            f"  7. Prepare only: {'yes' if args.prepare_only else 'no'}\n"
            f"  8. Allow release candidates: {'yes' if args.allow_rc else 'no'}\n"
            "  s. Start with these settings\n  q. Cancel")
        value = answer("Setting to edit, s to start (Enter to cancel): ").lower()
        if not value:
            raise Cancelled
        if value == "s":
            try:
                if args.profile == "rc" and not args.version:
                    raise Error("Set an explicit kernel version for the rc profile (setting 1).")
                if args.version:
                    validate_version(args.version, allow_rc=args.allow_rc)
            except Error as error:
                say(str(error))
                continue
            say("Command: " + shlex.join([*cli_command(), *build_arguments(args)]))
            return args
        if value in {"6", "7", "8"}:
            field = {"6": "refresh_base", "7": "prepare_only", "8": "allow_rc"}[value]
            setattr(args, field, not getattr(args, field))
        elif value in {"1", "2", "3", "4", "5"}:
            field, label = {"1": ("version", "Kernel version"),
                            "2": ("jobs", "Parallel jobs (positive integer)"),
                            "3": ("work_dir", "Workspace path"),
                            "4": ("min_free_gib", "Minimum free GiB (positive integer)"),
                            "5": ("base_kernel", "Exact installed Fedora kernel release")}[value]
            new = answer(label + " (Enter to keep): ")
            if not new:
                continue
            if new == "-":
                default = 50 if field == "min_free_gib" else (
                    PROFILES[args.profile].jobs if field == "jobs" else None)
                setattr(args, field, default)
                continue
            if field in {"jobs", "min_free_gib"}:
                try:
                    new = int(new)
                    if new < 1:
                        raise ValueError
                except ValueError:
                    say("Enter a positive integer.")
                    continue
            if field == "work_dir":
                new = Path(new)
            setattr(args, field, new)
        else:
            say("Choose a setting from 1 to 8, s to start, or q to cancel.")


def main_menu(parser):
    if not sys.stdin.isatty():
        raise Error("The menu needs an interactive terminal. Use profiles to list presets, "
                    "or build --profile NAME for scripts.")
    actions = [(["build"], "Build a kernel — choose and customize a profile"),
               (["check"], "Check system and build dependencies"),
               (["deps", "--install"], "Install build dependencies (sudo/DNF)"),
               (["install"], "Install RPMs from a completed build (sudo/DNF)"),
               (["kernels"], "List installed kernels"),
               (["set-default"], "Choose the default boot kernel"),
               (["remove"], "Choose a kernel to remove (DNF confirmation follows)"),
               (["offline-status"], "Show pending offline updates"),
               (["profiles"], "Show build profiles and command examples")]
    try:
        index = choose("Fedora Vanilla Kernel — choose an action:", [label for _, label in actions])
        command = list(actions[index][0])
        if command == ["build"]:
            return build_menu(parser)
        if command == ["install"]:
            directory = answer("Completed build directory (Enter to cancel): ")
            if not directory:
                raise Cancelled
            command.extend(["--", str(Path(directory).expanduser().resolve())])
        say("Command: " + shlex.join([*cli_command(), *command]))
        return parser.parse_args(command)
    except Cancelled:
        say("Cancelled. No action was started.")
        return None
