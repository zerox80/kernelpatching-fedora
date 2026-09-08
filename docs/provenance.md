# Signatures and provenance

## Fedora configuration baseline

The application selects a matching installed official `kernel-core` using the current Fedora release, architecture, vendor, and signing-key identifiers. Accepted Fedora keys come from the installed distribution-managed `fedora-gpg-keys` package, not arbitrary repository keys. The key files and selected configuration must match the file digests recorded in the RPM database.

This relies on a trusted local Fedora installation and RPM database. It does not re-download and cryptographically re-verify the original Fedora kernel RPM. The configuration is read from its packaged location under `/lib/modules` or `/usr/lib/modules`; `/boot/config-*` may be a ghost copy without a separate RPM digest.

## Upstream source verification

Sources and detached signatures are downloaded over HTTPS. The developer signature is verified against the **uncompressed TAR**, as specified by [kernel.org's signature instructions](https://www.kernel.org/signature.html).

Release keys are refreshed through kernel.org WKD in an isolated temporary GPG directory. Only explicitly trusted full fingerprints are accepted. Invalid, expired, revoked, unknown, or weak-hash signatures are rejected. Your normal GPG keyring is not modified.

For a legitimate future signing-key rotation, verify the full fingerprint using an authoritative source before adding:

```text
build --release-key FULL_FINGERPRINT=developer@kernel.org
```

This adds explicit trust; it does not disable verification or automatically accept arbitrary new keys. Kernel.org documents the trusted developer fingerprints and WKD procedure at the link above.

## Configuration and packaging changes

`make olddefconfig` carries compatible settings forward and applies upstream defaults to new options. The application does not run `localmodconfig`. Local changes cover the kernel release suffix, build salt, and certificate paths. Rust, BTF, and module signing are not disabled merely to simplify the build. Important configuration options are checked and all differences are recorded.

The RPM adapter changes package metadata and package names, not kernel source code. It uses `make binrpm-pkg`, excludes userspace headers from installation, and gives custom kernels a separate package namespace. Upstream BuildRequires are checked by RPM itself.

## Build records

| File | Contents |
| --- | --- |
| `PROVENANCE.txt` | Human-readable upstream version, Fedora baseline, source RPM, and patch policy |
| `manifest.json` | Target, source signer/hashes, configuration hash, package metadata and hashes |
| `fedora-original.config` | Verified configuration snapshot used for this build |
| `fedora-adapted.config` | Configuration after local settings are applied |
| `final.config` | Configuration after `olddefconfig` |
| `new-options.log` | Newly introduced configuration options |
| `config.diff`, `config-changes.json` | Baseline-to-final configuration changes |
| `signature.log`, `signature.status` | GPG verification output |
| `configure.log`, `build.log` | Configuration and compilation output |
| `packaging.diff` | Changes made to the RPM recipe |
| `installation.json` | Previous/default kernel and installation result |

No additional Fedora source patches are applied. The exact Fedora source RPM is recorded to identify the configuration's origin; identifying all source changes in the official Fedora kernel requires inspecting that matching source package/build recipe.
