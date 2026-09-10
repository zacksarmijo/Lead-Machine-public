"""Create a fresh local Git repository from reviewed, tracked working files.

The destination must not exist. No history, remotes, ignored files, global Git
identity, credentials, or local configuration are copied. Nothing is pushed.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

from check_public_release import private_path, safe_source


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--gitleaks", default="gitleaks")
    args = parser.parse_args()
    root = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"]).decode().strip())
    destination = args.destination.resolve()
    if destination.exists() or root == destination or root in destination.parents:
        parser.error("Destination must be a new directory outside the source repository.")
    scanner = shutil.which(args.gitleaks)
    if not scanner:
        parser.error("Gitleaks is required; install it or supply --gitleaks PATH.")
    scanner = str(Path(scanner).resolve())
    gate = subprocess.run([sys.executable, str(root / "scripts/check_public_release.py"),
                           "--gitleaks", scanner], cwd=root)
    if gate.returncode:
        return gate.returncode
    entries = subprocess.check_output(["git", "ls-files", "--stage", "-z"], cwd=root).decode().rstrip("\0").split("\0")
    files = []
    for entry in entries:
        metadata, name = entry.split("\t", 1)
        mode, _, stage = metadata.split()
        source = safe_source(root, name)
        if stage != "0" or mode not in {"100644", "100755"} or private_path(name):
            raise SystemExit(f"Refusing unreviewed file mode/path: {name}")
        files.append((name, source))
    destination.mkdir(parents=True)
    for name, source in files:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    git_env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    git_env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    subprocess.run(["git", "init", "--template=", "--initial-branch=main"], cwd=destination, env=git_env, check=True)
    subprocess.run(["git", "config", "user.name", "Lead Machine contributors"], cwd=destination, env=git_env, check=True)
    subprocess.run(["git", "config", "user.email", "contributors@users.noreply.github.com"], cwd=destination, env=git_env, check=True)
    # Do not execute inherited global hooks or invoke signing providers.
    subprocess.run(["git", "config", "core.hooksPath", ".git/no-hooks"], cwd=destination, env=git_env, check=True)
    subprocess.run(["git", "add", "--all"], cwd=destination, env=git_env, check=True)
    subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "-m", "Initial public source release"],
                   cwd=destination, env=git_env, check=True, stdout=subprocess.DEVNULL)
    check = subprocess.run([sys.executable, "scripts/check_public_release.py", "--history", "--gitleaks", scanner],
                           cwd=destination, env=git_env)
    if check.returncode:
        print("Release check failed. Keep the destination private and inspect it; no files were uploaded.")
        return check.returncode
    print(f"Created checked local public source repository: {destination}")
    print("No remote configured; nothing pushed. Keep the original private repository private.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
