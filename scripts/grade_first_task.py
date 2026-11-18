"""Grade a supplied patch for marshmallow-1359 in a fresh local snapshot.

Run in task-marshmallow-1359. For trusted local patches only: this process is
not sandboxed. The reference code patch is never applied automatically.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import zipfile

from verify_first_task import (ROOT, TASK_ID, check_tests, ids, init_snapshot_repo,
                               new_run_dir, resolve_test_ids, run_logged)


class InvalidPatch(Exception):
    pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--patch", type=Path, help="Candidate code diff; not the test diff")
    choice.add_argument("--empty", action="store_true", help="Negative control: change no code")
    parser.add_argument("--repo", type=Path, default=ROOT / "data/workspaces/marshmallow-1359")
    args = parser.parse_args()
    output_root = ROOT / "artifacts/candidate-grading"
    output_root.mkdir(parents=True, exist_ok=True)
    output = new_run_dir(output_root, "grade-")
    report = {"instance_id": TASK_ID, "status": "grader_error", "checks": [],
              "created_at": datetime.now(timezone.utc).isoformat(),
              "python": sys.version, "executable": sys.executable, "platform": sys.platform,
              "scope": "Trusted local candidate grading; not a sandbox or official score"}
    try:
        manifest = json.loads((ROOT / "data/manifests/lite-dev.json").read_text(encoding="utf-8"))
        payload = (ROOT / "data" / manifest["files"]["private"]["path"]).read_bytes()
        if hashlib.sha256(payload).hexdigest() != manifest["files"]["private"]["sha256"]:
            raise ValueError("Private data hash does not match manifest")
        task = next(row for row in map(json.loads, payload.decode("utf-8").splitlines())
                    if row["instance_id"] == TASK_ID)
        report.update(dataset_revision=manifest["revision"], base_commit=task["base_commit"])
        repo = args.repo.resolve()
        archive = output / "base.zip"
        subprocess.run(["git", "-c", "safe.directory=" + str(repo), "-C", str(repo),
                        "archive", "--format=zip", "--output=" + str(archive), task["base_commit"]],
                       check=True, timeout=60)
        workspace = output / "workspace"
        with zipfile.ZipFile(str(archive)) as source:
            for name in source.namelist():
                member = (workspace / name).resolve()
                if workspace.resolve() not in member.parents and member != workspace.resolve():
                    raise ValueError("Archive member escapes workspace")
            source.extractall(str(workspace))
        init_snapshot_repo(workspace)
        env = os.environ.copy()
        env.update(PYTHONPATH=str(workspace / "src"), PYTHONDONTWRITEBYTECODE="1",
                   PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
        env.pop("PYTEST_ADDOPTS", None)
        env.pop("PYTHONOPTIMIZE", None)
        probe = subprocess.check_output(
            [sys.executable, "-c", "import marshmallow; print(marshmallow.__file__)"],
            cwd=str(workspace), env=env, universal_newlines=True, timeout=30).strip()
        if Path(probe).resolve() != (workspace / "src/marshmallow/__init__.py").resolve():
            raise RuntimeError("Interpreter imported the wrong checkout")
        report["imported_module"] = probe
        if run_logged([sys.executable, "-m", "pip", "freeze"], workspace, env,
                      output / "dependencies.txt") != 0:
            raise RuntimeError("Could not record dependencies")
        hidden_tests = output / "test_patch.diff"
        hidden_tests.write_bytes(task["test_patch"].replace("\r\n", "\n").encode("utf-8"))
        subprocess.run(["git", "apply", "--", str(hidden_tests)], cwd=str(workspace),
                       check=True, timeout=30)
        targets, mapping = resolve_test_ids(ids(task["FAIL_TO_PASS"]) + ids(task["PASS_TO_PASS"]),
                                            workspace, env, output)
        report["test_id_mapping"] = mapping
        if args.patch:
            candidate = output / "candidate.diff"
            content = args.patch.resolve().read_bytes()
            candidate.write_bytes(content)
            report.update(candidate_source=str(args.patch.resolve()),
                          candidate_sha256=hashlib.sha256(content).hexdigest())
            command = ["git", "apply", "--numstat", "-z", "--", str(candidate)]
            stats = subprocess.run(command, cwd=str(workspace), stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, timeout=30)
            if stats.returncode != 0 or not stats.stdout:
                raise InvalidPatch("Candidate is not a nonempty valid diff")
            paths = []
            for entry in stats.stdout.decode("utf-8").rstrip("\0").split("\0"):
                parts = entry.split("\t", 2)
                if len(parts) != 3:
                    raise InvalidPatch("Unsupported patch path format")
                path = PurePosixPath(parts[2])
                if (path.is_absolute() or ".." in path.parts or
                        path.parts[:2] != ("src", "marshmallow") or path.suffix != ".py"):
                    raise InvalidPatch("Only src/marshmallow/*.py code changes are supported")
                paths.append(str(path))
            report["changed_paths"] = paths
            for flags in (["--check"], []):
                code = run_logged(["git", "apply"] + flags + ["--", str(candidate)],
                                  workspace, env, output / ("apply-check.log" if flags else "apply.log"))
                if code != 0:
                    raise InvalidPatch("Candidate could not be applied; see apply logs")
        else:
            report["candidate_source"] = "empty_negative_control"
        result = check_tests("candidate_all", targets, workspace, env, output)
        report["checks"].append(result)
        if result["expectation_met"]:
            report["status"] = "passed"
        elif (result["exit_code"] == 1 and result["reported_tests"] == len(targets)
              and result["failures"] and not result["errors"] and not result["skipped"]):
            report["status"] = "failed_tests"
        else:
            report["status"] = "test_execution_error"
    except InvalidPatch as error:
        report.update(status="invalid_patch", error=str(error))
    except Exception as error:
        report.update(status="grader_error", error=str(error))
    finally:
        path = output / "result.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Status: " + report["status"])
        print("Report: " + str(path))
    if report["status"] == "passed":
        return 0
    return 1 if report["status"] in ("failed_tests", "invalid_patch") else 2


if __name__ == "__main__":
    sys.exit(main())
