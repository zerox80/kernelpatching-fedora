"""Numbered kernel selection and its removal workflow integration."""
import argparse
import contextlib
import io
import unittest
from unittest.mock import Mock, patch

from kernelpatching.errors import Error
from kernelpatching.operations import removal, selection
from support import patch_symbol


CURRENT = "7.1.13-200.fc44.x86_64"
OLD = "7.1.10-200.fc44.x86_64"
DEFAULT = "7.2.4-vanilla.fc44.123456"
ENTRIES = [{"release": release, "image": f"/boot/vmlinuz-{release}",
            "kind": "test kernel", "packages": [f"kernel-core-{release}"]}
           for release in (CURRENT, OLD, DEFAULT)]


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(selection.sys, "stdin", Mock(isatty=lambda: True)))
        self.output = self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def choose(self, answers):
        with patch("builtins.input", side_effect=answers):
            return selection.select_kernel(ENTRIES, CURRENT, f"/boot/vmlinuz-{DEFAULT}")

    def test_number_resolves_to_exact_displayed_release(self):
        self.assertEqual(self.choose(["2"]), OLD)
        self.assertIn("1. " + CURRENT, self.output.getvalue())
        self.assertIn("running, protected", self.output.getvalue())
        self.assertIn("boot default, protected", self.output.getvalue())

    def test_invalid_and_protected_choices_reprompt(self):
        self.assertEqual(self.choose(["1", "3", "0", "99", "-1", "7.*", "2"]), OLD)
        self.assertIn("That kernel is protected", self.output.getvalue())

    def test_empty_quit_and_end_of_input_cancel_without_a_default(self):
        for answer in ("", " ", "q", "Q", "quit", EOFError()):
            with self.subTest(answer=answer):
                self.assertIsNone(self.choose([answer]))

    def test_noninteractive_input_requires_an_explicit_release(self):
        with patch.object(selection.sys.stdin, "isatty", return_value=False):
            with self.assertRaisesRegex(Error, "interactive terminal"):
                self.choose(["2"])

    def test_empty_or_fully_protected_inventory_never_prompts(self):
        with patch("builtins.input") as prompt:
            self.assertIsNone(selection.select_kernel([], CURRENT))
            self.assertIsNone(selection.select_kernel([ENTRIES[0]], CURRENT))
            prompt.assert_not_called()

    def test_cancelling_removal_does_not_request_sudo_or_change_packages(self):
        with patch.object(removal, "kernel_inventory", return_value=ENTRIES), \
                patch.object(removal, "read_boot_default", return_value=""), \
                patch.object(removal.platform, "release", return_value=CURRENT), \
                patch.object(removal, "run") as run, \
                patch.object(removal, "privileged") as privileged, \
                patch.object(removal, "assert_no_pending_offline_updates") as offline, \
                patch("builtins.input", return_value="q"):
            removal.remove_kernel(argparse.Namespace(release=None, dry_run=False))
            run.assert_not_called()
            privileged.assert_not_called()
            offline.assert_not_called()

    def test_numbered_preview_revalidates_exact_release_after_inventory_reordering(self):
        default = f"/boot/vmlinuz-{CURRENT}"
        with patch.object(removal, "kernel_inventory", side_effect=[ENTRIES, ENTRIES[::-1]]), \
                patch.object(removal, "read_boot_default", return_value=default), \
                patch.object(removal.platform, "release", return_value=CURRENT), \
                patch.object(removal.shutil, "which", return_value="/usr/bin/tool"), \
                patch.object(removal, "assert_no_pending_offline_updates"), \
                patch.object(removal, "official_kernels", return_value=[{"release": CURRENT}]), \
                patch.object(removal.Path, "is_file", return_value=True), \
                patch.object(removal, "run", return_value=Mock(stdout=default)), \
                patch.object(removal, "privileged") as privileged, \
                patch("builtins.input", return_value="2"):
            removal.remove_kernel(argparse.Namespace(release=None, dry_run=True))
            privileged.assert_not_called()
        self.assertIn("Selected kernel: " + OLD, self.output.getvalue())
        self.assertIn("Other installed kernel versions to keep:", self.output.getvalue())

    def test_selection_disappearing_during_menu_never_retargets_another_kernel(self):
        with patch.object(removal, "kernel_inventory", side_effect=[ENTRIES, [ENTRIES[0]]]), \
                patch.object(removal, "read_boot_default", return_value=""), \
                patch.object(removal.platform, "release", return_value=CURRENT), \
                patch.object(removal, "run") as run, \
                patch.object(removal, "privileged") as privileged, \
                patch("builtins.input", return_value="2"):
            with self.assertRaisesRegex(Error, "Kernel not found"):
                removal.remove_kernel(argparse.Namespace(release=None, dry_run=False))
            run.assert_not_called()
            privileged.assert_not_called()

    def test_pending_offline_update_blocks_removal_before_sudo(self):
        with patch.object(removal, "kernel_inventory", return_value=ENTRIES), \
                patch.object(removal.platform, "release", return_value=CURRENT), \
                patch.object(removal.shutil, "which", return_value="/usr/bin/tool"), \
                patch_symbol("pending_offline_updates", return_value=["prepared update"]), \
                patch.object(removal, "run") as run, \
                patch.object(removal, "privileged") as privileged:
            with self.assertRaisesRegex(Error, "offline update is pending"):
                removal.remove_kernel(argparse.Namespace(release=OLD, dry_run=False))
            run.assert_not_called()
            privileged.assert_not_called()
