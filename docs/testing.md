# Tests and validation limits

Run `python3 scripts/check.py` for syntax checks and the regression suite. The tests cover:

- stable release selection and input validation;
- known, unknown, expired, revoked, and rotated signing keys;
- archive traversal/link protections and download checks;
- Fedora baseline provenance and snapshot tampering;
- simulated Fedora release upgrades and architecture changes;
- matching build targets and RPM metadata;
- recipe adaptation and separate package names;
- installation failure handling and boot-default restoration;
- exact kernel removal, protected kernels, previews, and removal failures;
- numbered selection, cancellation, invalid input, and inventory changes during selection;
- pending offline updates, unknown/unreadable state, and mutation blocking;
- English CLI entry points and module imports.

Mocked workflow tests do not install or remove packages, cancel offline updates, change the bootloader, or reboot. Future Fedora version tests validate the selection logic only; they are not full builds on those releases.

The host's Fedora configuration and installed kernel list have been inspected read-only, and RPM recipe parsing has been checked with `rpmspec`. No full kernel compilation, live package installation/removal, hardware test, or boot test is implied by passing this suite.
