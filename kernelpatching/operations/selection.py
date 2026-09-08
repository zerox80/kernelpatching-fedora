"""Choose one installed kernel from a numbered terminal menu."""
from __future__ import annotations

import sys

from kernelpatching.errors import Error
from kernelpatching.system.console import say


def select_kernel(entries: list[dict], running: str, default: str = "", *,
                  action: str = "remove") -> str | None:
    """Return an exact release, or None when the user cancels."""
    if action not in {"remove", "set-default"}:
        raise ValueError(f"Unknown kernel selection action: {action}")
    if not entries:
        say("No supported kernel packages were found.")
        return None
    if not sys.stdin.isatty():
        raise Error("The numbered selector needs an interactive terminal. "
                    f"For scripts, use {action} KERNEL_RELEASE (optionally with --dry-run).")

    protected = set()
    say("Choose one kernel version to remove:" if action == "remove"
        else "Choose the kernel to boot by default:")
    for number, entry in enumerate(entries, start=1):
        marks = []
        if entry["release"] == running:
            marks.append("running")
        if entry["image"] == default:
            marks.append("boot default")
        if marks and action == "remove":
            protected.add(number)
            marks.append("protected")
        suffix = " [" + ", ".join(marks) + "]" if marks else ""
        say(f"  {number}. {entry['release']} — {entry['kind']}{suffix}")
    if len(protected) == len(entries):
        say("No selectable kernels. The running kernel and boot default are protected.")
        return None
    if action == "remove":
        say("The number selects one version and its component packages. "
            "Removal checks and DNF confirmation follow.")
    else:
        say("The selected kernel will be used by default on future boots. No reboot is started.")

    numbers = {str(number): number for number in range(1, len(entries) + 1)}
    while True:
        try:
            answer = input("Kernel number (Enter or q to cancel): ").strip()
        except EOFError:
            answer = ""
        if not answer or answer.lower() in {"q", "quit"}:
            say("Cancelled. No kernels were removed." if action == "remove"
                else "Cancelled. The boot default was not changed.")
            return None
        # Match the displayed labels instead of interpreting arbitrary numeric input.
        number = numbers.get(answer)
        if number is None:
            say(f"Enter a number from 1 to {len(entries)}, or q to cancel.")
            continue
        if number in protected:
            say("That kernel is protected. Choose another number, or q to cancel.")
            continue
        return entries[number - 1]["release"]
