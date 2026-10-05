"""Use the Fedora Rust tools checked by the RPM dependency workflow."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re

from kernelpatching.errors import Error
from kernelpatching.system.process import run


@dataclass(frozen=True)
class RustToolchain:
    rustc: str
    rustdoc: str
    bindgen: str
    library: str
    compiler_version: str
    bindgen_version: str

    def make_arguments(self) -> list[str]:
        # Command-line assignments survive recursive make and RPM packaging.
        return [f"RUSTC={self.rustc}", f"HOSTRUSTC={self.rustc}",
                f"RUSTDOC={self.rustdoc}", f"BINDGEN={self.bindgen}",
                f"RUST_LIB_SRC={self.library}"]

    def summary(self) -> str:
        return (f"Fedora Rust compiler: {self.rustc} ({self.compiler_version})\n"
                f"Rust library sources: {self.library}\n"
                f"Fedora bindgen: {self.bindgen} ({self.bindgen_version})")


def fedora_rust_toolchain() -> RustToolchain:
    """Check tools and matching core sources before downloading kernel sources.

    Kernel-specific version/libclang checks still run through rustavailable once
    the verified source tree is present. Never fall back to a rustup PATH shim.
    """
    paths = {name: f"/usr/bin/{name}" for name in ("rustc", "rustdoc", "bindgen")}
    remedy = "Run deps --install; if these packages are already installed, repair the Fedora rust/rust-src/bindgen-cli packages."
    for path in paths.values():
        if not Path(path).is_file() or not os.access(path, os.X_OK):
            raise Error(f"Fedora Rust tool is missing or not executable: {path}.\n{remedy}")
    versions = {}
    for name, path in paths.items():
        output = run([path, "--version"]).stdout.strip()
        match = re.match(rf"{name} (\d+\.\d+\.\d+)\b", output)
        if not match:
            raise Error(f"Unexpected version from {path}: {output!r}.\n{remedy}")
        versions[name] = match[1]
    if versions["rustc"] != versions["rustdoc"]:
        raise Error(f"Fedora rustc/rustdoc versions do not match.\n{remedy}")
    sysroot = run([paths["rustc"], "--print", "sysroot"]).stdout.strip()
    # These paths become make variable values and must be safe for Kbuild shells.
    if not re.fullmatch(r"/[A-Za-z0-9_./-]+", sysroot):
        raise Error(f"Unsupported Fedora Rust sysroot: {sysroot!r}.")
    library = Path(sysroot) / "lib/rustlib/src/rust/library"
    core = library / "core/src/lib.rs"
    try:
        with core.open("rb") as source:
            if not source.read(1):
                raise Error(f"Fedora Rust core sources are empty: {core}.\n{remedy}")
    except OSError as error:
        raise Error(f"Fedora Rust core sources are missing or unreadable: {core}.\n{remedy}") from error
    return RustToolchain(**paths, library=str(library), compiler_version=versions["rustc"],
                         bindgen_version=versions["bindgen"])
