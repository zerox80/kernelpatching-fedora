"""Security signatures support for Fedora kernel builds."""
from __future__ import annotations

from kernelpatching.constants import GIB
from kernelpatching.constants import RELEASE_KEYS
from kernelpatching.errors import Error
from kernelpatching.network.downloads import download
from kernelpatching.system.console import say
from kernelpatching.system.process import run
from pathlib import Path
import lzma
import subprocess
import tempfile


def signature_fingerprint(status: str, returncode: int, keys: dict[str, str] | None = None) -> str:
    keys = RELEASE_KEYS if keys is None else keys
    valid = []
    forbidden = {"BADSIG", "ERRSIG", "EXPSIG", "EXPKEYSIG", "REVKEYSIG", "NO_PUBKEY"}
    for line in status.splitlines():
        fields = line.split()
        if len(fields) < 2 or fields[0] != "[GNUPG:]":
            continue
        if fields[1] in forbidden:
            raise Error(f"Kernel signature rejected: {fields[1]}")
        if fields[1] == "VALIDSIG" and len(fields) >= 11:
            primary = fields[11] if len(fields) > 11 else fields[2]
            # Accept SHA256/384/512/224; reject SHA1 and MD5 signatures.
            if primary.upper() in keys and fields[9] in {"8", "9", "10", "11"}:
                valid.append(primary.upper())
    if returncode != 0 or not valid:
        raise Error("No valid signature from an explicitly trusted kernel developer. "
                    "For a legitimate key rotation, verify the official fingerprint; see --release-key.")
    return valid[0]



def verified_tarball(version: str, directory: Path, keys: dict[str, str] | None = None) -> tuple[Path, str]:
    keys = RELEASE_KEYS if keys is None else keys
    prefix = f"https://cdn.kernel.org/pub/linux/kernel/v{version.split('.')[0]}.x/linux-{version}"
    archive = directory / f"linux-{version}.tar.xz"
    signature = directory / f"linux-{version}.tar.sign"
    tarpath = directory / f"linux-{version}.tar"
    download(prefix + ".tar.xz", archive, 1024 ** 3)
    download(prefix + ".tar.sign", signature, 1024 ** 2)
    say("Decompressing XZ data for signature verification...")
    # The .tar.sign signature covers the uncompressed TAR archive.
    with lzma.open(archive, "rb") as source, tarpath.open("wb") as target:
        size = 0
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            if size > 8 * GIB:
                raise Error("The decompressed archive is unexpectedly large.")
            target.write(chunk)
    with tempfile.TemporaryDirectory(prefix="gnupg-", dir=directory) as tmp:
        keyring = Path(tmp)
        keyring.chmod(0o700)
        gpg = ["gpg", "--no-options", "--homedir", keyring, "--batch", "--no-tty"]
        for email in sorted(set(keys.values())):
            say(f"Refreshing release keys through kernel.org WKD: {email}")
            try:
                result = run([*gpg, "--auto-key-locate", "clear,wkd",
                              "--locate-external-keys", email], check=False, timeout=60)
            except subprocess.TimeoutExpired:
                say(f"  WKD request timed out for {email}; signature verification is still required.")
                continue
            with (directory / "signature.log").open("a", encoding="utf-8") as log:
                log.write(result.stdout + result.stderr)
        verified = run([*gpg, "--no-auto-key-retrieve", "--status-fd", "1", "--verify",
                        signature, tarpath], check=False, timeout=180)
        (directory / "signature.status").write_text(verified.stdout, encoding="utf-8")
        with (directory / "signature.log").open("a", encoding="utf-8") as log:
            log.write(verified.stderr)
        signer = signature_fingerprint(verified.stdout, verified.returncode, keys)
    say(f"Valid kernel signature: {signer}")
    return tarpath, signer
