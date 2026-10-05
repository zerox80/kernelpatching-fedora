# Troubleshooting

## Pending offline update

Run `python3 fedora_vanilla_kernel.py offline-status`. A `download-complete` transaction means an update is prepared. Finish it through the software manager when ready and retry package changes after rebooting. Do not clear or invalidate a prepared update just to remove an old kernel.

## Missing dependencies or GPG

Run `deps --install` as a regular user. The command can bootstrap GPG without first loading a baseline. If an upstream release introduces new BuildRequires, inspect the generated RPM spec and `build.log`; additional distribution packages may be needed. No verification step is skipped automatically.

## Rustup installed alongside Fedora Rust

Kernel builds explicitly use `/usr/bin/rustc`, `/usr/bin/rustdoc`, and `/usr/bin/bindgen` from the Fedora dependency packages. A Rustup installation earlier in `PATH` does not replace them. The Rust library source path is derived from that compiler's sysroot and pinned for configuration and RPM packaging, together with the host Rust compiler.

For Rust-enabled Fedora configurations, `check` verifies these tools and the readable `core` sources. `build` performs the same checks before fetching kernel sources and records the selected toolchain in `manifest.json`. Missing tools or sources stop early with a dependency-repair message. Use `deps --install` for missing packages; if installed package files are damaged, repair the Fedora packages named in the error.

Older application versions could report missing `core/src/lib.rs` under `~/.rustup` even when Fedora's `rust-src` package was installed. Update the application and retry; no Rustup component installation is needed for the Fedora build workflow. A retry creates a new build directory.

The verified kernel's `make rustavailable` check still runs before configuration to validate that release's Rust/bindgen/libclang requirements. Passing the initial dependency checks does not guarantee compatibility with every future kernel release.

## No matching official Fedora kernel

A new baseline needs an installed official `kernel-core` for the current Fedora release. An old Fedora configuration is not silently reused after an OS upgrade. Install or repair the appropriate official packages through your normal Fedora package management, then retry.

## Release candidate rejected or fetch failed

Use both options: `build --version 7.3-rc2 --allow-rc`. Run `deps --install` if Git is missing. The version must name an existing upstream mainline RC tag; a missing tag or interrupted fetch stops the build. Inspect `source.log` for fetch failures and `signature.log`/`signature.status` for verification failures. RC sources require a valid signed Git tag; no unsigned download fallback is used.

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
