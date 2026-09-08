# Development and module layout

The root launcher preserves the original command name. The `kernelpatching` package holds the implementation; its modules can also be invoked through the package CLI with `python3 -m kernelpatching`.

```text
kernelpatching-fedora/
  fedora_vanilla_kernel.py
  pyproject.toml
  kernelpatching/
    cli.py                 Argument parsing and command dispatch
    constants.py           Defaults and trusted release fingerprints
    errors.py              User-facing exception type
    models.py              Baseline metadata model
    system/                Host, process, dependency, RPM, boot and offline state helpers
    network/               Bounded HTTPS downloads
    security/              Fedora key discovery and upstream signature verification
    kernel/                Releases, source extraction, baselines and configuration
    packaging/             RPM recipe adaptation, building and validation
    storage/               File hashes and build manifests
    operations/            Build, install, inventory, numbered selection and removal
  docs/
  examples/
  scripts/
  tests/
    fixtures/
```

Package-changing workflows are explicitly selected CLI commands. Builds do not escalate privileges. Offline-update checks, provenance checks, and removal protections must remain active when adding features.

## Local checks

```bash
python3 scripts/check.py
python3 -m unittest discover -s tests -v
```

The regression suite uses standard-library unittest. Workflow tests inject dependencies at each module import site through `tests/support.py`, preserving the existing behavioral checks after modularization. The RPM adapter fixture is synthetic and never used to build a real kernel. A parser test uses `rpmspec` when it is available.

## Optional installation

Running from the project folder does not require installation. To use the `kernelpatching` console command, create a virtual environment and install this local project with pip. The build backend uses setuptools; there are no third-party runtime dependencies.

Do not package personal build directories, generated signing keys, or machine-specific configuration snapshots when sharing the source project.
