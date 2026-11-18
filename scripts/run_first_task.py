"""Run the minimal harness on the first task with a scripted, deterministic policy.

This is a runtime smoke test, not a model run: the actions below are fixed in
advance, including two deliberately denied ones. The purpose is to prove that
workspace creation, tool execution, policy enforcement, trace logging, patch
extraction and independent grading all work end to end.

Run with the harness interpreter (Python 3.11):

    python scripts/run_first_task.py
"""

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_harness.policy import Policy  # noqa: E402
from agent_harness.runtime import Runtime, ScriptedModel  # noqa: E402
from agent_harness.schemas import Action, Task  # noqa: E402
from agent_harness.tools import ToolBox  # noqa: E402
from agent_harness.workspace import create_snapshot, new_run_dir  # noqa: E402

DEFAULT_TASK = "marshmallow-code__marshmallow-1359"
DEFAULT_TASK_PYTHON = Path(r"D:\anaconda3\envs\task-marshmallow-1359\python.exe")

FIX_DIFF = """\
diff --git a/src/marshmallow/fields.py b/src/marshmallow/fields.py
--- a/src/marshmallow/fields.py
+++ b/src/marshmallow/fields.py
@@ -1113,7 +1113,7 @@ class DateTime(Field):
     def _bind_to_schema(self, field_name, schema):
         super()._bind_to_schema(field_name, schema)
         self.format = (
             self.format
-            or getattr(schema.opts, self.SCHEMA_OPTS_VAR_NAME)
+            or getattr(self.root.opts, self.SCHEMA_OPTS_VAR_NAME)
             or self.DEFAULT_FORMAT
         )
"""

TESTS_DIFF = """\
diff --git a/tests/test_fields.py b/tests/test_fields.py
--- a/tests/test_fields.py
+++ b/tests/test_fields.py
@@ -1,1 +1,1 @@
-\"\"\"Test fields.\"\"\"
+\"\"\"Test fields, edited by the agent.\"\"\"
"""


def load_task(task_id):
    path = ROOT / "data/public/lite-dev/tasks.jsonl"
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["instance_id"] == task_id:
            return Task.from_public(row)
    raise SystemExit("task not found in public split: " + task_id)


def scripted_actions():
    return [
        # Two attempts that the runtime must refuse before any side effect.
        Action("read_file", {"path": "../data/private/lite-dev/oracle.jsonl"}),
        Action("apply_patch", {"diff": TESTS_DIFF}),
        # Honest work: locate the configuration lookup and patch it.
        Action("list_files", {"path": "src/marshmallow"}),
        Action("search_code", {"pattern": "SCHEMA_OPTS_VAR_NAME", "path": "src/marshmallow"}),
        Action("read_file", {"path": "src/marshmallow/fields.py", "start": 1105, "end": 1122}),
        Action("run_tests", {"tests": ["tests/test_fields.py"]}),
        Action("apply_patch", {"diff": FIX_DIFF}),
        Action("run_tests", {"tests": ["tests/test_fields.py"]}),
        Action("get_diff", {}),
        Action("finish", {}),
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", default=DEFAULT_TASK)
    parser.add_argument("--repo", type=Path,
                        default=ROOT / "data/workspaces/marshmallow-1359")
    parser.add_argument("--test-python", type=Path, default=DEFAULT_TASK_PYTHON)
    args = parser.parse_args()

    task = load_task(args.task)
    run_root = ROOT / "artifacts/harness/first-task"
    run_root.mkdir(parents=True, exist_ok=True)
    run_dir = new_run_dir(run_root, "run-")
    workspace = create_snapshot(args.repo, task.base_commit, run_dir / "workspace")
    trace = run_dir / "trace.jsonl"

    toolbox = ToolBox(workspace, args.test_python)
    policy = Policy(workspace)
    runtime = Runtime(ScriptedModel(scripted_actions()), toolbox, policy, trace, max_steps=20)
    session = runtime.run(task)

    candidate = run_dir / "candidate.diff"
    diff = toolbox.current_diff()
    candidate.write_text(diff, encoding="utf-8")
    report = {
        "instance_id": task.instance_id,
        "base_commit": task.base_commit,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "scripted runtime smoke test; not a model run",
        "workspace": str(workspace),
        "session": {k: session[k] for k in ("status", "steps", "denied", "asked", "tool_errors")},
        "candidate_sha256": hashlib.sha256(diff.encode("utf-8")).hexdigest(),
        "candidate_path": str(candidate),
    }

    grade = subprocess.run(
        [str(args.test_python), str(ROOT / "scripts/grade_first_task.py"),
         "--patch", str(candidate)],
        cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        universal_newlines=True, timeout=600, check=False)
    status = "unknown"
    for line in grade.stdout.splitlines():
        if line.startswith("Status: "):
            status = line.split(":", 1)[1].strip()
    report["grader"] = {"status": status, "exit_code": grade.returncode,
                        "output": grade.stdout.strip().splitlines()[-3:]}
    (run_dir / "result.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("session : {} ({} steps, {} denied, {} tool errors)".format(
        session["status"], session["steps"], session["denied"], session["tool_errors"]))
    print("diff    : {} bytes, sha256 {}".format(len(diff), report["candidate_sha256"][:12]))
    print("grader  : {}".format(status))
    print("report  : {}".format(run_dir / "result.json"))
    return 0 if session["status"] == "finished" and status == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
