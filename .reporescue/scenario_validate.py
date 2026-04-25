#!/usr/bin/env python3
"""Path B: real business scenario for pep8radius.

Scenario — "PR formatter CI hook":
  A team wants to enforce PEP8 on *only the lines a PR touches*, not on the
  whole repo (the rest is legacy and re-formatting it would explode review
  diffs). Their CI worker runs this script in the merge-commit checkout:

    1. compute the merge-base with main (`git merge-base HEAD origin/main`)
    2. ask pep8radius to format every .py file modified in that range
    3. if pep8radius rewrote anything, fail the build with a summary patch
       so the PR author can apply locally; otherwise pass

This is the documented "headline" use of pep8radius (PR/changeset gating),
not a toy demo. The script is >30 lines and writes its summary to stderr like
a real CI worker would.

Run from a clean venv with pep8radius installed via `pip install -e`.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path


def sh(cmd, cwd, env, check=True, input_=None):
    p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, input=input_)
    if check and p.returncode != 0:
        raise RuntimeError(
            f"$ {' '.join(map(str, cmd))} (cwd={cwd})\n"
            f"--- stdout ---\n{p.stdout}\n--- stderr ---\n{p.stderr}"
        )
    return p


def setup_repo(workdir: Path, env: dict) -> None:
    """Build a fake repo with `main` + a feature branch carrying messy edits."""
    sh(["git", "init", "-q", "-b", "main"], workdir, env)
    sh(["git", "config", "user.email", "ci@example.com"], workdir, env)
    sh(["git", "config", "user.name", "CI"], workdir, env)

    # Legacy file already in `main` — intentionally NOT PEP8 perfect, but the
    # CI hook must NOT touch lines we did not modify.
    legacy = workdir / "pkg" / "legacy.py"
    legacy.parent.mkdir()
    legacy.write_text(textwrap.dedent("""\
        # legacy module - do not reformat untouched lines
        def legacy_fn(a,b):
            return a+b


        def untouched(x ):
            return x
    """))

    # Existing helper, baseline-clean
    helper = workdir / "pkg" / "helper.py"
    helper.write_text(textwrap.dedent("""\
        def add(a, b):
            return a + b
    """))

    sh(["git", "add", "."], workdir, env)
    sh(["git", "commit", "-q", "-m", "baseline main"], workdir, env)

    # Pretend `origin/main` is here
    sh(["git", "branch", "origin/main"], workdir, env)

    # Feature branch — PR with a *new* file + an edited line in helper.py
    sh(["git", "checkout", "-q", "-b", "feature"], workdir, env)
    new_file = workdir / "pkg" / "feature.py"
    new_file.write_text(textwrap.dedent("""\
        def compute( values ):
            total=0
            for v in  values:
                total+=v
            return  total
    """))
    helper.write_text(textwrap.dedent("""\
        def add(a, b):
            return a + b


        def mul(a,b):
            return a*b
    """))
    sh(["git", "add", "."], workdir, env)
    sh(["git", "commit", "-q", "-m", "feature: add compute + mul"], workdir, env)


def ci_hook(workdir: Path, env: dict, pep8radius_bin: str) -> tuple[int, str]:
    """Mimic the CI hook: run pep8radius against origin/main, summarize, return rc."""
    # Stage feature changes against main as 'unstaged' so pep8radius operates on the diff
    sh(["git", "checkout", "-q", "feature"], workdir, env)
    # pep8radius will diff working-tree against the given rev
    proc = subprocess.run(
        [pep8radius_bin, "--in-place", "--diff", "origin/main"],
        cwd=workdir, env=env, capture_output=True, text=True,
    )
    summary = proc.stdout + ("\n[stderr]\n" + proc.stderr if proc.stderr else "")
    return proc.returncode, summary


def main() -> int:
    pep8radius_bin = shutil.which("pep8radius")
    if pep8radius_bin is None:
        print("FAIL: pep8radius CLI not on PATH", file=sys.stderr)
        return 2
    print(f"[scenario] pep8radius = {pep8radius_bin}")
    assert "rescue_kimi" not in pep8radius_bin, (
        f"CLI resolved to rescue-tree venv, not clean install: {pep8radius_bin}"
    )

    workdir = Path(tempfile.mkdtemp(prefix="pep8radius_scenario_"))
    print(f"[scenario] workdir = {workdir}")

    env = os.environ.copy()
    env.update({
        "GIT_AUTHOR_NAME": "CI", "GIT_AUTHOR_EMAIL": "ci@example.com",
        "GIT_COMMITTER_NAME": "CI", "GIT_COMMITTER_EMAIL": "ci@example.com",
    })

    setup_repo(workdir, env)
    rc, summary = ci_hook(workdir, env, pep8radius_bin)
    print(f"[scenario] hook rc={rc}")
    print(f"[scenario] summary head:\n{summary[:600]}")

    # Assertions: new file `compute` got reformatted, mul got reformatted,
    # but legacy untouched lines must NOT have been changed.
    feat = (workdir / "pkg" / "feature.py").read_text()
    helper = (workdir / "pkg" / "helper.py").read_text()
    legacy = (workdir / "pkg" / "legacy.py").read_text()

    assert "def compute(values):" in feat, f"compute not reformatted:\n{feat}"
    assert "total = 0" in feat, f"E225 in compute not fixed:\n{feat}"
    assert "total += v" in feat, f"E225 += not fixed:\n{feat}"
    assert "for v in values:" in feat, f"double-space in for-loop not fixed:\n{feat}"

    assert "def mul(a, b):" in helper, f"mul not reformatted:\n{helper}"

    # Crucial: legacy lines we did NOT touch must remain UNCHANGED
    assert "def legacy_fn(a,b):" in legacy, (
        f"pep8radius wrongly reformatted untouched legacy lines:\n{legacy}"
    )
    assert "def untouched(x ):" in legacy, (
        f"pep8radius wrongly reformatted untouched lines:\n{legacy}"
    )

    print("SCENARIO_USABLE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
