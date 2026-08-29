from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from academy_core import (
    ReleaseExecutionService,
    get_project_version,
    git_commit,
    git_working_tree_clean,
)


@dataclass(frozen=True)
class RegressionRunResult:
    command: str
    exit_code: int
    test_count: int
    passed: bool
    output_snippet: str


def run_real_regression(root: Path) -> RegressionRunResult:
    cmd = [sys.executable, "-m", "unittest", "discover", "-s", "tests"]
    env = dict(os.environ)
    env["_REAL_REGRESSION_RUNNING"] = "1"
    try:
        proc = subprocess.run(
            cmd,
            cwd=root,
            capture_output=True,
            text=True,
            env=env,
            timeout=600,
        )
        output = (proc.stdout or "") + "\n" + (proc.stderr or "")
        test_count = 0
        for line in output.splitlines():
            if "Ran " in line and "test" in line:
                match = re.search(r"Ran (\d+) test", line)
                if match:
                    test_count = int(match.group(1))
        passed = (proc.returncode == 0) and (test_count > 0)
        snippet = output[-2000:].strip()
        return RegressionRunResult(
            command=" ".join(cmd),
            exit_code=proc.returncode,
            test_count=test_count,
            passed=passed,
            output_snippet=snippet,
        )
    except Exception as exc:
        return RegressionRunResult(
            command=" ".join(cmd),
            exit_code=-1,
            test_count=0,
            passed=False,
            output_snippet=f"Failed to execute regression: {exc}",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="GyanVerse Academy Release Auditor & Evaluation Tool"
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Explicitly generate final release artifacts and freeze package (fails if any gate is PENDING/FAIL).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to write generated release files when --generate is specified (defaults to release/generated).",
    )
    parser.add_argument(
        "--operator",
        type=str,
        default="System Auditor",
        help="Operator identity for evaluation report.",
    )
    args = parser.parse_args(argv)

    root = ROOT
    version = get_project_version(root)
    commit = git_commit(root)
    clean = git_working_tree_clean(root)

    print("============================================================")
    print(f"GYANVERSE ACADEMY RELEASE EVALUATION (Version: {version})")
    print("============================================================")

    regression = run_real_regression(root)
    print(f"Real regression command: {regression.command}")
    print(f"Regression result: {'PASS' if regression.passed else 'FAIL'} ({regression.test_count} tests executed)")

    service = ReleaseExecutionService()
    evaluation = service.evaluate_only(
        root=root,
        version=version,
        commit=commit,
        test_count=regression.test_count,
        tests_passed=regression.passed,
        working_tree_clean=clean,
        operator_name=args.operator,
        startup_verified=False,
        documentation_reviewed=False,
        windows_artifact=None,
        android_artifact=None,
        physical_android_device_verified=False,
        curriculum_readiness_verified=False,
    )

    print("\n--- Mandatory Release Gate Audit ---")
    audit = service.auditor.audit(
        root=root,
        version=version,
        commit=commit,
        test_count=regression.test_count,
        tests_passed=regression.passed,
        working_tree_clean=clean,
    )
    for gate in audit.gates:
        print(f"  [{gate.status.value.upper():<7}] {gate.gate:<30} : {gate.details}")

    print("\n============================================================")
    print(f"FINAL RELEASE DECISION : {evaluation.acceptance_decision.upper()}")
    print("============================================================")

    if evaluation.acceptance_decision != "approved":
        print("\nPRODUCT RELEASE STATUS: NOT APPROVED")
        print("Reason: Mandatory build, device, startup, or curriculum acceptance evidence is missing/pending.")
        print("Required incomplete items:")
        if audit.pending_gates:
            for item in audit.pending_gates:
                print(f"  - {item}: PENDING")
        if audit.blocking_failures:
            for item in audit.blocking_failures:
                print(f"  - {item}: FAILED")

    if args.generate:
        if evaluation.acceptance_decision != "approved" or not evaluation.rc_ready:
            print("\nRELEASE GENERATION ERROR: Refusing to generate release bundle because mandatory release gates are incomplete.")
            return 1

        out_dir = args.output_dir or (root / "release" / "generated")
        service.execute(
            root=root,
            release_dir=out_dir,
            version=version,
            commit=commit,
            test_count=regression.test_count,
            tests_passed=regression.passed,
            working_tree_clean=clean,
            operator_name=args.operator,
            dry_run=False,
        )
        print(f"\nFinal release bundle successfully written to: {out_dir}")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
