"""Read pending offline updates without changing or invalidating them."""
from __future__ import annotations

from pathlib import Path
import re
import tomllib

from kernelpatching.errors import Error
from kernelpatching.system.process import run

SYSTEM_UPDATE_MARKER = Path("/system-update")
PACKAGEKIT_UPDATE_MARKER = Path("/var/lib/PackageKit/prepared-update")


def offline_state_paths() -> list[Path]:
    """Inspect the effective DNF configuration, including a custom state directory."""
    result = run(["dnf", "--dump-main-config"], check=False, timeout=20)
    if result.returncode:
        raise Error("Cannot read the DNF configuration to check pending offline updates. "
                    "No package changes were started. Inspect 'sudo dnf5 offline status'.")
    match = re.search(r"(?m)^system_state_dir\s*=\s*(.+?)\s*$", result.stdout)
    if not match or not Path(match[1]).is_absolute():
        raise Error("Cannot determine the DNF system state directory. "
                    "No package changes were started.")
    roots = {Path("/usr/lib/sysimage/libdnf5"), Path(match[1])}
    return sorted(root / "offline/offline-transaction-state.toml" for root in roots)


def pending_offline_updates() -> list[str]:
    """Mirror DNF's pending state: every saved state except download-incomplete."""
    pending = []
    for path in offline_state_paths():
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
        except OSError as error:
            raise Error(f"Cannot read offline update state at {path}: {error}. "
                        "No package changes were started.") from error
        try:
            data = tomllib.loads(text)["offline-transaction-state"]
            status = data["status"]
            if not isinstance(status, str):
                raise ValueError("status must be a string")
        except (ValueError, KeyError, TypeError) as error:
            raise Error(f"Unrecognized offline update state at {path}. "
                        "Inspect 'sudo dnf5 offline status' before changing packages.") from error
        if status != "download-incomplete":
            current = str(data.get("system_releasever", "unknown"))
            target = str(data.get("target_releasever", "unknown"))
            pending.append(f"DNF offline update: status={status!r}, Fedora {current!r} -> {target!r}")
    # A marker also covers offline updates prepared by other package managers.
    marker = SYSTEM_UPDATE_MARKER
    if marker.is_symlink() or marker.exists():
        pending.append("An offline update is scheduled through /system-update.")
    prepared = PACKAGEKIT_UPDATE_MARKER
    if prepared.exists():
        pending.append("PackageKit has a prepared offline update.")
    return pending


def assert_no_pending_offline_updates() -> None:
    pending = pending_offline_updates()
    if pending:
        raise Error("Package changes are blocked because an offline update is pending:\n"
                    + "\n".join("  " + item for item in pending)
                    + "\nFinish the prepared update through your software manager and reboot.\n"
                    "Alternatively, to discard a stale or unwanted DNF offline transaction, run:\n"
                    "  sudo dnf5 offline clean\n"
                    "This cancels the saved DNF transaction and deletes its cached downloads. "
                    "It does not uninstall packages or delete your kernel build.\n"
                    "Then retry your original command. "
                    "The script has not installed, removed, or cancelled anything.")
