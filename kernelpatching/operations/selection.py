"""Choose one installed kernel from a numbered terminal menu."""
from __future__ import annotations

import sys

from kernelpatching.errors import Error
from kernelpatching.system.console import say


def select_kernel(entries: list[dict], running: str, default: str = "") -> str | None:
    """Return an exact release, or None when the user cancels."""
    if not entries:
        say("No supported kernel packages were found.")
        return None
    if not sys.stdin.isatty():
        raise Error("The numbered selector needs an interactive terminal. "
                    "For scripts, use remove KERNEL_RELEASE (optionally with --dry-run).")

    protected = set()
    say("Choose one kernel version to remove:")
    for number, entry in enumerate(entries, start=1):
        marks = []
        if entry["release"] == running:
            marks.append("running")
        if entry["image"] == default:
            marks.append("boot default")
        if marks:
            protected.add(number)
            marks.append("protected")
        suffix = " [" + ", ".join(marks) + "]" if marks else ""
        say(f"  {number}. {entry['release']} — {entry['kind']}{suffix}")
    if len(protected) == len(entries):
        say("No selectable kernels. The running kernel and boot default are protected.")
        return None
    say("The number selects one version and its component packages. "
        "Removal checks and DNF confirmation follow.")

    while True:
        try:
            answer = input("Kernel number (Enter or q to cancel): ").strip()
        except EOFError:
            answer = ""
        if not answer or answer.lower() in {"q", "quit"}:
            say("Cancelled. No kernels were removed.")
            return None
        # Match the displayed labels instead of interpreting arbitrary numeric input.
        numbers = {str(number): number for number in range(1, len(entries) + 1)}
        number = numbers.get(answer)
        if number is None:
            say(f"Enter a number from 1 to {len(entries)}, or q to cancel.")
            continue
        if number in protected:
            say("That kernel is protected. Choose another number, or q to cancel.")
            continue
        return entries[number - 1]["release"]
