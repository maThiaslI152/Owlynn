#!/usr/bin/env python3
"""Run Owlynn test suites (pytest)."""

import argparse
import subprocess
import sys
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def run_pytest(extra_args: list[str]) -> int:
    root = _project_root()
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(root / "tests"),
        "-m",
        "not network",
        "--tb=short",
        *extra_args,
    ]
    return subprocess.run(cmd, cwd=root).returncode


def run_pytest_all(extra_args: list[str]) -> int:
    root = _project_root()
    cmd = [sys.executable, "-m", "pytest", str(root / "tests"), "--tb=short", *extra_args]
    return subprocess.run(cmd, cwd=root).returncode


def run_routing_regressions() -> int:
    root = _project_root()
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            str(root / "tests" / "test_prompt_regression.py"),
            str(root / "tests" / "test_sentence_routing_and_response.py"),
        ],
        cwd=root,
    ).returncode


def run_internet_smoke(extra_args: list[str]) -> int:
    root = _project_root()
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            str(root / "tests" / "test_web_internet_smoke.py"),
            "--tb=short",
            *extra_args,
        ],
        cwd=root,
    ).returncode


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Owlynn tests via pytest.")
    parser.add_argument(
        "--routing",
        action="store_true",
        help="Only sentence/prompt routing regression tests.",
    )
    parser.add_argument(
        "--network",
        action="store_true",
        help="Include network/browser tests (web_search, fetch_webpage, etc.).",
    )
    parser.add_argument(
        "--internet",
        action="store_true",
        help="Run internet-info smoke tests (news/weather/general/games).",
    )
    args, pytest_tail = parser.parse_known_args()

    if args.routing:
        raise SystemExit(run_routing_regressions())

    if args.internet:
        raise SystemExit(run_internet_smoke(pytest_tail))

    if args.network:
        raise SystemExit(run_pytest_all(pytest_tail))

    raise SystemExit(run_pytest(pytest_tail))
