"""System dependencies support for Fedora kernel builds."""
from __future__ import annotations

from kernelpatching.constants import BASE_PACKAGES
from kernelpatching.constants import RUST_PACKAGES
from kernelpatching.kernel.configuration import config_values


def dependencies(config: bytes) -> list[str]:
    packages = BASE_PACKAGES.copy()
    if config_values(config.decode()).get("CONFIG_RUST") == "y":
        packages += RUST_PACKAGES
    return packages
