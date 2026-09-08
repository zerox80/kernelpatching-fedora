# Fedora Vanilla Kernel

Build a stable upstream Linux kernel using an official Fedora configuration, verify its source signature, package it as RPMs, and manage installed kernel versions.

The project uses Python's standard library at runtime. Its code, CLI messages, documentation, and filenames are in English. Keep the entire project folder together: the root Python file is a launcher for the modules in `kernelpatching/`.

## Quick start

Open a terminal in this project folder:

```bash
python3 fedora_vanilla_kernel.py check
python3 fedora_vanilla_kernel.py deps --install
python3 fedora_vanilla_kernel.py build
```

Each `build` automatically selects the **latest stable kernel from kernel.org**. You only need `--version` when deliberately choosing a specific version. There is no background updater: run `build` again when you want another kernel.

Do not run the whole application with sudo. Builds run as your regular user; explicitly requested package changes use sudo and DNF, and boot-default changes use sudo and grubby. A successful build prints its exact installation command. Nothing reboots automatically.

## Commands

| Command | Purpose |
| --- | --- |
| `check` | Inspect the host, configuration baseline, and build dependencies |
| `deps` | Print the dependency installation command |
| `deps --install` | Install build dependencies through DNF |
| `build` | Download verified sources, configure, and build local RPMs |
| `build --prepare-only` | Stop after source verification and configuration |
| `install BUILD_DIRECTORY` | Install a completed build after validation |
| `kernels` | List installed Fedora and custom kernel versions |
| `set-default` | Choose the default boot kernel by number |
| `set-default KERNEL_RELEASE` | Set an installed kernel as the boot default by exact release |
| `set-default --dry-run` | Choose a kernel by number and preview the boot-default change |
| `set-default KERNEL_RELEASE --dry-run` | Preview a boot-default change for an exact release |
| `remove --dry-run` | Choose a kernel by number and preview its component packages |
| `remove` | Choose a kernel by number, then review DNF's removal confirmation |
| `remove KERNEL_RELEASE --dry-run` | Preview the packages belonging to one selected kernel |
| `remove KERNEL_RELEASE` | Remove that selected kernel through DNF confirmation |
| `offline-status` | Inspect pending offline updates without changing them |

All commands provide `--help`. You can also use `python3 -m kernelpatching` from this directory.

Use `set-default` to choose which installed kernel boots by default at the next restart. Enter a number, or press Enter/type `q` to cancel. It does not reboot or rebuild the kernel. See [boot selection and recovery](docs/kernel-lifecycle.md#boot-default-and-recovery) for validation and recovery behavior.

## Requirements and limits

The target is a numbered Fedora release **44 or newer**, Python **3.12 or newer**, and a native **x86_64 or aarch64** build. Automatic installation supports the conventional Fedora GRUB/kernel-install/Dracut setup with Secure Boot disabled. Atomic/rpm-ostree systems and Rawhide development branches are excluded.

Fedora versions and distribution signing keys are detected dynamically. There is no hardcoded upper Fedora version, but compatibility with untested future releases is not guaranteed. Changes to build tools, package recipes, configuration dependencies, or boot interfaces may require maintenance.

Builds require at least 50 GiB free by default. More than 100 GiB of headroom can be useful with Fedora's broad configuration; this is a planning estimate, not an upper bound. Builds may take hours. CPU parallelism is limited using available CPU and RAM information.

## Kernel removal means one version

Fedora splits a kernel into several packages. Removing `kernel`, `kernel-core`, `kernel-devel`, and several `kernel-modules*` packages **with the same version** removes that one kernel and its components. It does not mean removing every installed kernel.

The running kernel, boot default, and last official fallback for the current Fedora release are protected. Package changes are also blocked while a prepared offline update is detected. Read [kernel lifecycle](docs/kernel-lifecycle.md) before your first removal.

Run `python3 fedora_vanilla_kernel.py remove` to open the numbered menu. Enter one number; press Enter or type `q` to cancel. You can still pass an exact kernel release when preferred.

## Documentation

- [Usage and examples](docs/usage.md)
- [Fedora upgrades and future compatibility](docs/fedora-upgrades.md)
- [Kernel packages, boot selection, and removal](docs/kernel-lifecycle.md)
- [Signatures and configuration provenance](docs/provenance.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Module structure and development](docs/development.md)
- [Tests and validation limits](docs/testing.md)

## Development

```bash
python3 scripts/check.py
```

No tests perform a real kernel installation, removal, bootloader change, or reboot. The implementation includes a compatibility launcher, dedicated modules, local fixtures, and regression tests. Full kernel builds and boot tests are still required before claiming support for a particular hardware and Fedora combination.
