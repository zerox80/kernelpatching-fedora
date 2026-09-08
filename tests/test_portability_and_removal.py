import argparse
import contextlib
import hashlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_builder import b, completed, FedoraTestCase, SCRIPT
from support import patch_symbol, SPEC_FIXTURE


class HostTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch_symbol("assert_no_pending_offline_updates"))

    def test_future_numbered_fedora_releases_have_no_upper_cap(self):
        for version in (44, 45, 46, 60):
            with self.subTest(version=version), patch.object(b.platform, "freedesktop_os_release",
                    return_value={"ID": "fedora", "VERSION_ID": str(version), "RELEASE_TYPE": "stable"}):
                self.assertEqual(b.fedora_version(), version)

    def test_unsupported_os_and_rawhide_are_rejected(self):
        for info in ({"ID": "fedora", "VERSION_ID": "43"},
                     {"ID": "ubuntu", "VERSION_ID": "45"},
                     {"ID": "fedora", "VERSION_ID": "rawhide"},
                     {"ID": "fedora", "VERSION_ID": "46", "RELEASE_TYPE": "development"}):
            with self.subTest(info=info), patch.object(b.platform, "freedesktop_os_release", return_value=info):
                with self.assertRaises(b.Error):
                    b.fedora_version()

    def test_workspace_is_per_fedora_architecture_and_user_state_directory(self):
        with patch.dict(os.environ, {"XDG_STATE_HOME": "/tmp/user-state"}), \
                patch.object(b.platform, "machine", return_value="aarch64"):
            paths = []
            for version in (44, 45):
                with patch_symbol("fedora_version", return_value=version):
                    paths.append(b.default_work_dir())
            self.assertNotEqual(*paths)
            self.assertEqual(str(paths[1]), "/tmp/user-state/fedora-vanilla-kernel/fedora-45-aarch64")

    def test_deps_bootstraps_without_gpg_or_baseline(self):
        with patch_symbol("host_check"), patch_symbol("choose_baseline", side_effect=AssertionError), \
                patch_symbol("fedora_signing_ids", side_effect=AssertionError), \
                patch_symbol("privileged") as privileged, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(b.main(["deps", "--install"]), 0)
            self.assertIn("gnupg2", privileged.call_args[0][0])
            self.assertIn("fedora-gpg-keys", privileged.call_args[0][0])


class FedoraUpgradeTests(FedoraTestCase):
    def snapshot(self, root):
        data = b"CONFIG_RUST=y\n"
        base = b.Baseline("7.1.13-200.fc44.x86_64", "old-fedora", "x86_64", "/old/config",
                          hashlib.sha256(data).hexdigest(), "sig", 44, "old.src.rpm")
        b.write_json(root / "baseline.json", b.dataclasses.asdict(base))
        (root / "fedora-base.config").write_bytes(data)

    def test_upgrade_selects_fedora45_config_not_old_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.snapshot(root)
            new_data = b"CONFIG_NEW_FEDORA45_FEATURE=y\n"
            new_file = "/lib/modules/7.3.1-200.fc45.x86_64/config"
            package = {"release": "7.3.1-200.fc45.x86_64", "package": "new-fedora45", "arch": "x86_64", "signature": "new-sig"}
            original_read = Path.read_bytes
            def read_bytes(path):
                return new_data if str(path) == new_file else original_read(path)
            with patch_symbol("fedora_version", return_value=45), \
                    patch_symbol("official_kernels", return_value=[package]), \
                    patch_symbol("rpm_file_digests", return_value=("sha512", {new_file: hashlib.sha512(new_data).hexdigest()})), \
                    patch.object(Path, "read_bytes", read_bytes), \
                    patch_symbol("run", return_value=completed("kernel-7.3.1-200.fc45.src.rpm")), \
                    contextlib.redirect_stdout(io.StringIO()):
                base, config = b.choose_baseline(root)
            self.assertEqual(config, new_data)
            self.assertEqual(base.fedora_version, 45)
            self.assertEqual(base.source_rpm, "kernel-7.3.1-200.fc45.src.rpm")
            self.assertEqual(base.sha256, hashlib.sha256(new_data).hexdigest())

    def test_upgrade_without_current_official_kernel_never_reuses_old_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.snapshot(root)
            with patch_symbol("fedora_version", return_value=45), \
                    patch_symbol("official_kernels", return_value=[]), \
                    contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(b.Error, "Fedora 45"):
                    b.choose_baseline(root)

    def test_manifest_rejects_cross_release_and_cross_arch_installation(self):
        manifest = {"schema": 2, "kernel_release": "7.3.1-vanilla.fc45.123456",
                    "target": {"fedora_version": 45, "architecture": "x86_64"}}
        with self.assertRaisesRegex(b.Error, "Build target"):
            b.validate_target(manifest)
        with patch_symbol("fedora_version", return_value=45):
            b.validate_target(manifest)
            manifest["target"]["architecture"] = "aarch64"
            with self.assertRaisesRegex(b.Error, "Build target"):
                b.validate_target(manifest)

    def test_old_manifest_remains_installable_only_on_fedora44(self):
        manifest = {"schema": 1, "kernel_release": "7.2.4-vanilla44.123456"}
        b.validate_target(manifest)
        with patch_symbol("fedora_version", return_value=45):
            with self.assertRaises(b.Error):
                b.validate_target(manifest)

    def test_target_marker_tampering_is_rejected(self):
        manifest = {"schema": 2, "kernel_release": "7.3.1-vanilla.fc45.123456",
                    "target": {"fedora_version": 44, "architecture": "x86_64"}}
        with self.assertRaisesRegex(b.Error, "kernel release"):
            b.validate_target(manifest)


class KeyCompatibilityTests(FedoraTestCase):
    def test_fedora_keys_are_loaded_from_each_distribution_package(self):
        for version, key_id in ((44, "1234567890123456"), (45, "ABCDEF0123456789"), (60, "FEDCBA9876543210")):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / f"RPM-GPG-KEY-fedora-{version}-primary"
                path.write_bytes(b"trusted-package-file")
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                pub = f"pub:-:255:22:{key_id}:1736879931:::-:::scSC:\n"
                with patch_symbol("rpm_file_digests", return_value=("sha256", {str(path): digest})), \
                        patch_symbol("run", return_value=completed(pub)):
                    self.assertEqual(b.fedora_signing_ids(version), {key_id})
                    path.write_bytes(b"tampered")
                    with self.assertRaisesRegex(b.Error, "file digest"):
                        b.fedora_signing_ids(version)

    def test_expired_and_revoked_primary_keys_and_subkeys_are_rejected(self):
        pub = "pub:-:4096:1:1234567890123456:1::::\n"
        sub = "sub:-:4096:1:ABCDEF0123456789:1::::\n"
        self.assertEqual(b.key_ids_from_colons(pub + sub), {"1234567890123456", "ABCDEF0123456789"})
        self.assertEqual(b.key_ids_from_colons(pub.replace("pub:-:", "pub:r:") + sub), set())
        self.assertEqual(b.key_ids_from_colons(pub + sub.replace(":1::::", ":1:2:::")), {"1234567890123456"})

    def test_rpm_openpgp_and_legacy_signature_formats(self):
        for tag, fmt in (("OPENPGP", "[%{OPENPGP:pgpsig};]"), ("RSAHEADER", "%{RSAHEADER:pgpsig}")):
            def fake_run(argv, **kwargs):
                if "--querytags" in argv:
                    return completed(tag + "\n")
                self.assertIn(fmt, argv[-1])
                return completed("kernel-core|7.4.2|200.fc45|x86_64|Fedora Project|EdDSA/SHA512, Key ID ABCDEF0123456789\n")
            with self.subTest(tag=tag), patch_symbol("fedora_version", return_value=45), \
                    patch_symbol("fedora_signing_ids", return_value={"ABCDEF0123456789"}), \
                    patch_symbol("run", side_effect=fake_run):
                self.assertEqual(b.official_kernels()[0]["release"], "7.4.2-200.fc45.x86_64")

    def test_future_developer_key_requires_explicit_full_fingerprint(self):
        fingerprint = "D" * 64
        pair = b.release_key_arg(f"{fingerprint}=developer@kernel.org")
        status = f"[GNUPG:] VALIDSIG {fingerprint} 2026-09-01 1788220800 0 4 0 22 10 00 {fingerprint}\n"
        with self.assertRaises(b.Error):
            b.signature_fingerprint(status, 0)
        self.assertEqual(b.signature_fingerprint(status, 0, dict([pair])), fingerprint)
        for value in ("short=developer@kernel.org", fingerprint + "=untrusted@example.org"):
            with self.assertRaises(argparse.ArgumentTypeError):
                b.release_key_arg(value)


class RecipeCompatibilityTests(unittest.TestCase):
    def test_whitespace_and_upstream_provides_are_idempotent(self):
        original = SPEC_FIXTURE.read_text()
        changed = original.replace("Name: kernel", "Name :   kernel   ").replace("%package devel", "%package   devel   ")
        once = b.adapt_rpm_spec(changed)
        self.assertEqual(once, b.adapt_rpm_spec(once))
        self.assertEqual(once.count("Provides: installonlypkg(kernel)"), 2)
        self.assertIn("Name: kernel-vanilla-local", once)

    def test_unknown_non_shell_scriptlet_is_rejected(self):
        original = SPEC_FIXTURE.read_text()
        with self.assertRaises(b.Error):
            b.adapt_rpm_spec(original.replace("\n%post\n", "\n%post -p <lua>\n"))


class RemovalTests(FedoraTestCase):
    OLD = "7.1.10-200.fc44.x86_64"
    CURRENT = "7.1.13-200.fc44.x86_64"
    CUSTOM = "7.2.4-vanilla.fc44.123456"

    def entries(self):
        return [{"release": release, "image": f"/boot/vmlinuz-{release}",
                 "packages": [f"kernel-core-{release}"], "kind": "test"}
                for release in (self.OLD, self.CURRENT, self.CUSTOM)]

    def plan(self, selected, running=None, default=None, official=None):
        with patch.object(Path, "is_file", return_value=True):
            return b.removal_plan(selected, self.entries(),
                official if official is not None else [{"release": self.CURRENT}],
                running or self.CURRENT, default or f"/boot/vmlinuz-{self.CURRENT}")

    def test_can_remove_old_kernel_with_precise_package_selection(self):
        self.assertEqual(self.plan(self.OLD), [f"kernel-core-{self.OLD}"])

    def test_running_default_and_last_official_kernel_are_protected(self):
        cases = [dict(selected=self.CURRENT),
                 dict(selected=self.OLD, default=f"/boot/vmlinuz-{self.OLD}"),
                 dict(selected=self.CURRENT, running=self.CUSTOM, default=f"/boot/vmlinuz-{self.CUSTOM}"),
                 dict(selected="7.*"), dict(selected="missing"), dict(selected=self.OLD, default="unknown")]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(b.Error):
                self.plan(**case)

    def test_inventory_groups_official_and_custom_packages_and_excludes_headers(self):
        lines = []
        for name in ("kernel", "kernel-core", "kernel-modules", "kernel-devel", "kernel-headers"):
            provides = f"kernel-uname-r={self.OLD};" if name == "kernel-core" else ""
            lines.append(f"{name}|7.1.10|200.fc44|x86_64|{name}-{self.OLD}|{provides}")
        for name in (b.PACKAGE_NAME, b.PACKAGE_NAME + "-devel"):
            provides = f"kernel-uname-r={self.CUSTOM};" if name == b.PACKAGE_NAME else ""
            lines.append(f"{name}|7.2.4_vanilla.fc44.123456|1.fc44|x86_64|{name}-7.2.4_vanilla.fc44.123456-1.fc44.x86_64|{provides}")
        with patch_symbol("run", return_value=completed("\n".join(lines))):
            entries = b.kernel_inventory()
        self.assertEqual(len(entries), 2)
        old = next(e for e in entries if e["release"] == self.OLD)
        self.assertEqual(len(old["packages"]), 4)
        self.assertFalse(any("headers" in p for p in old["packages"]))
        custom = next(e for e in entries if e["release"] == self.CUSTOM)
        self.assertEqual(len(custom["packages"]), 2)

    def removal_flow(self, dry_run=False, fail=False):
        default = f"/boot/vmlinuz-{self.CURRENT}"
        calls = []
        inventory = [self.entries(), [e for e in self.entries() if e["release"] != self.OLD]]
        def privileged(argv):
            calls.append(argv)
            if argv[0] == "dnf" and fail:
                raise b.Error("DNF failure")
        with patch_symbol("kernel_inventory", side_effect=inventory), \
                patch_symbol("official_kernels", return_value=[{"release": self.CURRENT}]), \
                patch.object(b.platform, "release", return_value=self.CURRENT), \
                patch_symbol("run", return_value=completed(default)), \
                patch.object(Path, "is_file", return_value=True), \
                patch.object(b.shutil, "which", return_value="/usr/bin/tool"), \
                patch_symbol("privileged", side_effect=privileged), contextlib.redirect_stdout(io.StringIO()):
            args = argparse.Namespace(release=self.OLD, dry_run=dry_run)
            if fail:
                with self.assertRaises(b.Error):
                    b.remove_kernel(args)
            else:
                b.remove_kernel(args)
        return calls

    def test_dry_run_never_modifies_packages_or_bootloader(self):
        self.assertEqual(self.removal_flow(dry_run=True), [])

    def test_remove_preserves_default_and_disables_autoremove(self):
        calls = self.removal_flow()
        self.assertIn("--setopt=clean_requirements_on_remove=False", calls[0])
        self.assertIn("--setopt=protect_running_kernel=True", calls[0])
        self.assertIn("--setopt=assumeyes=False", calls[0])
        self.assertNotIn("-y", calls[0])
        self.assertEqual(calls[-1], ["grubby", f"--set-default=/boot/vmlinuz-{self.CURRENT}"])

    def test_failed_remove_restores_default(self):
        calls = self.removal_flow(fail=True)
        self.assertEqual(calls[-1], ["grubby", f"--set-default=/boot/vmlinuz-{self.CURRENT}"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
