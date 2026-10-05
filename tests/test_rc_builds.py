"""RC opt-in, source provenance, and real offline Git/GPG verification."""
import contextlib
import hashlib
import io
import json
import lzma
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import types
import unittest
from unittest.mock import patch

from kernelpatching import cli
from kernelpatching.constants import GIB, PACKAGE_NAME, RELEASE_KEYS
from kernelpatching.errors import Error
from kernelpatching.kernel import releases
from kernelpatching.kernel.sources import extract_sources
from kernelpatching.models import Baseline
from kernelpatching.operations import build as build_operation
from kernelpatching.operations import inventory
from kernelpatching.security import git_sources, signatures
from kernelpatching.storage.manifests import validate_target
from kernelpatching.system import process
from support import patch_symbol


class RCVersionTests(unittest.TestCase):
    def test_explicit_rc_opt_in_preserves_exact_version(self):
        for version in ("6.12-rc1", "7.0-rc1", "7.3-rc2", "7.3-rc12"):
            with self.subTest(version=version):
                with self.assertRaisesRegex(Error, "--allow-rc"):
                    releases.validate_version(version)
                self.assertEqual(releases.validate_version(version, allow_rc=True), version)
        for version in ("6.12", "7.2.4"):
            self.assertEqual(releases.validate_version(version, allow_rc=True), version)

    def test_opt_in_still_rejects_other_revisions_and_injection(self):
        for version in ("7.3-rc0", "7.3-rc01", "7.3-rc", "7.3-rc-2", "7.3-RC2",
                        "7.3.1-rc2", "7.3-rc2-next", "v7.3-rc2", "next-20260908",
                        "6.11-rc7", "5.15-rc1", "../7.3-rc2", "7.3-rc2/../x",
                        "7.3-rc2;id", "7.3-rc$(id)", "7.3-rc2\n"):
            with self.subTest(version=version), self.assertRaises(Error):
                releases.validate_version(version, allow_rc=True)

    def test_rejected_rc_does_not_create_workspace_or_load_baseline(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(build_operation, "choose_baseline") as base:
            work = Path(tmp) / "unused"
            args = cli.parser().parse_args(["build", "--version", "7.3-rc2"])
            with self.assertRaisesRegex(Error, "--allow-rc"):
                build_operation.build(args, work)
            base.assert_not_called()
            self.assertFalse(work.exists())


class RCBuildWorkflowTests(unittest.TestCase):
    def simulate(self, options, *, rust_enabled=False):
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        work = Path(temporary)
        config = b"CONFIG_MODULES=y\n"
        toolchain = None
        if rust_enabled:
            from kernelpatching.system.rust import RustToolchain
            config += b"CONFIG_RUST=y\n"
            toolchain = RustToolchain("/usr/bin/rustc", "/usr/bin/rustdoc", "/usr/bin/bindgen",
                                      "/usr/lib/rustlib/src/rust/library", "1.98.1", "0.72.1")
        self.enterContext(patch.object(build_operation, "fedora_rust_toolchain", return_value=toolchain))
        baseline = Baseline("7.2.4-200.fc44.x86_64", "official", "x86_64", "/config",
                            hashlib.sha256(config).hexdigest(), "sig", 44, "kernel.src.rpm")
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.enterContext(patch.object(cli, "host_check"))
        self.enterContext(patch_symbol("fedora_version", return_value=44))
        self.enterContext(patch.object(build_operation.platform, "machine", return_value="x86_64"))
        self.enterContext(patch.object(build_operation, "choose_baseline", return_value=(baseline, config)))
        self.enterContext(patch.object(build_operation, "missing_packages", return_value=[]))
        self.enterContext(patch.object(build_operation.shutil, "disk_usage", return_value=types.SimpleNamespace(free=100 * GIB)))
        self.enterContext(patch.object(build_operation, "secure_boot", return_value="disabled"))
        self.enterContext(patch.object(build_operation, "job_count", return_value=1))
        metadata = {"latest_stable": {"version": "7.2.4"}, "releases": [
            {"version": "7.3-rc2", "moniker": "mainline", "iseol": False},
            {"version": "7.2.4", "moniker": "stable", "iseol": False}]}
        self.enterContext(patch.object(releases.urllib.request, "urlopen",
                                      side_effect=lambda *a, **kw: io.BytesIO(json.dumps(metadata).encode())))

        def archive(version, directory, keys):
            path = directory / f"linux-{version}.tar"
            with tarfile.open(path, "w") as tar:
                for name in ("Makefile", "scripts/config"):
                    member = tarfile.TarInfo(f"linux-{version}/{name}")
                    member.size = len(config)
                    tar.addfile(member, io.BytesIO(config))
            return path, next(iter(RELEASE_KEYS))

        git_metadata = {"upstream_git_tag": "v7.3-rc2", "upstream_git_tag_object": "a" * 40,
                        "upstream_git_commit": "b" * 40}
        stable = self.enterContext(patch.object(build_operation, "verified_tarball", side_effect=archive))
        rc = self.enterContext(patch.object(build_operation, "verified_git_archive",
                                            side_effect=lambda *a: (*archive(*a), git_metadata)))

        def configure(tree, directory, config, suffix, jobs, *, rust_toolchain=None):
            self.assertIs(rust_toolchain, toolchain)
            (tree / ".config").write_bytes(config)
            return ("7.3.0-rc2" if "--version" in options else "7.2.4") + suffix, ["make"]

        self.enterContext(patch.object(build_operation, "configure", side_effect=configure))
        packages = self.enterContext(patch.object(build_operation, "build_packages", return_value=[]))
        result = cli.main(["build", "--work-dir", str(work), *options])
        self.assertEqual(result, 0)
        manifest_path, = work.glob("linux-*/manifest.json")
        return json.loads(manifest_path.read_text()), manifest_path.parent, stable, rc, packages

    def test_rc_build_dispatch_and_provenance(self):
        manifest, directory, stable, rc, packages = self.simulate(["--version", "7.3-rc2", "--allow-rc"])
        stable.assert_not_called()
        rc.assert_called_once_with("7.3-rc2", directory, RELEASE_KEYS)
        packages.assert_called_once()
        self.assertEqual(manifest["status"], "built")
        self.assertEqual(manifest["upstream_version"], "7.3-rc2")
        self.assertRegex(manifest["kernel_release"], r"^7\.3\.0-rc2\.vanilla\.fc44\.[0-9]+$")
        self.assertTrue(manifest["release_candidate"])
        self.assertEqual(manifest["upstream_source_url"], git_sources.UPSTREAM_GIT_URL)
        self.assertEqual(manifest["source_verification"], "signed-git-tag")
        self.assertEqual(manifest["upstream_git_commit"], "b" * 40)
        self.assertEqual(manifest["source_tar_sha256"], hashlib.sha256((directory / "linux-7.3-rc2.tar").read_bytes()).hexdigest())
        self.assertIn("Verified Git tag: v7.3-rc2", (directory / "PROVENANCE.txt").read_text())

    def test_prepare_only_verifies_rc_without_building_packages(self):
        manifest, _, stable, rc, packages = self.simulate(["--version", "7.3-rc2", "--allow-rc", "--prepare-only"])
        self.assertEqual(manifest["status"], "prepared")
        stable.assert_not_called()
        rc.assert_called_once()
        packages.assert_not_called()

    def test_checked_rust_toolchain_reaches_configuration_and_manifest(self):
        manifest, _, _, _, _ = self.simulate(["--version", "7.3-rc2", "--allow-rc"], rust_enabled=True)
        self.assertEqual(manifest["rust_toolchain"]["rustc"], "/usr/bin/rustc")
        self.assertEqual(manifest["rust_toolchain"]["library"], "/usr/lib/rustlib/src/rust/library")

    def test_no_version_remains_latest_stable_with_or_without_opt_in(self):
        for flags in ([], ["--allow-rc"]):
            with self.subTest(flags=flags):
                manifest, directory, stable, rc, _ = self.simulate(flags + ["--prepare-only"])
                stable.assert_called_once_with("7.2.4", directory, RELEASE_KEYS)
                rc.assert_not_called()
                self.assertFalse(manifest["release_candidate"])
                self.assertEqual(manifest["source_verification"], "detached-tar-signature")
                self.assertEqual(manifest["upstream_source_url"], "https://cdn.kernel.org/pub/linux/kernel/v7.x/linux-7.2.4.tar.xz")


class RCLifecycleTests(unittest.TestCase):
    RELEASE = "7.3.0-rc2.vanilla.fc44.123456"

    def setUp(self):
        self.enterContext(patch_symbol("fedora_version", return_value=44))
        self.enterContext(patch.object(inventory.platform, "machine", return_value="x86_64"))

    def test_rc_manifest_target_accepts_local_release_and_rejects_wrong_fedora(self):
        manifest = {"schema": 2, "target": {"fedora_version": 44, "architecture": "x86_64"},
                    "kernel_release": self.RELEASE}
        validate_target(manifest)
        manifest["target"]["fedora_version"] = 45
        with self.assertRaisesRegex(Error, "kernel release"):
            validate_target(manifest)

    def test_inventory_keeps_rc_main_and_devel_packages_together(self):
        version = self.RELEASE.replace("-", "_")
        lines, expected = [], []
        for name in (PACKAGE_NAME, PACKAGE_NAME + "-devel"):
            nevra = f"{name}-{version}-1.fc44.x86_64"
            capability = "kernel-devel" if name.endswith("-devel") else "kernel"
            lines.append(f"{name}|{version}|1.fc44|x86_64|{nevra}|{capability}-uname-r={self.RELEASE};")
            expected.append(nevra)
        with patch.object(inventory, "run", return_value=types.SimpleNamespace(stdout="\n".join(lines))):
            entry, = inventory.kernel_inventory()
        self.assertEqual(entry["release"], self.RELEASE)
        self.assertEqual(entry["packages"], sorted(expected))
        self.assertEqual(entry["image"], f"/boot/vmlinuz-{self.RELEASE}")


@unittest.skipUnless(shutil.which("git") and shutil.which("gpg"), "Git and GPG are required")
class SignedSourceIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.keyring = cls.root / "keys"
        cls.keyring.mkdir(mode=0o700)
        cls.env = git_sources.git_environment() | {"GNUPGHOME": str(cls.keyring)}
        cls.gpg = ["gpg", "--no-options", "--homedir", str(cls.keyring), "--batch", "--pinentry-mode", "loopback", "--passphrase", ""]
        if shutil.which("gpgconf"):
            cls.addClassCleanup(lambda: subprocess.run(["gpgconf", "--homedir", str(cls.keyring), "--kill", "gpg-agent"],
                                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10))
        cls.command([*cls.gpg, "--quick-generate-key", "RC fixture <fixture@kernel.org>", "ed25519", "sign", "0"])
        keys = cls.command([*cls.gpg, "--with-colons", "--list-keys"]).stdout
        cls.fingerprint = next(line.split(":")[9] for line in keys.splitlines() if line.startswith("fpr:"))
        cls.public_key = cls.root / "public.asc"
        cls.command([*cls.gpg, "--armor", "--output", str(cls.public_key), "--export", cls.fingerprint])
        cls.repo = cls.root / "repo"
        cls.command(["git", "init", "--template=", str(cls.repo)])
        cls.git = ["git", "-C", str(cls.repo), "-c", "user.name=RC fixture",
                   "-c", "user.email=fixture@kernel.org", "-c", f"core.hooksPath={os.devnull}",
                   "-c", "gpg.format=openpgp", "-c", "gpg.openpgp.program=gpg"]
        (cls.repo / "scripts").mkdir()
        (cls.repo / "Makefile").write_text("signed kernel\n")
        (cls.repo / "scripts/config").write_text("signed config tool\n")
        cls.command([*cls.git, "add", "."])
        cls.command([*cls.git, "-c", "commit.gpgSign=false", "commit", "-m", "Fixture"])
        cls.commit = cls.command([*cls.git, "rev-parse", "HEAD"]).stdout.strip()
        cls.command([*cls.git, "tag", "-u", cls.fingerprint, "v7.3-rc2", "-m", "Synthetic RC"])
        cls.tag_object = cls.command([*cls.git, "rev-parse", "refs/tags/v7.3-rc2"]).stdout.strip()
        cls.command([*cls.git, "tag", "-a", "v7.3-rc3", "-m", "Unsigned"])
        cls.command([*cls.git, "tag", "v7.3-rc4"])
        cls.command([*cls.git, "update-ref", "refs/tags/v7.3-rc5", cls.tag_object])
        tag = cls.command([*cls.git, "cat-file", "tag", cls.tag_object]).stdout
        tampered = cls.command([*cls.git, "hash-object", "-t", "tag", "-w", "--stdin"],
                               input=tag.replace("Synthetic RC", "Modified RC")).stdout.strip()
        cls.command([*cls.git, "update-ref", "refs/tags/v7.3-rc6", tampered])
        (cls.repo / "Makefile").write_text("newer untagged kernel\n")
        cls.command([*cls.git, "-c", "commit.gpgSign=false", "commit", "-am", "Later changes"])

    @classmethod
    def command(cls, argv, **kwargs):
        return subprocess.run(argv, env=cls.env, text=True, capture_output=True, check=True, timeout=30, **kwargs)

    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))

        def import_fixture(argv, **kwargs):
            # Replace only WKD key discovery, retaining the real isolated keyring and GPG verification.
            if "--locate-external-keys" in argv:
                argv = [*argv[:argv.index("--auto-key-locate")], "--import", self.public_key]
            return process.run(argv, **kwargs)

        def local_fetch(argv, cwd, logfile, **kwargs):
            if "fetch" in argv:
                self.assertIn(git_sources.UPSTREAM_GIT_URL, argv)
                index = argv.index("fetch")
                argv = [*argv[:index], "-c", "protocol.file.allow=always", *argv[index:]]
                argv[argv.index(git_sources.UPSTREAM_GIT_URL)] = self.repo.as_uri()
            return process.logged(argv, cwd, logfile, **kwargs)

        self.enterContext(patch.object(signatures, "run", side_effect=import_fixture))
        self.enterContext(patch.object(git_sources, "logged", side_effect=local_fetch))
        self.keys = {self.fingerprint: "fixture@kernel.org"}

    def test_signed_tag_archives_exact_commit_with_isolated_caller_settings(self):
        caller_keys = self.directory / "caller-keys"
        caller_keys.mkdir()
        with patch.dict(os.environ, {"GIT_DIR": "/nonexistent", "GIT_CONFIG_GLOBAL": "/nonexistent/config",
                                     "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "gpg.openpgp.program",
                                     "GIT_CONFIG_VALUE_0": "/does-not-exist", "GNUPGHOME": str(caller_keys)}):
            archive, signer, metadata = git_sources.verified_git_archive("7.3-rc2", self.directory, self.keys)
        self.assertEqual(list(caller_keys.iterdir()), [])
        self.assertEqual(signer, self.fingerprint)
        self.assertEqual(metadata, {"upstream_git_tag": "v7.3-rc2", "upstream_git_tag_object": self.tag_object,
                                    "upstream_git_commit": self.commit})
        tree = extract_sources(archive, self.directory / "extracted", "7.3-rc2")
        self.assertEqual((tree / "Makefile").read_text(), "signed kernel\n")
        self.assertIn("BEGIN PGP SIGNATURE", (self.directory / "upstream-tag.txt").read_text())
        self.assertIn("VALIDSIG", (self.directory / "signature.status").read_text())

    def test_unsigned_lightweight_mismatched_and_tampered_tags_never_archive(self):
        for version in ("7.3-rc3", "7.3-rc4", "7.3-rc5", "7.3-rc6"):
            with self.subTest(version=version):
                directory = self.directory / version
                directory.mkdir()
                with self.assertRaises(Error):
                    git_sources.verified_git_archive(version, directory, self.keys)
                self.assertFalse((directory / f"linux-{version}.tar").exists())

    def test_valid_signature_from_untrusted_key_never_archives(self):
        with self.assertRaisesRegex(Error, "explicitly trusted"):
            git_sources.verified_git_archive("7.3-rc2", self.directory, {"D" * 40: "fixture@kernel.org"})
        self.assertFalse((self.directory / "linux-7.3-rc2.tar").exists())

    def test_missing_tag_stops_before_verification_and_archiving(self):
        with self.assertRaises(Error):
            git_sources.verified_git_archive("7.3-rc99", self.directory, self.keys)
        self.assertFalse((self.directory / "signature.status").exists())
        self.assertFalse((self.directory / "linux-7.3-rc99.tar").exists())

    def test_stable_tar_signatures_still_verify_the_uncompressed_archive(self):
        original = self.directory / "original.tar"
        original.write_bytes(b"TAR bytes verified before extraction")
        signature = self.directory / "original.sign"
        self.command([*self.gpg, "--detach-sign", "--output", str(signature), str(original)])

        def download(url, destination, limit):
            self.assertTrue(url.startswith("https://cdn.kernel.org/pub/linux/kernel/v7.x/linux-7.2.4.tar."))
            destination.write_bytes(signature.read_bytes() if url.endswith(".sign") else lzma.compress(original.read_bytes()))

        with patch.object(signatures, "download", side_effect=download):
            archive, signer = signatures.verified_tarball("7.2.4", self.directory, self.keys)
            self.assertEqual(archive.read_bytes(), original.read_bytes())
            self.assertEqual(signer, self.fingerprint)
            original.write_bytes(b"tampered TAR bytes")
            with self.assertRaises(Error):
                signatures.verified_tarball("7.2.4", self.directory, self.keys)
