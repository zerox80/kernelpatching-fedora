# Usage

Run commands from the project directory, or pass an absolute path to `fedora_vanilla_kernel.py`. Copy the whole project when sharing it; the launcher needs the `kernelpatching` package next to it.

## Interactive menu and profiles

Run `python3 fedora_vanilla_kernel.py` without arguments, or add `menu`, to choose an action by number. The build action offers four presets:

| Profile | Settings |
| --- | --- |
| `stable` | Latest stable version, automatic CPU/RAM-based job count, build RPMs |
| `low-load` | Latest stable version, one compiler job, build RPMs |
| `prepare` | Latest stable version, automatic jobs, stop after configuration |
| `rc` | RC opt-in enabled, explicit version required, automatic jobs, build RPMs |

All profiles use the Fedora configuration baseline and default to requiring 50 GiB free. `low-load` reduces compiler concurrency; it does not impose CPU or RAM limits or change kernel tuning.

After selecting a profile, edit any displayed setting by number. Entries 6–8 toggle baseline refresh, preparation only, and RC opt-in. Enter keeps a value while editing; `-` resets it to the preset default. Enter at a selection menu or `q` cancels. Only `s` starts the configured build. The equivalent command is printed for reuse. Edits apply to the current run and are not saved as personal profiles.

The menu also exposes checks, dependency installation, completed-build installation, installed kernels, boot selection, removal, and offline-update status. Existing validation and DNF confirmation still apply. Installation from the menu keeps the existing boot default.

For scripts or repeat runs:

```bash
python3 fedora_vanilla_kernel.py profiles
python3 fedora_vanilla_kernel.py build --profile low-load
python3 fedora_vanilla_kernel.py build --profile low-load --jobs 2
python3 fedora_vanilla_kernel.py build --profile prepare
python3 fedora_vanilla_kernel.py build --profile rc --version 7.3-rc2
python3 fedora_vanilla_kernel.py build --profile rc --version 7.3-rc2 --prepare-only
```

Explicit options override profile defaults regardless of argument order. Use `--no-prepare-only` or `--no-allow-rc` to turn off a preset switch. Version numbers are examples. The `rc` profile requires a version and does not automatically discover the latest RC. Ordinary `build --allow-rc` without a version continues to select latest stable.

Without an interactive terminal, no arguments print help, and `menu` reports that a terminal is required. `profiles` works without a terminal or a supported Fedora host. Build records include the selected preset and effective workflow options.

## Build

```bash
python3 fedora_vanilla_kernel.py check
python3 fedora_vanilla_kernel.py deps --install
python3 fedora_vanilla_kernel.py build
```

On a minimal system without GPG, start with `deps --install`. `deps` alone only prints the command. `check` exits with status 1 if a prerequisite is missing.

The default workspace is `$XDG_STATE_HOME/fedora-vanilla-kernel/fedora-VERSION-ARCHITECTURE`, or `~/.local/state/fedora-vanilla-kernel/fedora-VERSION-ARCHITECTURE` when `XDG_STATE_HOME` is not set. `check` prints the actual absolute path.

```bash
python3 fedora_vanilla_kernel.py build --work-dir /path/with/enough/space
python3 fedora_vanilla_kernel.py build --version 7.2.4 --jobs 4
python3 fedora_vanilla_kernel.py build --prepare-only
python3 fedora_vanilla_kernel.py build --refresh-base
```

The version number above is an example, not a recommendation to pin an old release. Omit `--version` to discover the latest stable version on every invocation. `--jobs` overrides automatic CPU/RAM sizing. `--refresh-base` selects a fresh installed official Fedora configuration.

Build paths must use ASCII letters, digits, slashes, dots, hyphens, and underscores. Spaces and shell-special characters are rejected because the upstream Makefiles and RPM macros do not consistently support them.

Every build gets a new directory. `--prepare-only` also needs the build tools, but stops before compilation and packaging. Automatic resume is not implemented: a later build creates a new run. Ctrl+C stops a compiler build and its child processes while retaining files and logs.

### Mainline release candidates

Use an explicit version and opt in to prereleases:

```bash
python3 fedora_vanilla_kernel.py deps --install
python3 fedora_vanilla_kernel.py build --version 7.3-rc2 --allow-rc
```

The version is an example; choose an existing upstream `MAJOR.MINOR-rcN` tag with a base version of 6.12 or newer. RC numbers start at 1. Arbitrary Git revisions, linux-next snapshots, and stable-review versions such as `7.2.4-rc1` are not supported. Without `--allow-rc`, an RC version is rejected with the required command. Without `--version`, even `--allow-rc` continues to select the latest stable release.

RC builds require Git, included in `deps --install`. They fetch just the requested tag and its source tree over HTTPS, without the full kernel history. The tag signature, trusted fingerprint, and signed tag name are checked before creating a local TAR archive. The commit, tag object, and archive hash are recorded in the build manifest. See [source provenance](provenance.md#upstream-sources).

An RC kernel release looks like `7.3.0-rc2.vanilla.fc44.TIMESTAMP`. The local suffix is joined with a dot because RPM versioned dependencies accept only one hyphen. Final releases retain their `-vanilla.fc44.TIMESTAMP` suffix. The upstream source version and tag are unchanged.

Add `--prepare-only` to stop after verification and configuration; a subsequent build starts a new run. RCs can introduce build or driver incompatibilities. Keep an official Fedora kernel available for booting back into. Installation and boot selection use the same commands and checks as stable builds.

## Install

Copy the exact installation command printed after a successful build:

```bash
python3 fedora_vanilla_kernel.py install /absolute/path/to/build
```

The application checks the Fedora target, architecture, RPM metadata, and recorded hashes. It installs only `kernel-vanilla-local` and `kernel-vanilla-local-devel`. Any generated userspace header RPM is excluded.

DNF displays the resolved transaction and requests confirmation. The application then verifies module dependency generation, initramfs creation, and the GRUB entry. It restores the previous default kernel unless `--make-default` was explicitly requested and installation completed successfully.

```bash
python3 fedora_vanilla_kernel.py install /absolute/path/to/build --make-default
```

No automatic reboot is performed. External modules such as NVIDIA or VirtualBox may require a separate rebuild before testing the new kernel.

## Change the boot default

```bash
python3 fedora_vanilla_kernel.py set-default
python3 fedora_vanilla_kernel.py set-default --dry-run
python3 fedora_vanilla_kernel.py set-default KERNEL_RELEASE
python3 fedora_vanilla_kernel.py set-default KERNEL_RELEASE --dry-run
```

Omit the release to choose an installed kernel from a numbered menu. Enter a number, or press Enter/type `q` to cancel. Both the running kernel and the current boot default are selectable. Selecting the existing default makes no change.

For an explicit command, replace `KERNEL_RELEASE` with an exact value from `kernels`. Scripts without an interactive terminal must supply the exact release. `--dry-run` previews the change without modifying boot configuration.

The application checks the installed kernel, kernel image, initramfs, and GRUB entry before setting the default with `sudo grubby --set-default`. It reads back the result to verify the change and attempts to restore the previous default if the change fails. Sudo may also be needed for boot-entry inspection.

Selecting a custom kernel requires Secure Boot to be disabled, matching the installation policy. Official Fedora kernels remain selectable with Secure Boot enabled.

This chooses the default for a future boot; the currently running kernel stays active until you reboot. The command does not reboot, install or remove packages, or rebuild a kernel. Normal Fedora kernel updates or release upgrades may change the default again later. You can still use `install --make-default` to select a newly built kernel during its installation.

## Inspect and remove

```bash
python3 fedora_vanilla_kernel.py kernels
python3 fedora_vanilla_kernel.py remove --dry-run
python3 fedora_vanilla_kernel.py remove
python3 fedora_vanilla_kernel.py remove KERNEL_RELEASE --dry-run
python3 fedora_vanilla_kernel.py remove KERNEL_RELEASE
python3 fedora_vanilla_kernel.py offline-status
```

Omit the release to open a numbered menu. Enter a number to select that kernel, or press Enter/type `q` to cancel. No kernel is selected by default. The menu marks the running kernel and any readable boot default as protected; the full removal checks run after selection. An inventory change never redirects a selected number to another kernel.

For an explicit command, replace `KERNEL_RELEASE` with an exact value from `kernels`. Scripts without an interactive terminal must supply the exact release. The removal preview does not resolve additional DNF dependencies. The actual command shows the complete DNF transaction before confirmation. Sudo may be needed to read the boot default reliably.

## Existing version 1 or 2 data

Old `./kernel-build` workspaces are not moved automatically. Reuse one explicitly with `--work-dir /absolute/path/to/kernel-build`. Legacy v1 manifests and package names remain recognized on Fedora 44. Existing builds are not renamed; new builds use the current package naming scheme.

Older builds may contain German log text and `HERKUNFT.txt`; historical build records are preserved. New builds write English output and `PROVENANCE.txt`.
