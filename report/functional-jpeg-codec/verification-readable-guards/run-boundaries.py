#!/usr/bin/env python3
"""Scoped host-only before/after guard verification; leaves every exit code in JSON."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
RUNTIME = HERE.parents[2] / "runtime/analysis"
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
spec = importlib.util.spec_from_file_location("jpeg_boundary_tests", RUNTIME / "test_functional_jpeg_codec.py")
tests = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tests)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("before", "after"))
    parser.add_argument("--reuse-builds", type=Path, help="Run repeats only against an existing pytest build directory")
    parser.add_argument("--output", type=Path, help="Fresh scoped output directory; existing evidence is never replaced")
    args = parser.parse_args()
    phase = args.phase
    path = (args.output or HERE / (phase + ("-repeats" if args.reuse_builds else ""))).resolve()
    path.mkdir(exist_ok=False)
    if args.reuse_builds:
        build_directory = args.reuse_builds.resolve()
        summary = dict(phase=phase, command=sys.argv, reused_builds=str(build_directory), runs=[])
    else:
        command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=short",
                   "--basetemp", str(path / "pytest-builds"), str(RUNTIME / "test_functional_jpeg_codec.py")]
        if phase == "before":
            command += ["-k", "main-short-object-sanitized", "-x"]
        start = time.monotonic()
        process = subprocess.run(command, cwd=RUNTIME, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
                                 capture_output=True, timeout=180)
        (path / "pytest.stdout").write_bytes(process.stdout)
        (path / "pytest.stderr").write_bytes(process.stderr)
        summary = dict(phase=phase, command=command, returncode=process.returncode,
                       elapsed_seconds=time.monotonic() - start,
                       stdout_sha256=digest(process.stdout), stderr_sha256=digest(process.stderr), runs=[])
        (path / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        expected = 1 if phase == "before" else 0
        assert process.returncode == expected, process.stdout.decode(errors="replace") + process.stderr.decode(errors="replace")
        build_directory = path / "pytest-builds/functional-jpeg-codec0"
        if phase == "after":
            print(f"after: full pytest matrix rc=0 in {summary['elapsed_seconds']:.2f}s; run repeats separately", flush=True)
            return
    builds = {mode: build_directory / mode for mode in ("normal", "sanitized")}
    for scenario in ("main-short-object", "main-small-object", "main-dmm-short", "main-dmm-failed"):
        for mode in builds:
            for iteration in range(1, 51):
                process = subprocess.run([str(builds[mode]), scenario], capture_output=True,
                                         env=tests.ENV, timeout=60)
                row = dict(scenario=scenario, mode=mode, iteration=iteration, returncode=process.returncode,
                           stdout_bytes=len(process.stdout), stdout_sha256=digest(process.stdout),
                           stderr_bytes=len(process.stderr), stderr_sha256=digest(process.stderr))
                summary["runs"].append(row)
                if iteration == 1:
                    (path / f"{scenario}-{mode}.stderr").write_bytes(process.stderr)
                (path / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
                refused_by_old = phase == "before" and scenario in ("main-short-object", "main-dmm-short")
                if refused_by_old:
                    assert process.returncode == -6, row
                    diagnostic = (f"UNREADABLE_ENTRY scenario={scenario} native_execs=1 borrow_count=0 requests_freed=0"
                                  " release_count=0 serialized_writes=0 bridge_stills=0 send_calls=0").encode()
                    assert diagnostic in process.stderr and not process.stdout, row
                else:
                    assert process.returncode == 0, process.stderr.decode(errors="replace")
                    assert b"Sanitizer" not in process.stderr and b"runtime error:" not in process.stderr
                    if scenario == "main-small-object":
                        # Reuse the existing full content assertions on the captured run.
                        original_run = tests.run
                        tests.run = lambda *_: process.stdout
                        try:
                            tests.test_main_actual_bridge_bytes_original_config_store_and_independent_decode(builds, mode, scenario)
                        finally:
                            tests.run = original_run
                    else:
                        assert not process.stdout, row
            print(f"{phase}: {scenario} {mode} 50/50 expected outcomes", flush=True)
    summary["repeat_total"] = len(summary["runs"])
    summary["complete"] = True
    (path / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"{phase}: {summary['repeat_total']} sequential boundary executions verified", flush=True)


if __name__ == "__main__":
    main()
