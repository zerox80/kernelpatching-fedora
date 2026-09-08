import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import types
import unittest
from unittest.mock import patch

from support import api as b, patch_symbol, SCRIPT, SPEC_FIXTURE


def completed(stdout="", returncode=0):
    return subprocess.CompletedProcess([], returncode, stdout, "")


class FedoraTestCase(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch_symbol("assert_no_pending_offline_updates"))
        self.enterContext(patch_symbol("fedora_version", return_value=44))
        self.enterContext(patch.object(b.platform, "machine", return_value="x86_64"))


class SignatureTests(unittest.TestCase):
    def status(self, primary=None, digest="10"):
        primary = primary or next(iter(b.RELEASE_KEYS))
        return f"[GNUPG:] VALIDSIG {'C' * 40} 2026-09-01 1788220800 0 4 0 1 {digest} 00 {primary}\n"

    def test_accepts_pinned_primary_with_signing_subkey(self):
        self.assertEqual(b.signature_fingerprint(self.status(), 0), next(iter(b.RELEASE_KEYS)))

    def test_rejects_unknown_primary(self):
        with self.assertRaises(b.Error):
            b.signature_fingerprint(self.status("D" * 40), 0)

    def test_rejects_failure_expiry_revocation_and_weak_hash(self):
        cases = [(self.status(), 1), (self.status(digest="2"), 0)]
        cases += [(self.status() + f"[GNUPG:] {bad} anything\n", 0)
                  for bad in ("BADSIG", "ERRSIG", "EXPSIG", "EXPKEYSIG", "REVKEYSIG", "NO_PUBKEY")]
        for status, returncode in cases:
            with self.subTest(status=status), self.assertRaises(b.Error):
                b.signature_fingerprint(status, returncode)


class SourceTests(unittest.TestCase):
    def test_version_rejects_prereleases_and_injection(self):
        for value in ("7.3-rc2", "../7.2", "7.2;id", "$(id)", "7.2\n", "5.15.1"):
            with self.subTest(value=value), self.assertRaises(b.Error):
                b.validate_version(value)
        self.assertEqual(b.validate_version("7.2.4"), "7.2.4")

    def archive(self, directory, entries):
        target = directory / "test.tar"
        with tarfile.open(target, "w") as archive:
            for name, link in entries:
                member = tarfile.TarInfo(name)
                if link is not None:
                    member.type = tarfile.SYMTYPE
                    member.linkname = link
                    archive.addfile(member)
                else:
                    content = b"test\n"
                    member.size = len(content)
                    archive.addfile(member, io.BytesIO(content))
        return target

    def test_extract_accepts_real_tree_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = self.archive(root, [("linux-7.2.4/Makefile", None),
                                          ("linux-7.2.4/scripts/config", None)])
            tree = b.extract_sources(archive, root / "sources", "7.2.4")
            self.assertEqual((tree / "Makefile").read_text(), "test\n")

    def test_extract_blocks_traversal_and_symlink_escape(self):
        cases = [[("linux-7.2.4/../../escape", None)],
                 [("/tmp/escape", None)],
                 [("linux-7.2.4/link", "../../escape")]]
        for entries in cases:
            with self.subTest(entries=entries), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                archive = self.archive(root, entries)
                with self.assertRaises((b.Error, tarfile.TarError)):
                    b.extract_sources(archive, root / "sources", "7.2.4")
                self.assertFalse((root / "escape").exists())

    def test_latest_version_uses_stable_metadata(self):
        data = {"latest_stable": {"version": "7.2.4"}, "releases": [
            {"version": "7.3-rc2", "moniker": "mainline", "iseol": False},
            {"version": "7.2.4", "moniker": "stable", "iseol": False}]}
        with patch.object(b.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(data).encode())):
            self.assertEqual(b.latest_version(), "7.2.4")
        data["latest_stable"]["version"] = "7.3-rc2"
        with patch.object(b.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(data).encode())):
            with self.assertRaises(b.Error):
                b.latest_version()


class BaselineTests(FedoraTestCase):
    def test_excludes_non_fedora_and_selects_newest_numerically(self):
        key_id = "DBFCF71C6D9F90A6"
        sig = "RSA/SHA256, Key ID " + key_id.lower()
        rows = [f"kernel-core|7.1.9|200.fc44|x86_64|Fedora Project|{sig}",
                f"kernel-core|7.1.13|200.fc44|x86_64|Fedora Project|{sig}",
                f"kernel-core|7.1.13|201.fc44|x86_64|Fedora Project|{sig}",
                f"kernel-core|7.2|200.fc44|x86_64|Fedora Project|{sig}",
                f"kernel-core|7.2.4|200.fc44|x86_64|Fedora Project|{sig}",
                f"kernel-core|9.2|200.fc44|x86_64|Evil Project|{sig}",
                "kernel-core|9.9|200.fc44|x86_64|Fedora Project|Key ID 1234567890123456",
                f"kernel-core|9.9|200.fc45|x86_64|Fedora Project|{sig}"]
        def fake_run(argv, **kwargs):
            return completed("OPENPGP\n" if "--querytags" in argv else "\n".join(rows))
        with patch_symbol("run", side_effect=fake_run), \
                patch_symbol("fedora_signing_ids", return_value={key_id}):
            packages = b.official_kernels()
        self.assertEqual(packages[0]["release"], "7.2.4-200.fc44.x86_64")
        self.assertEqual(packages[2]["release"], "7.1.13-201.fc44.x86_64")
        self.assertEqual(len(packages), 5)

    def test_pinned_config_survives_uninstalled_original_and_detects_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = b"CONFIG_RUST=y\n"
            base = b.Baseline("7.1.13-200.fc44.x86_64", "official", b.platform.machine(),
                              "/not/installed/anymore", hashlib.sha256(data).hexdigest(), "sig", 44)
            b.write_json(root / "baseline.json", b.dataclasses.asdict(base))
            (root / "fedora-base.config").write_bytes(data)
            with patch_symbol("official_kernels", side_effect=AssertionError("must use snapshot")):
                self.assertEqual(b.choose_baseline(root), (base, data))
            (root / "fedora-base.config").write_text("CONFIG_RUST=n\n")
            with self.assertRaises(b.Error):
                b.choose_baseline(root)

    def test_modified_installed_config_is_rejected(self):
        package = {"release": "7.2.4-200.fc44.x86_64", "package": "official",
                   "arch": b.platform.machine(), "signature": "sig"}
        rows = "8\n/lib/modules/7.2.4-200.fc44.x86_64/config\t" + "a" * 64 + "\n"
        with tempfile.TemporaryDirectory() as tmp, patch_symbol("official_kernels", return_value=[package]), \
                patch_symbol("run", return_value=completed(rows)), \
                patch.object(Path, "read_bytes", return_value=b"modified"):
            with self.assertRaisesRegex(b.Error, "file digest"):
                b.choose_baseline(Path(tmp))


class PackagingTests(FedoraTestCase):
    def test_recipe_gets_installonly_and_module_development_provides(self):
        recipe = SPEC_FIXTURE.read_text()
        changed = b.adapt_rpm_spec(recipe)
        self.assertEqual(changed.count("Provides: installonlypkg(kernel)"), 2)
        self.assertIn("Provides: kernel-devel-uname-r = %{KERNELRELEASE}", changed)
        self.assertIn("\n%post\nset -e\n", changed)
        self.assertIn("Name: kernel-vanilla-local\n", changed)
        self.assertNotIn("%description -n kernel-devel", changed)
        with self.assertRaises(b.Error):
            b.adapt_rpm_spec(recipe.replace("Name: kernel", "Name: changed-upstream"))

    def test_install_command_keeps_kernels_and_repo_gpg_checks(self):
        command = b.install_command([Path("/tmp/kernel.rpm"), Path("/tmp/devel.rpm")])
        self.assertIn("--setopt=installonly_limit=0", command)
        self.assertIn("--setopt=installonlypkgs=kernel,kernel-devel,kernel-vanilla-local,kernel-vanilla-local-devel", command)
        self.assertIn("--setopt=localpkg_gpgcheck=0", command)
        self.assertNotIn("--nogpgcheck", command)
        self.assertNotIn("--allowerasing", command)
        self.assertNotIn("-y", command)

    def test_rejects_changed_rpm_or_path_escape_before_running_rpm(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "kernel.rpm"
            path.write_bytes(b"tampered")
            manifest = {"kernel_release": "7.2.4-vanilla44.20260908", "packages": [
                {"name": "kernel", "path": "kernel.rpm", "sha256": "0" * 64},
                {"name": "kernel-devel", "path": "devel.rpm", "sha256": "0" * 64}]}
            with patch_symbol("run", side_effect=AssertionError("rpm must not execute")):
                with self.assertRaisesRegex(b.Error, "changed"):
                    b.validate_packages(root, manifest)
                manifest["packages"][0]["path"] = "../../etc/passwd"
                with self.assertRaisesRegex(b.Error, "RPM path"):
                    b.validate_packages(root, manifest)


class InstallFlowTests(FedoraTestCase):
    def simulate(self, make_default=False, fail_at=None, secure="disabled", offline=False):
        release = "7.2.4-vanilla44.99999999999999999999"
        previous = "/boot/vmlinuz-7.1.13-200.fc44.x86_64"
        new = f"/boot/vmlinuz-{release}"
        initramfs = f"/boot/initramfs-{release}.img"
        installed = {"default": previous}
        commands = []
        kernels = [{"release": "7.1.13-200.fc44.x86_64", "package": "official"}]
        original_file, original_stat = Path.is_file, Path.stat

        def is_file(path):
            return str(path) in {previous, new, initramfs} or original_file(path)

        def stat(path, *args, **kwargs):
            if str(path) == initramfs:
                return types.SimpleNamespace(st_size=42)
            return original_stat(path, *args, **kwargs)

        def run(argv, **kwargs):
            command = list(map(str, argv))
            if command[-1] == "--default-kernel":
                return completed(installed["default"] + "\n")
            if command[-1].startswith("--info="):
                return completed(command[-1] + "\ninitrd=" + initramfs)
            return completed()

        def privileged(argv):
            command = list(map(str, argv))
            commands.append(command)
            if command[0] == "dnf":
                installed["default"] = new  # Simulate a Fedora kernel-install scriptlet.
            if command[0] == fail_at:
                raise b.Error("simulated failure")
            if command[0] == "grubby":
                installed["default"] = command[1].split("=", 1)[1]

        with tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
            root = Path(tmp)
            b.write_json(root / "manifest.json", {"status": "built", "schema": 1,
                         "kernel_release": release, "packages": [{"nevra": "kernel"}, {"nevra": "devel"}]})
            stack.enter_context(patch_symbol("validate_packages", return_value=[root / "kernel.rpm", root / "devel.rpm"]))
            stack.enter_context(patch_symbol("secure_boot", return_value=secure))
            stack.enter_context(patch_symbol("official_kernels", return_value=kernels))
            stack.enter_context(patch_symbol("run", side_effect=run))
            stack.enter_context(patch_symbol("privileged", side_effect=privileged))
            stack.enter_context(patch.object(b.shutil, "which", return_value="/usr/bin/program"))
            stack.enter_context(patch.object(b.shutil, "disk_usage", return_value=types.SimpleNamespace(free=2 * b.GIB)))
            stack.enter_context(patch.object(Path, "is_file", is_file))
            stack.enter_context(patch.object(Path, "stat", stat))
            if offline:
                stack.enter_context(patch_symbol("assert_no_pending_offline_updates",
                                                side_effect=b.Error("offline update pending")))
            args = argparse.Namespace(directory=root, make_default=make_default)
            with contextlib.redirect_stdout(io.StringIO()):
                if fail_at or offline or secure not in {"disabled", "not-uefi"}:
                    with self.assertRaises(b.Error):
                        b.install(args)
                else:
                    b.install(args)
            expected = new if make_default and not fail_at and not offline and secure == "disabled" else previous
            self.assertEqual(installed["default"], expected)
            if offline:
                self.assertFalse((root / "installation.json").exists())
        return commands

    def test_keeps_old_default_after_success(self):
        self.simulate()

    def test_explicitly_selects_new_default_after_success(self):
        self.simulate(make_default=True)

    def test_dnf_failure_restores_old_default(self):
        self.simulate(make_default=True, fail_at="dnf")

    def test_dracut_failure_restores_old_default(self):
        self.simulate(make_default=True, fail_at="dracut")

    def test_secure_boot_active_or_unknown_prevents_mutations(self):
        for state in ("enabled", "unknown"):
            self.assertEqual(self.simulate(secure=state), [])

    def test_offline_update_prevents_installation_and_bootloader_changes(self):
        self.assertEqual(self.simulate(offline=True), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
