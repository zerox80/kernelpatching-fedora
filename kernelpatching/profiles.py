"""Build presets; explicit command-line settings take precedence."""
from __future__ import annotations

from dataclasses import dataclass
import shlex

from kernelpatching.system.console import cli_command, say


@dataclass(frozen=True)
class Profile:
    description: str
    jobs: int | None = None
    prepare_only: bool = False
    allow_rc: bool = False


PROFILES = {
    "stable": Profile("Latest stable kernel; automatic CPU/RAM-based parallelism"),
    "low-load": Profile("Latest stable kernel; one compiler job to reduce build load", jobs=1),
    "prepare": Profile("Verify sources and prepare configuration; do not compile RPMs", prepare_only=True),
    "rc": Profile("Allow a release candidate; requires an explicit kernel version", allow_rc=True),
}


def apply_profile(args) -> None:
    profile = PROFILES[args.profile]
    for field in ("jobs", "prepare_only", "allow_rc"):
        if getattr(args, field) is None:
            setattr(args, field, getattr(profile, field))


def show_profiles() -> None:
    for name, profile in PROFILES.items():
        say(f"{name}: {profile.description}")
    say("\nProfiles use the Fedora configuration baseline and require 50 GiB free by default.\n"
        "Explicit options override the preset. Examples:")
    command = shlex.join(cli_command())
    say(f"  {command} build --profile low-load\n"
        f"  {command} build --profile low-load --jobs 2\n"
        f"  {command} build --profile prepare --version 7.2.4\n"
        f"  {command} build --profile rc --version 7.3-rc2\n"
        f"  {command} menu")
