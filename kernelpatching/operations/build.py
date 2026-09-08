"""Operations build support for Fedora kernel builds."""
from __future__ import annotations

from kernelpatching.constants import GIB
from kernelpatching.constants import RELEASE_KEYS
from kernelpatching.constants import SCRIPT_VERSION
from kernelpatching.errors import Error
from kernelpatching.kernel.baseline import choose_baseline
from kernelpatching.kernel.configuration import configure
from kernelpatching.kernel.releases import latest_version
from kernelpatching.kernel.releases import validate_version
from kernelpatching.kernel.sources import extract_sources
from kernelpatching.packaging.rpms import build_packages
from kernelpatching.security.signatures import verified_tarball
from kernelpatching.storage.files import sha256
from kernelpatching.storage.files import write_json
from kernelpatching.storage.manifests import build_target
from kernelpatching.system.boot import secure_boot
from kernelpatching.system.console import cli_command
from kernelpatching.system.console import say
from kernelpatching.system.dependencies import dependencies
from kernelpatching.system.host import fedora_version
from kernelpatching.system.host import job_count
from kernelpatching.system.rpm import missing_packages
from pathlib import Path
import dataclasses
import datetime as dt
import fcntl
import platform
import re
import shlex
import shutil


def build(args, work: Path) -> None:
    # Kernel Makefiles and RPM macros do not support arbitrary path characters.
    if not re.fullmatch(r"/[A-Za-z0-9_./-]+", str(work)):
        raise Error("The build path may contain only ASCII letters, digits, /, dots, - and _.")
    work.mkdir(parents=True, exist_ok=True)
    with (work / ".build.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Error("A build is already running in this workspace.") from None
        base, config = choose_baseline(work, args.base_kernel, args.refresh_base)
        missing = missing_packages(dependencies(config))
        if missing:
            raise Error("Missing build dependencies: " + ", ".join(missing)
                        + "\nRun the deps --install subcommand first.")
        if shutil.disk_usage(work).free < args.min_free_gib * GIB:
            raise Error(f"Less than {args.min_free_gib} GiB is available in the build directory.")
        version = validate_version(args.version) if args.version else latest_version()
        timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M%S%f")
        directory = work / f"linux-{version}-{timestamp}"
        directory.mkdir(mode=0o700)
        (directory / "fedora-original.config").write_bytes(config)
        (work / "fedora-base.config").write_bytes(config)
        write_json(work / "baseline.json", dataclasses.asdict(base))
        suffix = f"-vanilla.fc{fedora_version()}.{timestamp}"
        jobs = args.jobs or job_count()
        say(f"Kernel: {version}\nFedora baseline: {base.release}\nBuild: {directory}\n"
            f"Parallel jobs: {jobs}\nSecure Boot: {secure_boot()}")
        keys = RELEASE_KEYS | dict(args.release_key or [])
        manifest = {"schema": 2, "script_version": SCRIPT_VERSION, "target": build_target(),
                    "status": "started", "upstream_version": version,
                    "upstream_source_url": f"https://cdn.kernel.org/pub/linux/kernel/v{version.split('.')[0]}.x/linux-{version}.tar.xz",
                    "fedora_source_patches_applied": False,
                    "trusted_release_keys": keys,
                    "baseline": dataclasses.asdict(base), "jobs": jobs,
                    "created_utc": dt.datetime.now(dt.timezone.utc).isoformat()}
        write_json(directory / "manifest.json", manifest)
        (directory / "PROVENANCE.txt").write_text(
            f"Application version: {SCRIPT_VERSION}\nTarget: Fedora {fedora_version()} / {platform.machine()}\n"
            f"Kernel source: Linux {version}, kernel.org Upstream\n"
            f"Download: {manifest['upstream_source_url']}\n"
            f"Configuration baseline: {base.package}\n"
            f"Fedora source RPM for the configuration baseline: {base.source_rpm or 'not recorded in the legacy snapshot'}\n"
            f"Fedora configuration SHA256: {base.sha256}\n"
            "Additional Fedora source patches applied: NONE\n"
            "The Fedora package version records the origin of the configuration only.\n"
            "Upstream fixes are included in the specified complete kernel release.\n"
            "Inspect the matching Fedora source RPM to identify its distribution patches.\n"
            "Configuration differences are in config.diff; RPM recipe changes are in packaging.diff.\n",
            encoding="utf-8")
        archive, signer = verified_tarball(version, directory, keys)
        manifest.update({"signer": signer, "source_tar_sha256": sha256(archive)})
        tree = extract_sources(archive, directory / "sources", version)
        release, make = configure(tree, directory, config, suffix, jobs)
        manifest.update({"kernel_release": release, "config_sha256": sha256(tree / ".config")})
        if args.prepare_only:
            manifest["status"] = "prepared"
        else:
            manifest["packages"] = build_packages(tree, directory, make, release)
            if sha256(tree / ".config") != manifest["config_sha256"]:
                raise Error("The configuration changed unexpectedly during packaging.")
            manifest["status"] = "built"
        write_json(directory / "manifest.json", manifest)
        say(f"Finished: {directory}\nConfiguration comparison: {directory / 'config.diff'}")
        if args.prepare_only:
            say("Preparation complete; no RPMs built. A later build command starts a new build.")
        else:
            say("To install this build:\n" + shlex.join([*cli_command(), "install", str(directory)]))
