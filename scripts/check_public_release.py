"""Fail closed on private files and scan only the publishable Git contents.

Requires Gitleaks on PATH (or --gitleaks). Never scans ignored local credentials
or invokes the application. Findings are redacted; exit 1 means do not publish.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile


PRIVATE_DIRS = {
    ".claude", ".codex", ".venv", "venv", "__pycache__", "node_modules",
    "outputs", "exports", "reports", "generated", "scraped_assets",
    ".ssh", ".aws", ".azure", ".kube", ".gnupg",
}
PRIVATE_SUFFIXES = {
    ".pyc", ".pyo", ".log", ".db", ".sqlite", ".sqlite3", ".xlsx", ".xls",
    ".csv", ".tsv", ".ndjson", ".jsonl", ".har", ".bak", ".backup", ".zip", ".7z",
    ".tar", ".gz", ".pem", ".key", ".p12", ".pfx",
}
PRIVATE_NAMES = {
    "settings.json", "lead_vault_settings.json", "credentials.json", ".git-credentials",
    ".gitconfig", ".netrc", "_netrc", ".npmrc", ".pypirc", "id_rsa", "id_ed25519",
}


def private_path(name: str) -> bool:
    path = PurePosixPath(name.lower())
    return (
        bool(set(path.parts) & PRIVATE_DIRS)
        or path.suffix in PRIVATE_SUFFIXES
        or path.name in PRIVATE_NAMES
        or path.name == ".env"
        or path.name.startswith((".env.", "client_secret", "service-account"))
        or path.name.endswith(".env")
        or any(marker in path.name for marker in (".db-", ".sqlite-", ".sqlite3-"))
    )


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args])


def safe_source(root: Path, name: str) -> Path:
    """Reject symlinks/junctions in every component, including on Windows."""
    source = root
    for component in PurePosixPath(name).parts:
        source = source / component
        if source.is_symlink() or (hasattr(source, "is_junction") and source.is_junction()):
            raise ValueError(f"Symlink or junction requires manual review: {name}")
    if not source.resolve(strict=True).is_relative_to(root.resolve()) or not source.is_file():
        raise ValueError(f"Tracked file is missing or outside repository: {name}")
    return source


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", action="store_true", help="Also gate every reachable commit/ref")
    parser.add_argument("--gitleaks", default="gitleaks")
    args = parser.parse_args()
    root = Path(git("rev-parse", "--show-toplevel").decode().strip())
    # Git's file enumeration is relative to cwd; always inspect the whole repo.
    os.chdir(root)
    files = git("ls-files", "-z").decode().rstrip("\0").split("\0")
    if not files or files == [""]:
        print("FAIL: no tracked files; stage the intended release first.")
        return 1
    for entry in git("ls-files", "--stage", "-z").decode().rstrip("\0").split("\0"):
        metadata, name = entry.split("\t", 1)
        mode, _, stage = metadata.split()
        if stage != "0" or mode not in {"100644", "100755"}:
            print(f"FAIL: unreviewed index mode or unresolved conflict: {name}")
            return 1
    blocked = sorted(name for name in files if private_path(name))
    if args.history:
        # Blob enumeration can hide an old private filename after a rename.
        # Inspect every distinct reachable commit tree, preserving path names.
        for tree in set(git("log", "--all", "--format=%T").decode().splitlines()):
            for entry in git("ls-tree", "-r", "-z", tree).decode().rstrip("\0").split("\0"):
                if not entry:
                    continue
                metadata, name = entry.split("\t", 1)
                mode, kind, _ = metadata.split()
                if private_path(name) or mode not in {"100644", "100755"} or kind != "blob":
                    blocked.append(name)
    if blocked:
        print(f"FAIL: {len(set(blocked))} private/generated paths in publication scope.")
        for name in sorted(set(blocked))[:30]:
            print(f"  {name}")
        print("A deletion commit does not clean earlier history. Keep this repository private.")
        return 1
    scanner = shutil.which(args.gitleaks)
    if not scanner:
        print("FAIL: install Gitleaks or supply --gitleaks PATH; secret scanning is required.")
        return 1
    scanner = str(Path(scanner).resolve())
    scanner_env = {key: value for key, value in os.environ.items()
                   if not key.upper().startswith("GITLEAKS_")}
    # Scan working files and staged blobs: either can differ from the other.
    with tempfile.TemporaryDirectory(prefix="public-release-scan-") as temp:
        snapshot = Path(temp) / "snapshot"
        config = Path(temp) / "trusted-gitleaks.toml"
        config.write_text("[extend]\nuseDefault = true\n", encoding="utf-8")
        ignore = Path(temp) / "empty-ignore"
        ignore.write_text("", encoding="utf-8")
        scanner_options = ["--config", str(config), "--gitleaks-ignore-path", str(ignore),
                           "--redact=100", "--no-banner", "--ignore-gitleaks-allow",
                           "--max-decode-depth=3", "--max-archive-depth=3"]
        for name in files:
            try:
                source = safe_source(root, name)
            except (ValueError, OSError) as error:
                print(f"FAIL: {error}")
                return 1
            for scope, content in (("working", source.read_bytes()), ("index", git("show", f":{name}"))):
                target = snapshot / scope / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
        command = [scanner, "dir", *scanner_options, str(snapshot)]
        if subprocess.run(command, cwd=root, env=scanner_env).returncode:
            return 1
        if args.history:
            command = [scanner, "git", *scanner_options,
                       "--log-opts=--all --full-history --no-renames -m", str(root)]
            if subprocess.run(command, cwd=root, env=scanner_env).returncode:
                return 1
    print(f"PASS: {len(files)} tracked files; working tree and index secret scans passed"
          + ("; reachable history passed." if args.history else ". History was NOT checked."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
