"""System console support for Fedora kernel builds."""
from __future__ import annotations

from pathlib import Path
import sys


def say(message: str) -> None:
    print(message, flush=True)



def cli_command() -> list[str]:
    """Return a usable command from either a source checkout or an installed package."""
    launcher = Path(__file__).resolve().parents[2] / "fedora_vanilla_kernel.py"
    if launcher.is_file():
        return [sys.executable, str(launcher)]
    return [sys.executable, "-m", "kernelpatching"]
