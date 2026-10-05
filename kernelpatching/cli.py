"""Build a vanilla Linux kernel using a Fedora configuration. Fedora >= 44, Python >= 3.12.

  python3 fedora_vanilla_kernel.py check
  python3 fedora_vanilla_kernel.py deps --install
  python3 fedora_vanilla_kernel.py build
  python3 fedora_vanilla_kernel.py install /absolute/path/to/build
  python3 fedora_vanilla_kernel.py kernels
  python3 fedora_vanilla_kernel.py set-default
  python3 fedora_vanilla_kernel.py remove
  python3 fedora_vanilla_kernel.py remove KERNEL_RELEASE --dry-run

Builds run without root privileges. Explicit package changes use sudo and DNF.
Fedora source patches and EFI signing are not automated. The system is never rebooted automatically.
See README.md and docs/ for usage, provenance, and compatibility limits."""
from __future__ import annotations

from kernelpatching.system.offline import assert_no_pending_offline_updates, pending_offline_updates

from kernelpatching.constants import BASE_PACKAGES
from kernelpatching.constants import RUST_PACKAGES
from kernelpatching.constants import SCRIPT_VERSION
from kernelpatching.errors import Error
from kernelpatching.kernel.baseline import choose_baseline
from kernelpatching.operations.build import build
from kernelpatching.operations.boot_default import set_boot_default
from kernelpatching.operations.install import install
from kernelpatching.operations.inventory import list_kernels
from kernelpatching.operations.removal import remove_kernel
from kernelpatching.profiles import PROFILES, apply_profile, show_profiles
from kernelpatching.menu import main_menu
from kernelpatching.system.boot import secure_boot
from kernelpatching.system.console import cli_command
from kernelpatching.system.console import say
from kernelpatching.system.dependencies import dependencies
from kernelpatching.system.host import default_work_dir
from kernelpatching.system.host import fedora_version
from kernelpatching.system.host import host_check
from kernelpatching.system.host import job_count
from kernelpatching.system.process import privileged
from kernelpatching.system.rpm import missing_packages
from pathlib import Path
import argparse
import lzma
import platform
import re
import shlex
import subprocess
import sys
import tarfile


def positive(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("Must be at least 1.")
    return value



def release_key_arg(text: str) -> tuple[str, str]:
    fingerprint, separator, email = text.partition("=")
    fingerprint = fingerprint.replace(" ", "").upper()
    if not separator or not re.fullmatch(r"(?:[0-9A-F]{40}|[0-9A-F]{64})", fingerprint):
        raise argparse.ArgumentTypeError("Expected FULL_FINGERPRINT=name@kernel.org.")
    if not re.fullmatch(r"[a-zA-Z0-9._+-]+@kernel\.org", email):
        raise argparse.ArgumentTypeError("WKD requires a developer email address at kernel.org.")
    return fingerprint, email



def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    result.add_argument("--version", action="version", version=f"%(prog)s {SCRIPT_VERSION}")
    sub = result.add_subparsers(dest="command")
    sub.add_parser("menu", help="Choose an action and customize a build profile interactively")
    sub.add_parser("profiles", help="Show the built-in build profiles and examples")
    for action, help_text in (("check", "Check the system, baseline configuration, and dependencies"),
                              ("deps", "Print the DNF command for build dependencies"),
                              ("build", "Download signed sources, configure the kernel, and build RPMs")):
        p = sub.add_parser(action, help=help_text)
        p.add_argument("--work-dir", type=Path,
                       help="Workspace; defaults to XDG_STATE_HOME or ~/.local/state, grouped by Fedora release and architecture")
        p.add_argument("--base-kernel", help="Exact release of an installed official kernel for the current Fedora release")
        if action == "deps":
            p.add_argument("--install", action="store_true", help="Install dependencies with sudo dnf")
        if action == "build":
            p.add_argument("--profile", choices=PROFILES, default="stable",
                           help="Build preset; explicit options override its defaults (default: stable)")
            p.add_argument("--version", help="Specific upstream version (RCs require --allow-rc); defaults to the latest stable release from kernel.org")
            p.add_argument("--allow-rc", action=argparse.BooleanOptionalAction, default=None,
                           help="Allow an explicit --version such as 7.3-rc2; without --version, still build latest stable")
            p.add_argument("--jobs", type=positive, help="Parallel jobs; the default accounts for RAM and CPUs")
            p.add_argument("--min-free-gib", type=positive, default=50, help="Required free space before building; default: 50 GiB")
            p.add_argument("--refresh-base", action="store_true", help="Refresh the saved baseline from an installed official package")
            p.add_argument("--prepare-only", action=argparse.BooleanOptionalAction, default=None,
                           help="Stop after configuration without building the kernel")
            p.add_argument("--release-key", type=release_key_arg, action="append", metavar="FINGERPRINT=EMAIL",
                           help="Trust an additional release key; verify the full fingerprint against an official source first")
    p = sub.add_parser("install", help="Install RPMs from a completed build using sudo/DNF")
    p.add_argument("directory", type=Path, help="Build directory containing manifest.json")
    p.add_argument("--make-default", action="store_true", help="Select the new GRUB default after successful installation")
    sub.add_parser("offline-status", help="Inspect prepared offline updates without changing them")
    sub.add_parser("kernels", help="List installed Fedora and custom kernels")
    p = sub.add_parser("set-default", help="Choose the installed kernel to boot by default")
    p.add_argument("release", nargs="?", help="Exact kernel release; omit to choose from a numbered menu")
    p.add_argument("--dry-run", action="store_true", help="Preview the default change without applying it")
    p = sub.add_parser("remove", help="Remove one explicitly selected installed kernel")
    p.add_argument("release", nargs="?", help="Exact kernel release; omit to choose from a numbered menu")
    p.add_argument("--dry-run", action="store_true", help="Preview selected packages without removing anything")
    return result



def main(argv=None) -> int:
    argument_parser = parser()
    args = argument_parser.parse_args(argv)
    try:
        if args.command is None and not sys.stdin.isatty():
            argument_parser.print_help()
            return 0
        if args.command in {None, "menu"}:
            args = main_menu(argument_parser)
            if args is None:
                return 0
        if args.command == "profiles":
            show_profiles()
            return 0
        if args.command == "build":
            apply_profile(args)
            if args.profile == "rc" and not args.version:
                raise Error("The rc profile needs an explicit --version, for example 7.3-rc2.")
        host_check()
        if args.command == "offline-status":
            pending = pending_offline_updates()
            say("\n".join(pending) if pending else "No pending offline updates were found.")
            return 0
        if args.command == "kernels":
            list_kernels()
            return 0
        if args.command == "set-default":
            set_boot_default(args)
            return 0
        if args.command == "remove":
            remove_kernel(args)
            return 0
        if args.command == "install":
            install(args)
            return 0
        if args.command == "deps":
            # Bootstrap minimal systems even when gpg and a saved baseline are unavailable.
            packages = list(dict.fromkeys(BASE_PACKAGES + RUST_PACKAGES))
            say(shlex.join(["sudo", "dnf", "install", *packages]))
            if args.install:
                assert_no_pending_offline_updates()
                privileged(["dnf", "install", *packages])
            return 0
        work = (args.work_dir or default_work_dir()).expanduser().resolve()
        if args.command == "build":
            build(args, work)
            return 0
        base, config = choose_baseline(work, args.base_kernel)
        packages = dependencies(config)
        missing = missing_packages(packages)
        say(f"System: Fedora {fedora_version()} / {platform.machine()}\nRunning kernel: {platform.release()}\n"
            f"Fedora baseline: {base.release}\nConfig-SHA256: {base.sha256}\n"
            f"Fedora source RPM for the baseline: {base.source_rpm or 'not recorded in the legacy snapshot'}\n"
            f"Workspace: {work}\nSecure Boot: {secure_boot()}\n"
            f"Suggested parallel jobs: {job_count()}")
        say("Missing build packages: " + (", ".join(missing) if missing else "none"))
        if missing:
            say("Next step: " + shlex.join([*cli_command(), "deps", "--install"]))
        return 1 if missing else 0
    except KeyboardInterrupt:
        say("\nCancelled. Build files and logs were retained; no reboot was requested.")
        return 130
    except (Error, OSError, ValueError, KeyError, TypeError, tarfile.TarError,
            lzma.LZMAError, subprocess.SubprocessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
