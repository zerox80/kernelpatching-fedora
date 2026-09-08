"""Cross-module dependency injection for the preserved workflow regression tests."""
from contextlib import ExitStack, contextmanager
import dataclasses
import hashlib
import importlib
import os
from pathlib import Path
import platform
import shutil
import sys
import types
import urllib.request
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "fedora_vanilla_kernel.py"
SPEC_FIXTURE = Path(__file__).resolve().parent / "fixtures/kernel.spec"
OWNERS = {'Error': 'errors', 'Baseline': 'models', 'say': 'system.console', 'environment': 'system.process', 'run': 'system.process', 'logged': 'system.process', 'privileged': 'system.process', 'fedora_version': 'system.host', 'default_work_dir': 'system.host', 'host_check': 'system.host', 'job_count': 'system.host', 'rpm_file_digests': 'system.rpm', 'checked_rpm_file': 'system.rpm', 'missing_packages': 'system.rpm', 'dependencies': 'system.dependencies', 'secure_boot': 'system.boot', 'sha256': 'storage.files', 'write_json': 'storage.files', 'build_target': 'storage.manifests', 'validate_target': 'storage.manifests', 'key_ids_from_colons': 'security.fedora_keys', 'fedora_signing_ids': 'security.fedora_keys', 'signature_fingerprint': 'security.signatures', 'verified_tarball': 'security.signatures', 'download': 'network.downloads', 'validate_version': 'kernel.releases', 'latest_version': 'kernel.releases', 'extract_sources': 'kernel.sources', 'official_kernels': 'kernel.baseline', 'choose_baseline': 'kernel.baseline', 'config_values': 'kernel.configuration', 'configure': 'kernel.configuration', 'adapt_rpm_spec': 'packaging.spec', 'build_packages': 'packaging.rpms', 'validate_packages': 'packaging.rpms', 'kernel_inventory': 'operations.inventory', 'list_kernels': 'operations.inventory', 'removal_plan': 'operations.removal', 'remove_kernel': 'operations.removal', 'install_command': 'operations.install', 'install': 'operations.install', 'build': 'operations.build', 'positive': 'cli', 'release_key_arg': 'cli', 'parser': 'cli', 'main': 'cli', 'SCRIPT_VERSION': 'constants', 'MIN_FEDORA': 'constants', 'PACKAGE_NAME': 'constants', 'RELEASE_KEYS': 'constants', 'BASE_PACKAGES': 'constants', 'RUST_PACKAGES': 'constants', 'VERSION_RE': 'constants', 'RELEASE_RE': 'constants', 'GIB': 'constants', 'RPM_HASHES': 'constants', 'cli_command': 'system.console', 'offline_state_paths': 'system.offline', 'pending_offline_updates': 'system.offline', 'assert_no_pending_offline_updates': 'system.offline'}
api = types.SimpleNamespace()
for name, owner in OWNERS.items():
    setattr(api, name, getattr(importlib.import_module("kernelpatching." + owner), name))
for name, value in {"dataclasses":dataclasses, "hashlib":hashlib, "os":os,
                    "Path":Path, "platform":platform, "shutil":shutil, "urllib":urllib}.items():
    setattr(api, name, value)

@contextmanager
def patch_symbol(name, **kwargs):
    """Patch a dependency at every package import site, sharing one test double."""
    sites = [module for key, module in list(sys.modules.items())
             if key.startswith("kernelpatching.") and hasattr(module, name)]
    if not sites:
        raise AssertionError(f"No package import site for {name}")
    with ExitStack() as stack:
        replacement = stack.enter_context(patch.object(sites[0], name, **kwargs))
        for module in sites[1:]:
            stack.enter_context(patch.object(module, name, new=replacement))
        yield replacement
