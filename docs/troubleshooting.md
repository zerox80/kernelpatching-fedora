# Troubleshooting

## Pending offline update

Run `python3 fedora_vanilla_kernel.py offline-status`. A `download-complete` transaction means an update is prepared. Finish it through the software manager when ready and retry package changes after rebooting. Do not clear or invalidate a prepared update just to remove an old kernel.

## Missing dependencies or GPG

Run `deps --install` as a regular user. The command can bootstrap GPG without first loading a baseline. If an upstream release introduces new BuildRequires, inspect the generated RPM spec and `build.log`; additional distribution packages may be needed. No verification step is skipped automatically.

## No matching official Fedora kernel

A new baseline needs an installed official `kernel-core` for the current Fedora release. An old Fedora configuration is not silently reused after an OS upgrade. Install or repair the appropriate official packages through your normal Fedora package management, then retry.

## Secure Boot enabled or unknown

Building is allowed, but automatic installation is blocked. The generated EFI kernel image is not signed for your firmware trust chain. Custom EFI/MOK signing and disabling Secure Boot are outside this project's automation. Source PGP signatures and kernel-module signatures do not replace an EFI signature.

## A configuration option disappeared

Inspect `config.diff`, `config-changes.json`, and `configure.log`. Upstream may rename options or change dependencies. New options use upstream defaults, not a freshly audited Fedora selection. Loss of a required option stops the build.

## Unknown RPM recipe or manifest

The relevant interface changed or the input is not from a supported version. Update/review the adapter rather than bypassing its checks. A kernel package built for another Fedora release or architecture is rejected.

## Removal blocked

Use an exact release from `kernels`. The running kernel, boot default, and last official fallback are protected. `--dry-run` never removes packages, and build files remain after actual removal. Kernel families outside the explicit package list are not managed automatically.

## Partial installation/removal

Read the DNF output and inspect package/boot state before retrying. The application restores the previous boot default where possible but does not blindly roll back completed package actions. Do not assume a failed command means no files changed.

## External drivers

NVIDIA, VirtualBox, DKMS, and akmods modules may need rebuilding for the new kernel. The matching custom development RPM is installed, but the application does not verify third-party module builds or hardware behavior.
