# Fedora upgrades and kernel versions

The Fedora operating system release, the installed kernel packages, and the kernel selected by the bootloader are separate pieces of state.

## Example: custom 7.2.x on Fedora 44, then Fedora 45

A normal Fedora upgrade can install an official Fedora 45 kernel and change the boot default. Your custom 7.2.x kernel is not recompiled, renamed, or given Fedora 45 patches by that operation. If its packages are retained, it can remain as another boot entry. The bootloader decides which installed kernel starts; `uname -r` reports the running one.

Use `python3 fedora_vanilla_kernel.py set-default` to choose an installed kernel as the default for a future boot. This selection does not prevent later Fedora package operations from changing the default again.

The custom RPMs use separate `kernel-vanilla-local` package names so official Fedora packages retain their own update path. Retention during a future DNF transaction still depends on that transaction and its install-only policy.

The next `build` after the OS upgrade detects Fedora 45 and selects a matching **installed official Fedora 45 kernel configuration**. Default workspaces are separated by Fedora release and architecture. An explicitly reused workspace is also checked, so a Fedora 44 snapshot is not silently reused on Fedora 45.

If no suitable official package is installed, the build stops. The application does not automatically perform a Fedora upgrade or install an official kernel to obtain a new baseline.

An RPM build targeted at Fedora 44 is rejected by `install` on Fedora 45. Build again on the upgraded system. This restriction does not claim that an already installed older kernel is necessarily unbootable; it prevents accidentally installing a build for a different target.

## Configuration survives removal

The verified configuration is copied to `fedora-base.config` and recorded in `baseline.json`. Each build also gets `fedora-original.config`. Removing the original kernel package does not delete these separate snapshots.

Within a single Fedora release, the saved baseline remains pinned. Use `build --refresh-base` to deliberately select a newer installed official configuration. You may additionally specify an exact installed release with `--base-kernel`.

## Future releases and patches

Numbered Fedora releases from 44 upward are accepted without a fixed upper bound. Fedora signing keys are read from the distribution-managed `fedora-gpg-keys` package for the detected release. Legacy and newer RPM signature query formats are handled.

These mechanisms remove annual version/key hardcoding. They cannot guarantee that an untested future release has compatible package names, toolchains, Kconfig dependencies, RPM recipes, or boot integration. Unknown structures fail with an error instead of bypassing verification.

Each default `build` discovers the latest stable upstream release. A new upstream patch version arrives as a complete source archive containing that release's fixes. **Fedora source patches are not transplanted into upstream Linux.** Copying a Fedora configuration does not copy Fedora's source changes. For the complete official Fedora patch set, use its matching source package/build tree, as described in [Fedora's custom kernel guide](https://fedoraproject.org/wiki/Building_a_custom_kernel).
