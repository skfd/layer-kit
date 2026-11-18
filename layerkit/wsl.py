"""Run tippecanoe's shell commands inside WSL.

tippecanoe does not run natively on Windows, so the vector step shells out to
``wsl.exe``. Off Windows there is no WSL in between: the command runs in bash
directly and paths are left alone.
"""

import os
import subprocess


def win_to_wsl(path):
    """Convert a Windows path to its /mnt/<drive> WSL equivalent.

    Off Windows the path is returned as is (made absolute).
    """
    if os.name != "nt":
        return os.path.abspath(path)
    drive, rest = os.path.splitdrive(os.path.abspath(path))
    return f"/mnt/{drive.rstrip(':').lower()}{rest.replace(chr(92), '/')}"


def run(command, distro):
    """Run a bash command inside the WSL ``distro`` (or directly, off Windows).

    Returns stderr; raises on failure.
    """
    prefix = ["wsl", "-d", distro] if os.name == "nt" else []
    result = subprocess.run(
        [*prefix, "bash", "-lc", command],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.stdout:
        print(result.stdout.rstrip())
    if result.returncode != 0:
        print(result.stderr.rstrip())
        raise RuntimeError(
            f"WSL command failed (exit {result.returncode}). "
            f"Is WSL set up? See wsl-setup.md."
        )
    return result.stderr or ""
