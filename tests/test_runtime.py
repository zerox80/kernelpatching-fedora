"""CLI entry points and bounded downloads without network or package changes."""
import contextlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from kernelpatching import cli
from kernelpatching.errors import Error
from kernelpatching.network import downloads
from kernelpatching.packaging.spec import adapt_rpm_spec
from support import SCRIPT, SPEC_FIXTURE, patch_symbol


class Response(io.BytesIO):
    def __init__(self, data, url="https://cdn.kernel.org/test", length=None):
        super().__init__(data)
        self.url = url
        self.headers = {} if length is None else {"Content-Length": str(length)}

    def geturl(self):
        return self.url


class DownloadTests(unittest.TestCase):
    def test_completed_download_replaces_destination_and_removes_temporary_file(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            destination = Path(tmp) / "source.tar.xz"
            with patch.object(downloads.urllib.request, "urlopen", return_value=Response(b"verified-later", length=14)):
                downloads.download("https://cdn.kernel.org/test", destination, 100)
            self.assertEqual(destination.read_bytes(), b"verified-later")
            self.assertFalse(destination.with_suffix(".xz.part").exists())

    def test_oversize_incomplete_or_unencrypted_download_preserves_existing_file(self):
        cases = [(b"abcdef", "https://cdn.kernel.org/test", 6, 3),
                 (b"abc", "https://cdn.kernel.org/test", 6, 100),
                 (b"abc", "http://example.org/test", 3, 100)]
        for data, url, length, limit in cases:
            with self.subTest(url=url, limit=limit), tempfile.TemporaryDirectory() as tmp, \
                    contextlib.redirect_stdout(io.StringIO()):
                destination = Path(tmp) / "source.tar.xz"
                destination.write_bytes(b"existing")
                with patch.object(downloads.urllib.request, "urlopen", return_value=Response(data, url, length)):
                    with self.assertRaises(Error):
                        downloads.download("https://cdn.kernel.org/test", destination, limit)
                self.assertEqual(destination.read_bytes(), b"existing")
                self.assertFalse(destination.with_suffix(".xz.part").exists())


class CommandTests(unittest.TestCase):
    def test_remove_accepts_menu_or_exact_release(self):
        args = cli.parser().parse_args(["remove", "--dry-run"])
        self.assertIsNone(args.release)
        self.assertTrue(args.dry_run)
        args = cli.parser().parse_args(["remove", "7.1.10-200.fc44.x86_64"])
        self.assertEqual(args.release, "7.1.10-200.fc44.x86_64")

    def test_launcher_and_package_cli_work_in_fresh_processes(self):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        for command in ([sys.executable, str(SCRIPT), "--help"],
                        [sys.executable, "-m", "kernelpatching", "remove", "--help"]):
            with self.subTest(command=command):
                result = subprocess.run(command, cwd=SCRIPT.parent, env=env,
                                        text=True, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("remove", result.stdout)

    def test_offline_update_blocks_dependency_installation(self):
        with patch.object(cli, "host_check"), \
                patch_symbol("pending_offline_updates", return_value=["prepared update"]), \
                patch.object(cli, "privileged") as privileged, \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(cli.main(["deps", "--install"]), 1)
            privileged.assert_not_called()
            self.assertIn("offline update is pending", stderr.getvalue())

    @unittest.skipUnless(shutil.which("rpmspec"), "rpmspec is not installed")
    def test_adapted_recipe_parses_as_separate_main_and_devel_packages(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = Path(tmp) / "kernel.spec"
            spec.write_text(adapt_rpm_spec(SPEC_FIXTURE.read_text()))
            result = subprocess.run(["rpmspec", "--parse", "--define", "with_devel 1",
                                     "--define", "KERNELRELEASE 7.2.4-vanilla.fc44.123456", str(spec)],
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Name: kernel-vanilla-local", result.stdout)
            self.assertIn("Provides: kernel-devel-uname-r", result.stdout)
