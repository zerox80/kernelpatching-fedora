"""Create RC source archives from verified upstream Git tags."""
from __future__ import annotations

from pathlib import Path
import os
import re

from kernelpatching.constants import RC_VERSION_RE, RELEASE_KEYS
from kernelpatching.errors import Error
from kernelpatching.kernel.releases import validate_version
from kernelpatching.security.signatures import release_keyring, signature_fingerprint
from kernelpatching.system.console import say
from kernelpatching.system.process import environment, logged, run


UPSTREAM_GIT_URL = "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git"
OBJECT_ID_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


def git_environment() -> dict[str, str]:
    """Do not inherit repository locations, config injection, or URL rewrites."""
    env = {key: value for key, value in environment().items() if not key.startswith("GIT_")}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_SYSTEM": os.devnull,
                "GIT_CONFIG_GLOBAL": os.devnull, "GIT_ATTR_NOSYSTEM": "1",
                "GIT_NO_REPLACE_OBJECTS": "1", "GIT_TERMINAL_PROMPT": "0"})
    return env


def verified_git_archive(version: str, directory: Path,
                         keys: dict[str, str] | None = None) -> tuple[Path, str, dict[str, str]]:
    validate_version(version, allow_rc=True)
    if not RC_VERSION_RE.fullmatch(version):
        raise Error("Git source verification expects an explicit release candidate version.")
    keys = RELEASE_KEYS if keys is None else keys
    tag = f"v{version}"
    ref = f"refs/tags/{tag}"
    repository = directory / "upstream.git"
    env = git_environment()
    # An empty template and isolated config avoid local hooks and attributes.
    run(["git", "init", "--bare", "--template=", repository], env=env)
    git = ["git", f"--git-dir={repository}", "-c", f"core.hooksPath={os.devnull}",
           "-c", f"core.attributesFile={os.devnull}", "-c", "gc.auto=0",
           "-c", "protocol.allow=never", "-c", "protocol.https.allow=always",
           "-c", "http.followRedirects=false", "-c", "fetch.fsckObjects=true"]
    say(f"Fetching release candidate {tag} from {UPSTREAM_GIT_URL}")
    logged([*git, "fetch", "--depth=1", "--no-tags", "--no-recurse-submodules",
            UPSTREAM_GIT_URL, f"{ref}:{ref}"], directory, directory / "source.log", env=env)
    # Pin the tag object before verification; never archive a mutable ref.
    tag_object = run([*git, "rev-parse", "--verify", f"{ref}^{{tag}}"], env=env).stdout.strip()
    if not OBJECT_ID_RE.fullmatch(tag_object):
        raise Error("The upstream release tag did not resolve to a Git tag object.")
    with release_keyring(directory, keys) as keyring:
        verified = run([*git, "-c", "gpg.format=openpgp", "-c", "gpg.openpgp.program=gpg",
                        "verify-tag", "--raw", tag_object],
                       env=env | {"GNUPGHOME": str(keyring)}, check=False, timeout=180)
        (directory / "signature.status").write_text(verified.stderr, encoding="utf-8")
        with (directory / "signature.log").open("a", encoding="utf-8") as log:
            log.write(verified.stdout + verified.stderr)
        signer = signature_fingerprint(verified.stderr, verified.returncode, keys)
    contents = run([*git, "cat-file", "tag", tag_object], env=env).stdout
    header = contents.split("\n\n", 1)[0].splitlines()
    if (len(header) != 4 or not header[0].startswith("object ")
            or header[1] != "type commit" or header[2] != f"tag {tag}"
            or not header[3].startswith("tagger ")
            or not OBJECT_ID_RE.fullmatch(header[0][7:])):
        raise Error("The signed Git tag does not name the requested release and a commit.")
    commit = header[0][7:]
    (directory / "upstream-tag.txt").write_text(contents, encoding="utf-8")
    archive = directory / f"linux-{version}.tar"
    logged([*git, "archive", "--format=tar", f"--prefix=linux-{version}/",
            f"--output={archive}", commit], directory, directory / "source.log", env=env)
    say(f"Valid kernel Git tag signature: {signer}\nVerified commit: {commit}")
    return archive, signer, {"upstream_git_tag": tag, "upstream_git_tag_object": tag_object,
                             "upstream_git_commit": commit}
