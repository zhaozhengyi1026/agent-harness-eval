"""Create and inspect the workspace the agent is allowed to touch."""

import subprocess
import uuid
import zipfile
from pathlib import Path

BASE_AUTHOR = ("agent-harness", "harness@example.invalid")


def new_run_dir(root: Path, prefix: str) -> Path:
    """Create a unique run directory.

    ``tempfile.mkdtemp`` is avoided on purpose: on Windows it produces a
    directory whose ACL blocks child processes such as ``git`` from writing.
    A plain ``mkdir`` inherits the parent ACL and keeps the tools working.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    for _ in range(10):
        candidate = root / (prefix + uuid.uuid4().hex[:8])
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError("could not create a unique run directory under " + str(root))


def resolve_inside(root: Path, relative: str) -> Path:
    """Resolve a relative path and refuse anything outside ``root``."""
    if not isinstance(relative, str) or not relative.strip():
        raise ValueError("path must be a non-empty string")
    root = root.resolve()
    candidate = Path(relative)
    if candidate.is_absolute():
        raise ValueError("absolute paths are not allowed")
    resolved = (root / candidate).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("path escapes the workspace: {}".format(relative))
    return resolved


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd)] + list(args),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        timeout=120,
        check=check,
    )


def create_snapshot(repo: Path, commit: str, dest: Path) -> Path:
    """Export ``commit`` from ``repo`` into ``dest`` and make it a fresh repo.

    The new repository has exactly one commit ("base"), so the agent can use
    ``git diff`` but cannot read future history or the original remote.
    """
    repo = repo.resolve()
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    archive = dest.parent / (dest.name + ".zip")
    exported = subprocess.run(
        ["git", "-c", "safe.directory=" + str(repo), "-C", str(repo),
         "archive", "--format=zip", "--output=" + str(archive), commit],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        timeout=120,
        check=False,
    )
    if exported.returncode != 0:
        raise RuntimeError("git archive failed ({}): {}".format(
            exported.returncode, (exported.stderr or "").strip()))
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(archive)) as source:
        for name in source.namelist():
            resolve_inside(dest, name)
        source.extractall(str(dest))
        names = source.namelist()
    git(dest, "init", "-q", "-b", "main")
    git(dest, "add", "-A")
    git(dest, "-c", "user.name=" + BASE_AUTHOR[0],
        "-c", "user.email=" + BASE_AUTHOR[1], "commit", "-q", "-m", "base snapshot")
    (dest.parent / "base_manifest.json").write_text(
        '{"commit": "%s", "files": %d}\n' % (commit, len(names)), encoding="utf-8")
    archive.unlink()
    return dest
