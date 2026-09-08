"""System process support for Fedora kernel builds."""
from __future__ import annotations

from kernelpatching.errors import Error
from kernelpatching.system.console import say
from pathlib import Path
import os
import shlex
import signal
import subprocess


def environment() -> dict[str, str]:
    env = os.environ.copy()
    # Prevent inherited Kbuild/Make settings from overriding the verified configuration.
    for key in list(env):
        if key.startswith(("KBUILD_", "KCONFIG_", "RPM")) or key in {
            "MAKEFLAGS", "MFLAGS", "GNUMAKEFLAGS", "MAKEFILES", "ARCH", "SUBARCH",
            "CROSS_COMPILE", "LLVM", "LLVM_IAS", "LOCALVERSION", "KCFLAGS",
            "KCPPFLAGS", "KAFLAGS", "KRUSTFLAGS", "O", "CC", "HOSTCC",
        }:
            env.pop(key, None)
    env["LC_ALL"] = "C"
    return env



def run(argv, *, cwd=None, check=True, timeout=120, env=None) -> subprocess.CompletedProcess:
    result = subprocess.run([str(x) for x in argv], cwd=cwd, env=environment() if env is None else env,
                            text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=timeout)
    if check and result.returncode:
        raise Error(f"Command failed: {shlex.join(map(str, argv))}\n"
                    f"{result.stderr[-4000:]}{result.stdout[-2000:]}")
    return result



def logged(argv, cwd: Path, logfile: Path, *, env=None) -> None:
    """Stream large build output to disk without accumulating it in memory."""
    say(f"$ {shlex.join(map(str, argv))}\n  Log: {logfile}")
    with logfile.open("a", encoding="utf-8") as out:
        out.write("\n$ " + shlex.join(map(str, argv)) + "\n")
        out.flush()
        proc = subprocess.Popen([str(x) for x in argv], cwd=cwd, env=environment() if env is None else env,
                                stdin=subprocess.DEVNULL, stdout=out,
                                stderr=subprocess.STDOUT, start_new_session=True)
        try:
            while True:
                try:
                    status = proc.wait(timeout=30)
                    break
                except subprocess.TimeoutExpired:
                    say(f"  Still running: {logfile.name}")
        except BaseException:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
            raise
    if status:
        with logfile.open("rb") as source:
            source.seek(max(0, logfile.stat().st_size - 6000))
            tail = source.read().decode("utf-8", errors="replace")
        raise Error(f"Command failed (exit status {status}).\n{tail}\nLog: {logfile}")



def privileged(argv) -> None:
    command = ["sudo", "--", *map(str, argv)]
    say("$ " + shlex.join(command))
    if subprocess.call(command, env=environment()):
        raise Error("Command cancelled or failed; inspect the output above.")
