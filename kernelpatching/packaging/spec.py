"""Packaging spec support for Fedora kernel builds."""
from __future__ import annotations

from kernelpatching.constants import PACKAGE_NAME
from kernelpatching.errors import Error
import re


def adapt_rpm_spec(text: str) -> str:
    """Adjust RPM metadata without modifying kernel source code."""
    name_pattern = r"(?m)^Name[ \t]*:[ \t]*(?:kernel|kernel-vanilla-local)[ \t]*$"
    devel_pattern = r"(?m)^%package[ \t]+(?:devel|-n[ \t]+kernel-devel)[ \t]*$"
    post_pattern = r"(?m)^%post(?:[ \t]+-p[ \t]+/bin/(?:ba)?sh)?[ \t]*$"
    if any(len(re.findall(pattern, text)) != 1
           for pattern in (name_pattern, devel_pattern, post_pattern)):
        raise Error("Unknown upstream RPM spec format; review the packaging adapter before proceeding.")
    if not re.search(r"(?:/usr/bin/)?kernel-install[ \t]+add[ \t]+%\{KERNELRELEASE\}", text):
        raise Error("The upstream RPM recipe does not use the expected kernel-install integration.")
    def inject_header(pattern: str, lines: list[str], body: str) -> str:
        match = re.search(pattern, body)
        end = re.search(r"(?m)^%description\b", body[match.end():])
        if not end:
            raise Error("An RPM package description is missing; review the new spec format.")
        header = body[match.end():match.end() + end.start()]
        # A future upstream recipe may already include these Provides.
        present = {re.sub(r"[ \t]+", " ", line.strip()) for line in header.splitlines()}
        additions = [line for line in lines if line not in present]
        return body[:match.end()] + "".join("\n" + line for line in additions) + body[match.end():]
    text = inject_header(name_pattern, ["Provides: installonlypkg(kernel)",
                         "Provides: kernel-uname-r = %{KERNELRELEASE}",
                         "Requires: kmod dracut systemd grubby"], text)
    text = inject_header(devel_pattern, ["Provides: installonlypkg(kernel)",
                         "Provides: kernel-devel-uname-r = %{KERNELRELEASE}"], text)
    # Do not allow a successful cp command to hide a preceding kernel-install failure.
    post = re.search(post_pattern, text)
    if not text[post.end():].startswith("\nset -e\n"):
        text = text[:post.end()] + "\nset -e" + text[post.end():]
    # Use separate package names so official Fedora kernels retain their own update path.
    text = re.sub(name_pattern, f"Name: {PACKAGE_NAME}", text)
    text = re.sub(r"(?m)^%(package|description|files)[ \t]+-n[ \t]+kernel-devel[ \t]*$",
                  lambda match: f"%{match[1]} devel", text)
    return text
