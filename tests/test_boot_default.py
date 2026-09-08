"""Default boot selection with simulated GRUB state and no real boot changes."""
import argparse
import contextlib
import io
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from kernelpatching import cli
from kernelpatching.errors import Error
from kernelpatching.operations import boot_default, selection


OFFICIAL = "7.1.13-200.fc44.x86_64"
CUSTOM = "7.2.4-vanilla.fc44.123456"
PREVIOUS = f"/boot/vmlinuz-{OFFICIAL}"
TARGET = f"/boot/vmlinuz-{CUSTOM}"
ENTRIES = [{"release": release, "image": f"/boot/vmlinuz-{release}",
            "kind": kind, "packages": [f"test-{release}"]}
           for release, kind in ((OFFICIAL, "Fedora kernel-core"), (CUSTOM, "custom vanilla kernel"))]


def boot_info(image):
    release = Path(image).name.removeprefix("vmlinuz-")
    return f'index=0\nkernel="{image}"\ninitrd="/boot/initramfs-{release}.img"\ntitle="Test kernel"\n'


class BootDefaultTests(unittest.TestCase):
    def setUp(self):
        self.current = PREVIOUS
        self.output = self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.inventory = self.enterContext(patch.object(boot_default, "kernel_inventory", return_value=ENTRIES))
        self.enterContext(patch.object(boot_default, "read_boot_default", return_value=PREVIOUS))
        self.enterContext(patch.object(boot_default.platform, "release", return_value=OFFICIAL))
        self.secure_boot = self.enterContext(patch.object(boot_default, "secure_boot", return_value="disabled"))
        self.enterContext(patch.object(boot_default.shutil, "which", return_value="/usr/bin/tool"))
        self.is_file = self.enterContext(patch.object(Path, "is_file", return_value=True))
        self.enterContext(patch.object(Path, "stat", return_value=Mock(st_size=100)))
        self.run = self.enterContext(patch.object(boot_default, "run", side_effect=self.read_grubby))
        self.privileged = self.enterContext(patch.object(boot_default, "privileged", side_effect=self.write_grubby))

    def read_grubby(self, command):
        self.assertEqual(command[:3], ["sudo", "--", "grubby"])
        if command[-1] == "--default-kernel":
            return Mock(stdout=self.current + "\n")
        self.assertTrue(command[-1].startswith("--info="))
        return Mock(stdout=boot_info(command[-1].removeprefix("--info=")))

    def write_grubby(self, command):
        self.assertEqual(command[0], "grubby")
        self.assertTrue(command[1].startswith("--set-default="))
        self.current = command[1].removeprefix("--set-default=")

    def execute(self, release=CUSTOM, dry_run=False):
        boot_default.set_boot_default(argparse.Namespace(release=release, dry_run=dry_run))

    def test_changes_and_verifies_the_default_without_other_mutations(self):
        self.execute()
        self.assertEqual(self.current, TARGET)
        self.privileged.assert_called_once_with(["grubby", f"--set-default={TARGET}"])
        self.assertIn("Boot default changed to: " + CUSTOM, self.output.getvalue())

    def test_preview_reads_entries_without_writing(self):
        self.execute(dry_run=True)
        self.privileged.assert_not_called()
        self.assertEqual(self.current, PREVIOUS)
        self.assertIn(f"--set-default={TARGET}", self.output.getvalue())

    def test_tuned_initrd_is_supported_for_target_and_previous_default(self):
        def read(command):
            if command == ["sudo", "--", "grub2-editenv", "/boot/grub2/grubenv", "list"]:
                return Mock(stdout="tuned_initrd=\n")
            result = self.read_grubby(command)
            if command[-1].startswith("--info="):
                result.stdout = result.stdout.replace('.img"', '.img $tuned_initrd"')
            return result
        self.run.side_effect = read
        self.execute()
        self.assertEqual(self.current, TARGET)
        self.privileged.assert_called_once_with(["grubby", f"--set-default={TARGET}"])

    def test_already_default_is_a_noop(self):
        self.execute(release=OFFICIAL)
        self.privileged.assert_not_called()
        self.assertIn("Already the boot default", self.output.getvalue())

    def test_custom_kernel_is_blocked_when_secure_boot_is_active_or_unknown(self):
        for state in ("enabled", "unknown"):
            with self.subTest(state=state):
                self.secure_boot.return_value = state
                with self.assertRaisesRegex(Error, "Secure Boot"):
                    self.execute()
        self.run.assert_not_called()
        self.privileged.assert_not_called()

    def test_official_kernel_remains_selectable_with_secure_boot_enabled(self):
        self.current = TARGET
        self.secure_boot.return_value = "enabled"
        self.execute(release=OFFICIAL)
        self.assertEqual(self.current, PREVIOUS)
        self.privileged.assert_called_once_with(["grubby", f"--set-default={PREVIOUS}"])

    def test_invalid_unknown_or_ambiguous_selection_never_requests_sudo(self):
        for release in ("../kernel", "7.*", "7.9-missing"):
            with self.subTest(release=release), self.assertRaises(Error):
                self.execute(release=release)
        self.inventory.return_value = ENTRIES + [ENTRIES[1]]
        with self.assertRaisesRegex(Error, "not found uniquely"):
            self.execute()
        self.run.assert_not_called()
        self.privileged.assert_not_called()

    def test_missing_target_image_prevents_changes(self):
        self.is_file.side_effect = lambda path=None: False
        with self.assertRaisesRegex(Error, "image is missing"):
            self.execute()
        self.run.assert_not_called()
        self.privileged.assert_not_called()

    def test_command_failure_restores_previous_default(self):
        def fail(command):
            self.write_grubby(command)
            if self.current == TARGET:
                raise Error("simulated grubby failure")
        self.privileged.side_effect = fail
        with self.assertRaisesRegex(Error, "simulated grubby failure"):
            self.execute()
        self.assertEqual(self.current, PREVIOUS)
        self.assertEqual(self.privileged.call_count, 2)
        self.assertIn("previous boot default was restored", self.output.getvalue())

    def test_wrong_readback_restores_previous_default(self):
        def ignore_first_change(command):
            if command[1] != f"--set-default={TARGET}":
                self.write_grubby(command)
        self.privileged.side_effect = ignore_first_change
        with self.assertRaisesRegex(Error, "did not match"):
            self.execute()
        self.assertEqual(self.current, PREVIOUS)
        self.assertEqual(self.privileged.call_count, 2)

    def test_failed_restoration_reports_both_failures_and_recovery_command(self):
        self.privileged.side_effect = [Error("write failed"), Error("restore failed")]
        with self.assertRaises(Error) as raised:
            self.execute()
        message = str(raised.exception)
        for expected in ("write failed", "restore failed", f"sudo grubby --set-default={PREVIOUS}"):
            self.assertIn(expected, message)

    def test_interrupt_after_mutation_restores_previous_default(self):
        def interrupt(command):
            self.write_grubby(command)
            if self.current == TARGET:
                raise KeyboardInterrupt
        self.privileged.side_effect = interrupt
        with self.assertRaises(KeyboardInterrupt):
            self.execute()
        self.assertEqual(self.current, PREVIOUS)

    def test_menu_choice_keeps_exact_release_after_inventory_reordering(self):
        self.inventory.side_effect = [ENTRIES, ENTRIES[::-1]]
        with patch.object(selection.sys, "stdin", Mock(isatty=lambda: True)), \
                patch("builtins.input", return_value="2"):
            self.execute(release=None)
        self.assertEqual(self.current, TARGET)

    def test_menu_cancellation_does_not_request_sudo(self):
        with patch.object(selection.sys, "stdin", Mock(isatty=lambda: True)), \
                patch("builtins.input", return_value="q"):
            self.execute(release=None)
        self.run.assert_not_called()
        self.privileged.assert_not_called()

    def test_menu_selection_disappearing_never_selects_another_kernel(self):
        self.inventory.side_effect = [ENTRIES, [ENTRIES[0]]]
        with patch.object(selection.sys, "stdin", Mock(isatty=lambda: True)), \
                patch("builtins.input", return_value="2"):
            with self.assertRaisesRegex(Error, "not found uniquely"):
                self.execute(release=None)
        self.run.assert_not_called()
        self.privileged.assert_not_called()


class BootEntryTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(Path, "is_file", return_value=True))
        self.stat = self.enterContext(patch.object(Path, "stat", return_value=Mock(st_size=100)))

    def validate(self, output, grubenv=""):
        def read(command):
            if command == ["sudo", "--", "grubby", f"--info={TARGET}"]:
                return Mock(stdout=output)
            self.assertEqual(command, ["sudo", "--", "grub2-editenv", "/boot/grub2/grubenv", "list"])
            if isinstance(grubenv, Error):
                raise grubenv
            return Mock(stdout=grubenv)
        with patch.object(boot_default, "run", side_effect=read) as run:
            boot_default.validate_boot_entry(Path(TARGET))
        return run

    def test_literal_initrds_do_not_require_reading_grub_environment(self):
        run = self.validate(boot_info(TARGET))
        run.assert_called_once_with(["sudo", "--", "grubby", f"--info={TARGET}"])

    def test_unset_and_empty_tuned_initrd_are_optional(self):
        for token in ("$tuned_initrd", "${tuned_initrd}"):
            for grubenv in ("saved_entry=test\n", "tuned_initrd=\nsaved_entry=test\n"):
                with self.subTest(token=token, grubenv=grubenv):
                    output = boot_info(TARGET).replace('.img"', f'.img {token}"')
                    self.validate(output, grubenv)

    def test_tuned_initrd_overlays_are_resolved_and_checked(self):
        output = boot_info(TARGET).replace('.img"', '.img $tuned_initrd"')
        expected = [TARGET, f"/boot/initramfs-{CUSTOM}.img", "/boot/tuned.img", "/boot/extra.img"]
        checked = []
        def is_file(path):
            checked.append(str(path))
            return str(path) in expected
        with patch.object(Path, "is_file", is_file):
            self.validate(output, "tuned_params=ignored\ntuned_initrd=/tuned.img /boot/extra.img\n")
        self.assertEqual(checked, expected)

    def test_missing_or_empty_tuned_overlay_is_rejected(self):
        output = boot_info(TARGET).replace('.img"', '.img $tuned_initrd"')
        for missing in (True, False):
            with self.subTest(missing=missing), \
                    patch.object(Path, "is_file", lambda path: not missing or path.name != "tuned.img"), \
                    patch.object(Path, "stat", lambda path: Mock(st_size=0 if path.name == "tuned.img" else 100)):
                with self.assertRaisesRegex(Error, "initramfs file is missing or empty"):
                    self.validate(output, "tuned_initrd=/tuned.img\n")

    def test_tuned_initrd_cannot_replace_the_matching_kernel_initramfs(self):
        output = boot_info(TARGET).replace(f"/boot/initramfs-{CUSTOM}.img", "$tuned_initrd")
        for grubenv in ("tuned_initrd=\n", "tuned_initrd=/tuned.img\n"):
            with self.subTest(grubenv=grubenv), self.assertRaisesRegex(Error, "matching initramfs"):
                self.validate(output, grubenv)

    def test_invalid_tuned_environment_is_rejected(self):
        output = boot_info(TARGET).replace('.img"', '.img $tuned_initrd"')
        for grubenv in ("tuned_initrd=/../etc/passwd\n", "tuned_initrd=relative.img\n",
                        "tuned_initrd=$unknown\n", "tuned_initrd=/boot/$unknown\n",
                        "tuned_initrd=/one.img\ntuned_initrd=/two.img\n", 'tuned_initrd="\n',
                        Error("Cannot read GRUB environment")):
            with self.subTest(grubenv=grubenv), self.assertRaises(Error):
                self.validate(output, grubenv)

    def test_unknown_grub_variables_are_rejected(self):
        for token in ("$unknown", "${unknown}", "$tuned_initrd_suffix", "/boot/$unknown"):
            output = boot_info(TARGET).replace('.img"', f'.img {token}"')
            with self.subTest(token=token), self.assertRaisesRegex(Error, "Unrecognized GRUB initramfs path"):
                self.validate(output)

    def test_exact_image_and_matching_initramfs_are_required(self):
        good = boot_info(TARGET)
        cases = ["", good.replace(TARGET, TARGET + "-other"),
                 good.replace(f"initramfs-{CUSTOM}.img", "wrong-initramfs.img"),
                 good + good, good + 'kernel="duplicate"\n']
        for output in cases:
            with self.subTest(output=output), self.assertRaises(Error):
                self.validate(output)

    def test_multiple_initramfs_files_are_checked(self):
        self.validate(boot_info(TARGET).replace('initrd="', 'initrd="/boot/microcode.img '))
        self.assertEqual(self.stat.call_count, 3)

    def test_bls_additional_initramfs_paths_resolve_under_boot(self):
        output = boot_info(TARGET).replace(f'{CUSTOM}.img"', f'{CUSTOM}.img /extra.img"')
        def is_file(path):
            return str(path) in {TARGET, f"/boot/initramfs-{CUSTOM}.img", "/boot/extra.img"}
        with patch.object(Path, "is_file", is_file):
            self.validate(output)

    def test_missing_additional_initramfs_and_traversal_are_rejected(self):
        for extra in ("/missing.img", "/../etc/passwd", "relative.img"):
            output = boot_info(TARGET).replace(f'{CUSTOM}.img"', f'{CUSTOM}.img {extra}"')
            with self.subTest(extra=extra), patch.object(Path, "is_file",
                    lambda path: path.name != "missing.img"), self.assertRaises(Error):
                self.validate(output)

    def test_empty_initramfs_is_rejected(self):
        self.stat.side_effect = [Mock(st_size=100), Mock(st_size=0)]
        with self.assertRaisesRegex(Error, "initramfs file is missing or empty"):
            self.validate(boot_info(TARGET))


class BootDefaultCommandTests(unittest.TestCase):
    def test_cli_dispatches_numbered_and_exact_selection_with_preview(self):
        for arguments in (["set-default"], ["set-default", CUSTOM, "--dry-run"]):
            with self.subTest(arguments=arguments), patch.object(cli, "host_check"), \
                    patch.object(cli, "set_boot_default") as operation:
                self.assertEqual(cli.main(arguments), 0)
                args = operation.call_args.args[0]
                self.assertEqual(args.release, None if len(arguments) == 1 else CUSTOM)
                self.assertEqual(args.dry_run, len(arguments) > 1)
