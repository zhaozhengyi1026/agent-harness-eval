"""Verify the first development task locally using its reference fix (not an Agent run).

Run with the task-marshmallow-1359 interpreter. Creates a fresh snapshot and
logs under artifacts; leaves the user's existing checkout unchanged.
This is a trusted-code local smoke verifier, not a security sandbox.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
import zipfile


ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "marshmallow-code__marshmallow-1359"


def new_run_dir(root, prefix):
    """Create a unique run directory with a plain mkdir.

    ``tempfile.mkdtemp`` is avoided on purpose: on Windows the directory it
    creates has an ACL that blocks child processes such as ``git`` from
    writing, which breaks snapshot creation.
    """
    root.mkdir(parents=True, exist_ok=True)
    for _ in range(10):
        candidate = root / (prefix + uuid.uuid4().hex[:8])
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError("could not create a unique run directory")


def init_snapshot_repo(workspace):
    """Make the extracted snapshot its own Git repository.

    Without this, ``git apply`` run inside a directory that sits under another
    repository treats the patch paths as outside the current prefix and
    silently skips them ("Skipped patch"), leaving the workspace unchanged.
    """
    init = ["git", "init", "-q", "-b", "main"]
    if subprocess.run(init, cwd=str(workspace), timeout=60,
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
        subprocess.run(["git", "init", "-q"], cwd=str(workspace), check=True, timeout=60)
    subprocess.run(["git", "add", "-A"], cwd=str(workspace), check=True, timeout=60)
    subprocess.run(["git", "-c", "user.name=agent-harness",
                    "-c", "user.email=harness@example.invalid",
                    "commit", "-q", "-m", "base snapshot"],
                   cwd=str(workspace), check=True, timeout=120)


def ids(value):
    return json.loads(value) if isinstance(value, str) else value


def run_logged(command, cwd, env, log):
    with log.open("w", encoding="utf-8") as handle:
        try:
            result = subprocess.run(command, cwd=str(cwd), env=env, stdout=handle,
                                    stderr=subprocess.STDOUT, timeout=180)
            return result.returncode
        except subprocess.TimeoutExpired:
            handle.write("\nVerifier timeout: 180 seconds\n")
            return 124


def check_tests(name, targets, workspace, env, output, should_fail=False):
    xml = output / (name + ".xml")
    log = output / (name + ".log")
    command = [sys.executable, "-m", "pytest", "-q", "--color=no",
               "--junitxml=" + str(xml)] + targets
    code = run_logged(command, workspace, env, log)
    cases = list(ET.parse(str(xml)).getroot().iter("testcase")) if xml.exists() else []
    failures = [case for case in cases if case.find("failure") is not None]
    errors = [case for case in cases if case.find("error") is not None]
    skipped = [case for case in cases if case.find("skipped") is not None]
    if should_fail:
        detail = "\n".join(ET.tostring(case, encoding="unicode") for case in failures)
        valid = (code == 1 and len(cases) == len(targets) == len(failures) == 1
                 and not errors and not skipped and "AttributeError" in detail
                 and "opts" in detail)
    else:
        valid = (code == 0 and len(cases) == len(targets) and not failures
                 and not errors and not skipped)
    result = {"name": name, "command": command, "exit_code": code,
              "expected_tests": len(targets), "reported_tests": len(cases),
              "failures": len(failures), "errors": len(errors),
              "skipped": len(skipped), "expectation_met": valid,
              "log": log.name, "junit": xml.name}
    print("{}: {} ({} tests)".format(name, "OK" if valid else "FAILED", len(cases)))
    return result


def resolve_test_ids(targets, workspace, env, output):
    """Map documented truncated parameter IDs only when collection is unique."""
    node_file = output / "collected_nodes.json"
    collector = (
        "import json, pathlib, pytest, sys\n"
        "class Collector:\n"
        "    def pytest_collection_finish(self, session):\n"
        "        pathlib.Path(sys.argv[1]).write_text(json.dumps([i.nodeid for i in session.items]), encoding='utf-8')\n"
        "sys.exit(pytest.main(['--collect-only', '-q', 'tests/test_fields.py'], plugins=[Collector()]))\n"
    )
    code = run_logged([sys.executable, "-c", collector, str(node_file)], workspace,
                      env, output / "collection.log")
    if code != 0 or not node_file.exists():
        raise RuntimeError("Could not collect full test IDs; see collection.log")
    available = json.loads(node_file.read_text(encoding="utf-8"))
    resolved, mapping = [], {}
    for node in targets:
        if node in available:
            actual = node
        elif "[" in node and not node.endswith("]"):
            matches = [item for item in available if item.startswith(node)]
            if len(matches) != 1:
                raise ValueError("Truncated test ID has no unique match: " + node)
            actual = matches[0]
            mapping[node] = actual
        else:
            raise ValueError("Test ID missing from collection: " + node)
        resolved.append(actual)
    if len(set(resolved)) != len(resolved):
        raise ValueError("Multiple dataset test IDs map to the same collected test")
    return resolved, mapping


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path,
                        default=ROOT / "data/workspaces/marshmallow-1359")
    args = parser.parse_args()
    manifest_path = ROOT / "data/manifests/lite-dev.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    private = ROOT / "data" / manifest["files"]["private"]["path"]
    payload = private.read_bytes()
    if hashlib.sha256(payload).hexdigest() != manifest["files"]["private"]["sha256"]:
        raise ValueError("Oracle file hash does not match the manifest")
    task = next(row for row in map(json.loads, payload.decode("utf-8").splitlines())
                if row["instance_id"] == TASK_ID)
    target, regression = ids(task["FAIL_TO_PASS"]), ids(task["PASS_TO_PASS"])
    if len(target) != 1 or len(regression) != 76:
        raise ValueError("Unexpected first-task test set; inspect dataset revision")
    output_root = ROOT / "artifacts/first-task"
    output_root.mkdir(parents=True, exist_ok=True)
    output = new_run_dir(output_root, "verify-")
    report = {"instance_id": TASK_ID, "dataset_revision": manifest["revision"],
              "base_commit": task["base_commit"], "python": sys.version,
              "executable": sys.executable, "platform": sys.platform,
              "created_at": datetime.now(timezone.utc).isoformat(),
              "status": "incomplete", "checks": [],
              "scope": "Local reference validation; not an Agent trial or sandbox"}
    env = os.environ.copy()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("PYTEST_ADDOPTS", None)
    try:
        repo = args.repo.resolve()
        git = ["git", "-c", "safe.directory=" + str(repo), "-C", str(repo)]
        archive = output / "base.zip"
        subprocess.run(git + ["archive", "--format=zip", "--output=" + str(archive),
                              task["base_commit"]], check=True, timeout=60)
        workspace = output / "workspace"
        with zipfile.ZipFile(str(archive)) as source:
            for name in source.namelist():
                resolved = (workspace / name).resolve()
                if workspace.resolve() not in resolved.parents and resolved != workspace.resolve():
                    raise ValueError("Archive member escapes workspace")
            source.extractall(str(workspace))
        init_snapshot_repo(workspace)
        env["PYTHONPATH"] = str(workspace / "src")
        probe = [sys.executable, "-c", "import marshmallow; print(marshmallow.__file__)"]
        imported = subprocess.check_output(probe, cwd=str(workspace), env=env,
                                           universal_newlines=True, timeout=30).strip()
        if Path(imported).resolve() != (workspace / "src/marshmallow/__init__.py").resolve():
            raise RuntimeError("Interpreter imported the wrong marshmallow checkout")
        report["imported_module"] = imported
        freeze_code = run_logged([sys.executable, "-m", "pip", "freeze"], workspace,
                                 env, output / "dependencies.txt")
        if freeze_code != 0:
            raise RuntimeError("Could not record dependencies")
        for field in ("test_patch", "patch"):
            with (output / (field + ".diff")).open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(task[field].replace("\r\n", "\n").rstrip("\n") + "\n")
        apply = ["git", "apply", "--"]
        subprocess.run(apply + [str(output / "test_patch.diff")], cwd=str(workspace),
                       check=True, timeout=30)
        resolved, mapping = resolve_test_ids(target + regression, workspace, env, output)
        target, regression = resolved[:len(target)], resolved[len(target):]
        report["test_id_mapping"] = mapping
        report["checks"].append(check_tests("base_target", target, workspace, env,
                                            output, should_fail=True))
        report["checks"].append(check_tests("base_regression", regression, workspace,
                                            env, output))
        subprocess.run(apply + [str(output / "patch.diff")], cwd=str(workspace),
                       check=True, timeout=30)
        report["checks"].append(check_tests("reference_all", target + regression,
                                            workspace, env, output))
        report["status"] = ("oracle_validated_local" if
                            all(item["expectation_met"] for item in report["checks"])
                            else "validation_failed")
    except Exception as error:
        report["status"] = "verification_error"
        report["error"] = str(error)
    finally:
        path = output / "result.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Report: " + str(path))
    return 0 if report["status"] == "oracle_validated_local" else 1


if __name__ == "__main__":
    sys.exit(main())
