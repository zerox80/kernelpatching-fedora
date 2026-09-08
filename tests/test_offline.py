"""Read-only offline update detection, including future or unreadable state."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from kernelpatching.errors import Error
from kernelpatching.system import offline


class OfflineTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.state = root / "state.toml"
        self.marker = root / "system-update"
        self.packagekit = root / "prepared-update"
        self.enterContext(patch.object(offline, "offline_state_paths", return_value=[self.state]))
        self.enterContext(patch.object(offline, "SYSTEM_UPDATE_MARKER", self.marker))
        self.enterContext(patch.object(offline, "PACKAGEKIT_UPDATE_MARKER", self.packagekit))

    def state_with(self, status):
        self.state.write_text('[offline-transaction-state]\n'
                              f'status = "{status}"\n'
                              'system_releasever = "44"\ntarget_releasever = "45"\n')

    def test_missing_and_incomplete_download_do_not_block(self):
        self.assertEqual(offline.pending_offline_updates(), [])
        self.state_with("download-incomplete")
        offline.assert_no_pending_offline_updates()

    def test_downloaded_scheduled_interrupted_and_future_states_block(self):
        for status in ("download-complete", "ready", "transaction-incomplete", "future-status"):
            with self.subTest(status=status):
                self.state_with(status)
                with self.assertRaisesRegex(Error, "Fedora '44' -> '45'"):
                    offline.assert_no_pending_offline_updates()
                self.assertIn(status, self.state.read_text())

    def test_invalid_or_incomplete_state_blocks(self):
        for text in ("not toml", "[other]\n", '[offline-transaction-state]\nstatus = 1\n'):
            with self.subTest(text=text):
                self.state.write_text(text)
                with self.assertRaisesRegex(Error, "Unrecognized offline update state"):
                    offline.pending_offline_updates()

    def test_unreadable_state_blocks(self):
        with patch.object(Path, "read_text", side_effect=PermissionError("denied")):
            with self.assertRaisesRegex(Error, "Cannot read offline update state"):
                offline.pending_offline_updates()

    def test_broken_system_update_link_and_packagekit_marker_block(self):
        self.marker.symlink_to(self.marker.parent / "missing-target")
        self.packagekit.touch()
        pending = offline.pending_offline_updates()
        self.assertEqual(len(pending), 2)
        self.assertIn("/system-update", pending[0])
        self.assertIn("PackageKit", pending[1])


class OfflineConfigurationTests(unittest.TestCase):
    def test_default_and_custom_state_directories_are_checked(self):
        with patch.object(offline, "run", return_value=Mock(returncode=0,
                stdout="system_state_dir = /custom/state\n")) as run:
            self.assertEqual(set(offline.offline_state_paths()), {
                Path("/custom/state/offline/offline-transaction-state.toml"),
                Path("/usr/lib/sysimage/libdnf5/offline/offline-transaction-state.toml")})
            self.assertEqual(run.call_args.args[0], ["dnf", "--dump-main-config"])

    def test_unavailable_or_unrecognized_configuration_blocks(self):
        for returncode, stdout in ((1, ""), (0, "other=value\n"), (0, "system_state_dir = relative\n")):
            with self.subTest(stdout=stdout), patch.object(offline, "run",
                    return_value=Mock(returncode=returncode, stdout=stdout)):
                with self.assertRaises(Error):
                    offline.offline_state_paths()
