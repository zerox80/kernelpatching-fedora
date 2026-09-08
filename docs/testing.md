# Tests and validation limits

Run `python3 scripts/check.py` for syntax checks and the regression suite. The tests cover:

- stable release selection, explicit RC opt-in, and input validation;
- RC build dispatch, provenance, and real signed-tag/archive verification with an isolated local Git/GPG fixture;
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

The RC integration tests generate an ephemeral signing key and a tiny local repository. They verify signed tags and detached TAR signatures, and reject unsigned, lightweight, mismatched, tampered, or untrusted tags before archiving. They require Git and GPG, use no network, and do not modify the user's repositories or keyring.

When testing `set-default`, mock the installed-kernel inventory, boot artifacts, and grubby commands. Exercise selection, cancellation, previews, an already-selected default, validation failures, and restoration after a failed change without writing to the host's boot configuration.

The host's Fedora configuration and installed kernel list have been inspected read-only, and RPM recipe parsing has been checked with `rpmspec`. No full kernel compilation, live package installation/removal, hardware test, or boot test is implied by passing this suite.
