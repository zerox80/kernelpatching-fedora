"""Shared defaults and explicitly trusted release fingerprints.

Release key source: https://www.kernel.org/signature.html
"""
from __future__ import annotations
import re

SCRIPT_VERSION = "2.1.0"


MIN_FEDORA = 44


PACKAGE_NAME = "kernel-vanilla-local"


RELEASE_KEYS = {
    "ABAF11C65A2970B130ABE3C479BE3E4300411886": "torvalds@kernel.org",
    "647F28654894E3BD457199BE38DBBDC86092693E": "gregkh@kernel.org",
    "E27E5D8A3403A2EF66873BBCDEA66FF797772CDC": "sashal@kernel.org",
}


BASE_PACKAGES = """gcc gcc-c++ make binutils bc bison flex openssl openssl-devel
elfutils-devel elfutils-libelf-devel ncurses-devel dwarves perl python3 rsync
rpm-build redhat-rpm-config zstd xz gzip tar cpio diffutils findutils patch
gnupg2 fedora-gpg-keys gcc-plugin-devel""".split()


RUST_PACKAGES = "rust rust-src bindgen-cli clang clang-devel llvm-devel lld".split()


VERSION_RE = re.compile(r"[1-9][0-9]*\.[0-9]+(?:\.[0-9]+)?\Z")


RELEASE_RE = re.compile(r"[0-9][A-Za-z0-9._+-]{1,100}\Z")


GIB = 1024 ** 3


RPM_HASHES = {"8": "sha256", "9": "sha384", "10": "sha512", "11": "sha224"}
