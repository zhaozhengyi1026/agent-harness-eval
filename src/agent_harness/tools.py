"""Concrete tools the runtime can execute inside the workspace."""

import os
import re
import subprocess
from pathlib import Path

from .schemas import Action, ToolResult
from .workspace import git, resolve_inside

SKIP_DIRS = {".git", "__pycache__", ".pytest_cache"}
TEXT_SUFFIXES = {".py", ".rst", ".cfg", ".toml", ".txt", ".ini", ".yml", ".yaml", ".in"}
MAX_FILES = 200
MAX_MATCHES = 40


class ToolBox:
    def __init__(self, workspace: Path, test_python: Path, max_output: int = 4000,
                 timeout: int = 300):
        self.workspace = Path(workspace).resolve()
        self.test_python = str(test_python)
        self.max_output = max_output
        self.timeout = timeout

    # -- helpers -----------------------------------------------------------
    def _text(self, value: str) -> str:
        value = value.replace("\r\n", "\n")
        if len(value) > self.max_output:
            value = value[: self.max_output] + "\n... [truncated]"
        return value

    def _walk(self, start: Path):
        for root, dirs, files in os.walk(str(start)):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in files:
                yield Path(root) / name

    # -- tools -------------------------------------------------------------
    def list_files(self, path: str = ".") -> ToolResult:
        start = resolve_inside(self.workspace, path)
        names = []
        for item in self._walk(start):
            names.append(item.relative_to(self.workspace).as_posix())
            if len(names) >= MAX_FILES:
                break
        return ToolResult(True, "\n".join(sorted(names)))

    def search_code(self, pattern: str, path: str = "src") -> ToolResult:
        if not isinstance(pattern, str) or not pattern:
            raise ValueError("pattern must be a non-empty string")
        regex = re.compile(pattern)
        start = resolve_inside(self.workspace, path)
        matches = []
        for item in self._walk(start):
            if item.suffix not in TEXT_SUFFIXES:
                continue
            try:
                lines = item.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for number, line in enumerate(lines, 1):
                if regex.search(line):
                    matches.append("{}:{}: {}".format(
                        item.relative_to(self.workspace).as_posix(), number, line.strip()[:200]))
                    if len(matches) >= MAX_MATCHES:
                        return ToolResult(True, self._text("\n".join(matches)))
        return ToolResult(True, self._text("\n".join(matches)) or "no matches")

    def read_file(self, path: str, start: int = 1, end: int = None) -> ToolResult:
        target = resolve_inside(self.workspace, path)
        if not target.is_file():
            raise ValueError("not a file: " + path)
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, int(start))
        end = min(len(lines), int(end) if end else start + 199)
        body = ["{:5d}: {}".format(n, lines[n - 1]) for n in range(start, end + 1)]
        return ToolResult(True, self._text("\n".join(body)))

    def apply_patch(self, diff: str) -> ToolResult:
        patch = self.workspace.parent / "apply.diff"
        patch.write_text(diff if diff.endswith("\n") else diff + "\n", encoding="utf-8")
        check = git(self.workspace, "apply", "--check", "--", str(patch), check=False)
        if check.returncode != 0:
            return ToolResult(False, self._text("patch does not apply:\n" + check.stderr))
        applied = git(self.workspace, "apply", "--", str(patch), check=False)
        if applied.returncode != 0:
            return ToolResult(False, self._text("apply failed:\n" + applied.stderr))
        return ToolResult(True, "applied patch to: " + ", ".join(sorted(
            p for p in (line[6:].strip() for line in diff.splitlines()
                        if line.startswith("+++ b/")) if p)))

    def run_tests(self, tests: list) -> ToolResult:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(self.workspace / "src")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        env.pop("PYTEST_ADDOPTS", None)
        command = [self.test_python, "-m", "pytest", "-q", "--color=no"] + list(tests)
        try:
            result = subprocess.run(command, cwd=str(self.workspace), env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    universal_newlines=True, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            return ToolResult(False, "pytest timed out after {}s".format(self.timeout),
                              {"returncode": 124})
        output = result.stdout or ""
        tail = "\n".join(output.strip().splitlines()[-25:])
        return ToolResult(result.returncode == 0, self._text(tail),
                          {"returncode": result.returncode})

    def get_diff(self) -> ToolResult:
        diff = git(self.workspace, "diff", check=False).stdout
        return ToolResult(True, self._text(diff) if diff.strip() else "no changes")

    def finish(self) -> ToolResult:
        return ToolResult(True, "candidate patch finalized")

    # -- dispatch ----------------------------------------------------------
    def execute(self, action: Action) -> ToolResult:
        handler = getattr(self, action.tool, None)
        if handler is None:
            return ToolResult(False, "unknown tool: " + action.tool)
        try:
            return handler(**(action.args or {}))
        except TypeError as error:
            return ToolResult(False, "bad arguments for {}: {}".format(action.tool, error))
        except Exception as error:  # tool errors are reported, not raised
            return ToolResult(False, "{}: {}".format(type(error).__name__, error))

    def current_diff(self) -> str:
        return git(self.workspace, "diff", check=False).stdout
