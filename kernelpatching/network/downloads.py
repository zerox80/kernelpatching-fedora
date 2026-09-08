"""Network downloads support for Fedora kernel builds."""
from __future__ import annotations
import urllib.request

from kernelpatching.errors import Error
from kernelpatching.system.console import say
from pathlib import Path
import time


def download(url: str, destination: Path, limit: int) -> None:
    say(f"Download: {url}")
    temporary = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "fedora-vanilla-builder/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as target:
            if not response.geturl().startswith("https://"):
                raise Error("The download was redirected to an unencrypted connection.")
            count, last = 0, time.monotonic()
            while chunk := response.read(1024 * 1024):
                count += len(chunk)
                if count > limit:
                    raise Error("The download is unexpectedly large.")
                target.write(chunk)
                if time.monotonic() - last > 20:
                    say(f"  {count // (1024 * 1024)} MiB downloaded")
                    last = time.monotonic()
            if response.headers.get("Content-Length") and count != int(response.headers["Content-Length"]):
                raise Error("The download is incomplete.")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
