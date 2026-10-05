"""Regression coverage for Fedora/Rustup toolchain mixing and early checks."""
import contextlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from kernelpatching import cli
from kernelpatching.errors import Error
from kernelpatching.kernel import configuration
from kernelpatching.operations import build as build_operation
from kernelpatching.packaging import rpms
from kernelpatching.profiles import apply_profile
from kernelpatching.system import rust


CONFIG = b"CONFIG_RUST=y\nCONFIG_MODULES=y\nCONFIG_BLK_DEV_INITRD=y\nCONFIG_DEVTMPFS=y\n"


class RustToolchainTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.library = self.directory / "lib/rustlib/src/rust/library"
        self.core = self.library / "core/src/lib.rs"
        self.core.parent.mkdir(parents=True)
        self.core.write_text("// test core source\n")
        self.enterContext(patch.object(rust.os, "access", return_value=True))
        self.enterContext(patch.object(rust.Path, "is_file", return_value=True))
        self.run = self.enterContext(patch.object(rust, "run", side_effect=self.command))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def command(self, argv):
        values = {("/usr/bin/rustc", "--version"): "rustc 1.98.1 (Fedora)",
                  ("/usr/bin/rustdoc", "--version"): "rustdoc 1.98.1 (Fedora)",
                  ("/usr/bin/bindgen", "--version"): "bindgen 0.72.1",
                  ("/usr/bin/rustc", "--print", "sysroot"): str(self.directory)}
        return Mock(stdout=values[tuple(argv)])

    def test_shadowing_rustup_and_inherited_source_path_cannot_select_toolchain(self):
        with patch.dict(os.environ, {"PATH": "/home/example/.cargo/bin:/usr/bin",
                                     "RUSTC": "/broken/rustc", "HOSTRUSTC": "/broken/rustc",
                                     "RUST_LIB_SRC": "/missing/core"}):
            toolchain = rust.fedora_rust_toolchain()
        self.assertEqual(toolchain.rustc, "/usr/bin/rustc")
        self.assertEqual(toolchain.library, str(self.library))
        self.assertIn("HOSTRUSTC=/usr/bin/rustc", toolchain.make_arguments())
        self.assertIn(f"RUST_LIB_SRC={self.library}", toolchain.make_arguments())
        self.assertEqual(self.run.call_count, 4)

    def test_missing_or_nonexecutable_tools_do_not_fall_back_to_path(self):
        for attribute in ("is_file", "access"):
            owner = rust.Path if attribute == "is_file" else rust.os
            with self.subTest(attribute=attribute), patch.object(owner, attribute, return_value=False):
                with self.assertRaisesRegex(Error, "deps --install"):
                    rust.fedora_rust_toolchain()
        self.run.assert_not_called()

    def test_missing_empty_or_unreadable_core_sources_fail_early(self):
        self.core.unlink()
        with self.assertRaisesRegex(Error, "sources are missing or unreadable"):
            rust.fedora_rust_toolchain()
        self.core.touch()
        with self.assertRaisesRegex(Error, "sources are empty"):
            rust.fedora_rust_toolchain()
        with patch.object(rust.Path, "open", side_effect=PermissionError("unreadable")):
            with self.assertRaisesRegex(Error, "sources are missing or unreadable"):
                rust.fedora_rust_toolchain()

    def test_mismatched_rustdoc_version_is_rejected(self):
        def command(argv):
            if argv == ["/usr/bin/rustdoc", "--version"]:
                return Mock(stdout="rustdoc 1.97.1")
            return self.command(argv)
        self.run.side_effect = command
        with self.assertRaisesRegex(Error, "versions do not match"):
            rust.fedora_rust_toolchain()

    def test_malformed_version_and_unsafe_sysroot_are_rejected(self):
        self.run.return_value = Mock(stdout="unexpected")
        self.run.side_effect = None
        with self.assertRaisesRegex(Error, "Unexpected version"):
            rust.fedora_rust_toolchain()
        def command(argv):
            if argv[-1] == "sysroot":
                return Mock(stdout="/tmp/$(unexpected)")
            return self.command(argv)
        self.run.side_effect = command
        with self.assertRaisesRegex(Error, "Unsupported.*sysroot"):
            rust.fedora_rust_toolchain()

    def test_build_fails_before_source_download_when_core_sources_are_missing(self):
        self.core.unlink()
        args = cli.parser().parse_args(["build", "--profile", "rc", "--version", "7.3-rc6"])
        apply_profile(args)
        work = self.directory / "work"
        with patch.object(build_operation, "choose_baseline", return_value=(Mock(), CONFIG)), \
                patch.object(build_operation, "missing_packages", return_value=[]), \
                patch.object(build_operation, "verified_git_archive") as fetch, \
                patch.object(build_operation, "verified_tarball") as tarball, \
                patch.object(build_operation, "latest_version") as latest, \
                patch.object(build_operation, "configure") as configure:
            with self.assertRaisesRegex(Error, "core sources"):
                build_operation.build(args, work)
        fetch.assert_not_called()
        tarball.assert_not_called()
        latest.assert_not_called()
        configure.assert_not_called()
        self.assertEqual(list(work.glob("linux-*")), [])

    def test_check_reports_missing_core_even_when_rpms_are_installed(self):
        self.core.unlink()
        base = Mock(release="test", sha256="test", source_rpm="test")
        with patch.object(cli, "host_check"), \
                patch.object(cli, "choose_baseline", return_value=(base, CONFIG)), \
                patch.object(cli, "missing_packages", return_value=[]), \
                patch.object(cli, "fedora_version", return_value=44), \
                patch.object(cli, "secure_boot", return_value="disabled"), \
                contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(cli.main(["check", "--work-dir", str(self.directory)]), 1)
        self.assertIn("core sources", errors.getvalue())

    def test_configuration_and_packaging_keep_the_checked_toolchain(self):
        toolchain = rust.fedora_rust_toolchain()
        tree = self.directory / "source"
        tree.mkdir()
        suffix = "-vanilla.fc44.test"
        with patch.object(configuration, "logged") as logged, \
                patch.object(configuration, "run", return_value=Mock(stdout="7.3.0" + suffix)):
            release, make = configuration.configure(tree, self.directory, CONFIG, suffix, 2,
                                                    rust_toolchain=toolchain)
        for call in logged.call_args_list:
            for argument in toolchain.make_arguments():
                self.assertIn(argument, call.args[0])
        self.assertEqual(logged.call_args_list[0].args[0][-1], "rustavailable")
        spec = tree / "scripts/package/kernel.spec"
        spec.parent.mkdir(parents=True)
        spec.write_text((Path(__file__).parent / "fixtures/kernel.spec").read_text())
        with patch.object(rpms, "logged", side_effect=Error("stop before building")) as package:
            with self.assertRaisesRegex(Error, "stop before building"):
                rpms.build_packages(tree, self.directory, make, release)
        for argument in toolchain.make_arguments():
            self.assertIn(argument, package.call_args.args[0])

    def test_non_rust_baseline_does_not_require_rust_tools(self):
        tree = self.directory / "source"
        tree.mkdir()
        config = CONFIG.replace(b"CONFIG_RUST=y", b"# CONFIG_RUST is not set")
        with patch.object(configuration, "fedora_rust_toolchain") as select, \
                patch.object(configuration, "logged") as logged, \
                patch.object(configuration, "run", return_value=Mock(stdout="7.3.0-vanilla.test")):
            configuration.configure(tree, self.directory, config, "-vanilla.test", 1)
        select.assert_not_called()
        self.assertFalse(any(call.args[0][-1] == "rustavailable" for call in logged.call_args_list))

    def test_pinned_assignments_survive_recursive_make_and_hostile_environment(self):
        toolchain = rust.fedora_rust_toolchain()
        # Exercise GNU make's inheritance, as used by Kbuild and its RPM recipe.
        (self.directory / "Makefile").write_text(
            "all:\n\t$(MAKE) -f child.mk\n")
        (self.directory / "child.mk").write_text(
            "RUSTC = rustc\nHOSTRUSTC = rustc\nRUSTDOC = rustdoc\nBINDGEN = bindgen\n"
            "RUST_LIB_SRC ?= wrong\n"
            "all:\n\t@printf '%s\\n' '$(RUSTC)' '$(HOSTRUSTC)' '$(RUSTDOC)' '$(BINDGEN)' '$(RUST_LIB_SRC)'\n")
        result = subprocess.run(["make", "--no-print-directory", *toolchain.make_arguments()],
                                cwd=self.directory, capture_output=True, text=True, timeout=10,
                                env=dict(os.environ, RUSTC="rustup", RUST_LIB_SRC="wrong", MAKEFLAGS=""))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[-5:], ["/usr/bin/rustc", "/usr/bin/rustc",
                         "/usr/bin/rustdoc", "/usr/bin/bindgen", str(self.library)])
