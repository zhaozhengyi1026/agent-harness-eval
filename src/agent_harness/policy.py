"""Runtime policy: decide ALLOW / ASK / DENY before any tool executes.

The policy is enforced by the runtime, not by the prompt. Changing a tool name
or an argument forces a new decision.
"""

import re
from pathlib import Path, PurePosixPath
from typing import Tuple

from .schemas import Action
from .workspace import resolve_inside

ALLOW = "allow"
ASK = "ask"
DENY = "deny"

READ_TOOLS = ("list_files", "read_file", "search_code")
ALLOWED_WRITE_PREFIXES = ("src/",)
TEST_ID = re.compile(r"^tests/[A-Za-z0-9_./\-]+(::[A-Za-z0-9_\[\]\-,. ]+)?$")


def diff_paths(patch: str):
    """Collect target paths from a unified diff."""
    paths = set()
    for line in patch.splitlines():
        if line.startswith("+++ b/"):
            paths.add(line[len("+++ b/"):])
        elif line.startswith("--- a/"):
            paths.add(line[len("--- a/"):])
    return paths


class Policy:
    def __init__(self, workspace: Path):
        self.workspace = Path(workspace).resolve()

    # -- individual checks -------------------------------------------------
    def _read(self, args) -> Tuple[str, str]:
        try:
            resolve_inside(self.workspace, args.get("path", "."))
        except ValueError as error:
            return DENY, str(error)
        return ALLOW, "read inside workspace"

    def _patch(self, args) -> Tuple[str, str]:
        patch = args.get("diff", "")
        if not isinstance(patch, str) or not patch.strip():
            return DENY, "empty patch"
        paths = diff_paths(patch)
        if not paths:
            return DENY, "patch does not name any file"
        for name in paths:
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts:
                return DENY, "patch path escapes workspace: " + name
            if not str(path).startswith(ALLOWED_WRITE_PREFIXES):
                return DENY, "patch may only change src/: " + name
            if path.suffix != ".py":
                return DENY, "patch may only change Python files: " + name
        if "deleted file mode" in patch:
            return ASK, "patch deletes a file"
        return ALLOW, "code-only patch under src/"

    def _tests(self, args) -> Tuple[str, str]:
        nodes = args.get("tests")
        if not isinstance(nodes, list) or not nodes or len(nodes) > 50:
            return DENY, "tests must be a non-empty list of at most 50 node IDs"
        for node in nodes:
            if not isinstance(node, str) or not TEST_ID.match(node):
                return DENY, "unsupported test selector: {!r}".format(node)
        return ALLOW, "registered test paths only"

    # -- entry point -------------------------------------------------------
    def check(self, action: Action) -> Tuple[str, str]:
        tool = action.tool
        args = action.args or {}
        if tool in READ_TOOLS:
            return self._read(args)
        if tool == "apply_patch":
            return self._patch(args)
        if tool == "run_tests":
            return self._tests(args)
        if tool in ("get_diff", "finish"):
            return ALLOW, "read-only reporting"
        return DENY, "unknown tool: " + str(tool)
