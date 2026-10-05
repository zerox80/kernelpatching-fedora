"""Preset overrides and menu dispatch without builds or system changes."""
import contextlib
import io
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from kernelpatching import cli, menu
from kernelpatching.profiles import apply_profile


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.output = self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.errors = self.enterContext(contextlib.redirect_stderr(io.StringIO()))
        self.host = self.enterContext(patch.object(cli, "host_check"))
        self.build = self.enterContext(patch.object(cli, "build"))
        self.enterContext(patch.object(cli, "default_work_dir", return_value=Path("/tmp/test-build")))

    def test_profile_defaults_reach_build(self):
        for name, jobs, prepare, rc in (("stable", None, False, False),
                                      ("low-load", 1, False, False),
                                      ("prepare", None, True, False),
                                      ("rc", None, False, True)):
            with self.subTest(name=name):
                options = ["--version", "7.3-rc2"] if rc else []
                self.assertEqual(cli.main(["build", "--profile", name, *options]), 0)
                args = self.build.call_args.args[0]
                self.assertEqual((args.jobs, args.prepare_only, args.allow_rc), (jobs, prepare, rc))

    def test_explicit_overrides_win_independent_of_argument_order(self):
        for flags in (["--profile", "low-load", "--jobs", "4"],
                      ["--jobs", "4", "--profile", "low-load"]):
            self.assertEqual(cli.main(["build", *flags]), 0)
            self.assertEqual(self.build.call_args.args[0].jobs, 4)
        cli.main(["build", "--profile", "prepare", "--no-prepare-only"])
        self.assertFalse(self.build.call_args.args[0].prepare_only)
        cli.main(["build", "--profile", "rc", "--version", "7.2.4", "--no-allow-rc"])
        self.assertFalse(self.build.call_args.args[0].allow_rc)

    def test_rc_profile_requires_version_before_host_checks_or_build(self):
        self.assertEqual(cli.main(["build", "--profile", "rc"]), 1)
        self.host.assert_not_called()
        self.build.assert_not_called()
        self.assertIn("explicit --version", self.errors.getvalue())

    def test_profiles_and_noninteractive_no_arguments_work_without_host_checks(self):
        with patch.object(cli.sys, "stdin", Mock(isatty=lambda: False)), patch("builtins.input") as prompt:
            self.assertEqual(cli.main(["profiles"]), 0)
            self.assertEqual(cli.main([]), 0)
            self.assertEqual(cli.main(["menu"]), 1)
            prompt.assert_not_called()
        self.host.assert_not_called()
        self.assertIn("low-load", self.output.getvalue())

    def test_no_arguments_open_menu_and_allow_editing_before_dispatch(self):
        with patch.object(cli.sys, "stdin", Mock(isatty=lambda: True)), \
                patch("builtins.input", side_effect=["1", "2", "2", "3", "4", "75", "7", "s"]):
            self.assertEqual(cli.main([]), 0)
        args = self.build.call_args.args[0]
        self.assertEqual((args.profile, args.jobs, args.min_free_gib, args.prepare_only),
                         ("low-load", 3, 75, True))
        self.assertIn("Command:", self.output.getvalue())
        # The displayed command must preserve every edited setting.
        replay = cli.parser().parse_args(menu.build_arguments(args))
        apply_profile(replay)
        self.assertEqual(vars(args), vars(replay))

    def test_cancel_and_eof_never_dispatch_or_check_host(self):
        for answers in ([""], ["q"], [EOFError()], ["1", ""],
                        ["1", "1", "q"], ["1", "1", "3", EOFError()]):
            with self.subTest(answers=answers), \
                    patch.object(cli.sys, "stdin", Mock(isatty=lambda: True)), \
                    patch("builtins.input", side_effect=answers):
                self.assertEqual(cli.main([]), 0)
        self.host.assert_not_called()
        self.build.assert_not_called()

    def test_invalid_settings_reprompt_and_rc_needs_explicit_opt_in(self):
        answers = ["99", "1", "1", "2", "0", "2", "oops", "1", "7.3-rc2", "s", "8", "s"]
        with patch.object(cli.sys, "stdin", Mock(isatty=lambda: True)), \
                patch("builtins.input", side_effect=answers):
            self.assertEqual(cli.main([]), 0)
        args = self.build.call_args.args[0]
        self.assertIsNone(args.jobs)
        self.assertTrue(args.allow_rc)
        self.assertIn("positive integer", self.output.getvalue())
        self.assertIn("--allow-rc", self.output.getvalue())

    def test_rc_profile_menu_does_not_start_without_version(self):
        with patch.object(cli.sys, "stdin", Mock(isatty=lambda: True)), \
                patch("builtins.input", side_effect=["1", "4", "s", "q"]):
            self.assertEqual(cli.main([]), 0)
        self.build.assert_not_called()
        self.assertIn("explicit kernel version", self.output.getvalue())

    def test_menu_preserves_existing_lifecycle_dispatch(self):
        for number, operation in (("5", "list_kernels"), ("6", "set_boot_default"), ("7", "remove_kernel")):
            with self.subTest(operation=operation), \
                    patch.object(cli.sys, "stdin", Mock(isatty=lambda: True)), \
                    patch("builtins.input", side_effect=[number]), patch.object(cli, operation) as handler:
                self.assertEqual(cli.main(["menu"]), 0)
                handler.assert_called_once()

    def test_install_path_is_passed_literally(self):
        with patch.object(cli.sys, "stdin", Mock(isatty=lambda: True)), \
                patch("builtins.input", side_effect=["4", "/tmp/build with spaces;echo"]), \
                patch.object(cli, "install") as install:
            self.assertEqual(cli.main(["menu"]), 0)
        args = install.call_args.args[0]
        self.assertEqual(args.directory, Path("/tmp/build with spaces;echo"))
        self.assertFalse(args.make_default)
