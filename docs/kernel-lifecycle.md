# Kernel packages, boot selection, and removal

## Why one removal shows several packages

For an official Fedora kernel, these packages can all belong to the same release:

| Package | Role |
| --- | --- |
| `kernel` | Meta-package grouping the components; it can show zero installed bytes |
| `kernel-core` | Kernel image and core files |
| `kernel-modules-core` | A group of kernel driver modules |
| `kernel-modules` | Additional kernel driver modules |
| `kernel-modules-extra` | Extra kernel driver modules |
| `kernel-devel` | Build files for external modules targeting this kernel |

For example, if **every removal row is version `7.0.12-201.fc44`**, the selected packages belong to that old kernel. Separately installed `7.1.10` and `7.1.13` packages are different versions and are not selected by that exact removal.

The application groups packages by version, RPM release, and architecture. It excludes the global `kernel-headers` package. Custom kernels use their own main/development package pair. Unknown kernel families are not silently included.

## Removal workflow

1. Optionally run `remove --dry-run` to choose a kernel by number and preview its packages.
2. Run `remove`, choose a number, and inspect DNF's complete transaction before confirming.
3. Press Enter or type `q` at the selection prompt to cancel without changing anything.

You can still use `remove RELEASE` with an exact release from `kernels`. Numbers belong to the menu currently displayed; each new invocation reads the installed kernels again. The preview lists the other kernel versions that will be kept.

The running kernel, boot default, and last official fallback for the current Fedora release cannot be selected for removal. Use `set-default` to choose another working kernel as the default before removing the old default. If the kernel to remove is also running, reboot into another kernel first. There is no force flag to bypass these checks.

The application disables cleanup of unused dependencies for its removal transaction. DNF may still need to remove packages directly depending on the selected kernel; its transaction preview remains the authority. See [DNF5 remove](https://dnf5.readthedocs.io/en/latest/commands/remove.8.html).

Build directories, saved source RPM metadata, generated RPM files, and configuration snapshots are retained. Package removal does not clean the workspace.

## Pending offline updates

A prepared offline update is separate from the choice of kernel packages. DNF may warn that a new package transaction would invalidate an already prepared update.

The application now checks offline update state before dependency installation, kernel installation, or removal. A detected pending update blocks those actions before the DNF transaction is started. `offline-status` provides a read-only inspection without sudo. The guard also checks the effective DNF state directory, `/system-update`, and PackageKit's prepared-update marker.

Finish the prepared update through the software manager first, then retry after rebooting. Alternatively, to discard a stale or unwanted DNF offline transaction, run `sudo dnf5 offline clean`, then retry your original command. This cancels the saved DNF transaction and deletes its cached downloads; installed packages and your kernel build are retained. The error message prints this command, but the application does not run it automatically. If state is unreadable or has an unknown format, inspect `sudo dnf5 offline status` before changing packages. DNF documents offline transactions and their state location in its [offline command reference](https://dnf5.readthedocs.io/en/latest/commands/offline.8.html).

## Boot default and recovery

Run `python3 fedora_vanilla_kernel.py set-default` to choose an installed kernel by number. Enter a number, or press Enter/type `q` to cancel. Use `set-default RELEASE` for an exact release from `kernels`. Add `--dry-run` to either form to preview the change without modifying boot configuration.

The running kernel and current default are valid choices in this menu. Choosing the existing default makes no change. Before setting a new default, the application validates the selected installed kernel, its image and initramfs, and its GRUB entry. It uses `sudo grubby --set-default`, verifies the resulting default, and attempts to restore the previous default if the change fails.

Fedora's optional `$tuned_initrd` (or `${tuned_initrd}`) entry is resolved from `/boot/grub2/grubenv` using `sudo grub2-editenv`. An unset or empty value adds no initramfs; any configured TuneD overlays must exist and be nonempty, just like the kernel's matching initramfs. An unreadable GRUB environment or an unsupported variable prevents the change.

Custom-kernel selection requires disabled Secure Boot, as automatic EFI/MOK signing is not implemented. Official Fedora kernels remain selectable when Secure Boot is enabled. The underlying command is documented in the [Fedora GRUB wiki](https://fedoraproject.org/wiki/GRUB_2).

Changing the default selects the kernel for a future boot. It does not reboot, change the currently running kernel, rebuild anything, or install/remove packages. A later Fedora kernel update or release upgrade may change the default again.

Installation preserves the previous default unless `--make-default` was explicitly requested and all post-installation checks succeeded. Existing official kernels are preserved during that installation by a transaction-local `installonly_limit=0`. Ordinary later DNF operations use their own retention policy.

If installation or removal partly fails, the application attempts to restore the previous boot default. It does not blindly undo completed package operations. Read the DNF output and inspect the actual system state before retrying.
