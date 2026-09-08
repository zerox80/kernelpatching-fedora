# Usage

Run commands from the project directory, or pass an absolute path to `fedora_vanilla_kernel.py`. Copy the whole project when sharing it; the launcher needs the `kernelpatching` package next to it.

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
