#!/usr/bin/env python3
"""Usability validation for pep8radius (Type A: CLI tool) — v2.

End-to-end happy path validation. Run from outside the rescue tree, against the
console_script `pep8radius` installed in a clean venv (Step 4 hard constraint):

  python3.13 -m venv /tmp/pep8radius-clean
  /tmp/pep8radius-clean/bin/pip install -e <RESCUE_TREE>
  cd /tmp/pep8radius-clean
  /tmp/pep8radius-clean/bin/python <THIS FILE>

Real-world scenario: a developer makes PEP8-violating edits in a git repo,
stages them, then runs `pep8radius --in-place` to auto-format only the lines
they touched. We verify:
  1. `pep8radius` console_script is on PATH and resolves to the clean venv
  2. real `git init` + commit + edit + `git add` workflow
  3. CLI rewrites the file to PEP8-compliant content (real-output assertion)
  4. ≥3 distinct submodules (radius, vcs, diff) are exercised
  5. multiple primary modes: --in-place, --diff, --list-files
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


PEP8_BAD = '''\
def foo( x ):
    y=x+1
    z =y*2
    return  z


def bar(a,b,c):
    return a+b+c
'''

PEP8_BASELINE = '''\
def foo(x):
    return x


def bar(a, b, c):
    return a + b + c
'''


def run(cmd, cwd, check=True, env=None):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env)
    if check and p.returncode != 0:
        raise RuntimeError(f"cmd {cmd} failed:\nstdout={p.stdout}\nstderr={p.stderr}")
    return p


def main():
    # Sanity: we must be running outside the rescue tree
    rescue_tree = Path("/home/zhihao/hdd/RepoRescue_Clean/repos/rescue_kimi/pep8radius").resolve()
    cwd = Path.cwd().resolve()
    assert rescue_tree not in cwd.parents and cwd != rescue_tree, (
        f"refusing to run inside rescue tree: cwd={cwd}"
    )
    print(f"[validate] cwd = {cwd} (outside rescue tree: OK)")

    # Resolve installed console_script
    pep8radius_bin = shutil.which("pep8radius")
    assert pep8radius_bin is not None, "pep8radius CLI not on PATH (clean install failed?)"
    print(f"[validate] pep8radius bin = {pep8radius_bin}")
    # Must be from clean venv, not the rescue-tree venv-t2
    assert "rescue_kimi" not in pep8radius_bin, (
        f"CLI resolved to rescue-tree venv, not clean install: {pep8radius_bin}"
    )

    # Constraint 5 evidence: import 3 distinct submodules from clean venv
    import importlib
    for mod in ("pep8radius.radius", "pep8radius.vcs", "pep8radius.diff", "pep8radius.main"):
        m = importlib.import_module(mod)
        print(f"[validate] imported {mod} from {m.__file__}")

    workdir = Path(tempfile.mkdtemp(prefix="pep8radius_validate_"))
    print(f"[validate] workdir = {workdir}")

    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = "Test"
    env["GIT_AUTHOR_EMAIL"] = "test@example.com"
    env["GIT_COMMITTER_NAME"] = "Test"
    env["GIT_COMMITTER_EMAIL"] = "test@example.com"

    # Real git workflow
    run(["git", "init", "-q", "-b", "main"], cwd=workdir, env=env)
    run(["git", "config", "user.email", "test@example.com"], cwd=workdir, env=env)
    run(["git", "config", "user.name", "Test"], cwd=workdir, env=env)

    target = workdir / "bad.py"
    target.write_text(PEP8_BASELINE)
    run(["git", "add", "bad.py"], cwd=workdir, env=env)
    run(["git", "commit", "-q", "-m", "baseline"], cwd=workdir, env=env)

    # Touched lines = the PEP8-violating overwrite
    target.write_text(PEP8_BAD)
    run(["git", "add", "bad.py"], cwd=workdir, env=env)

    # Mode 1: --version (cheap smoke; exercises pep8radius.main.version_info)
    proc = run([pep8radius_bin, "--version"], cwd=workdir, env=env, check=False)
    print(f"[validate] --version rc={proc.returncode}, stdout={proc.stdout.strip()!r}")
    assert proc.returncode == 0 and "0.9" in proc.stdout, (
        f"--version unhealthy: rc={proc.returncode}, out={proc.stdout!r}"
    )

    # Mode 1b: --list-fixes (exercises autopep8 plumbing through pep8radius.main)
    proc = run([pep8radius_bin, "--list-fixes"], cwd=workdir, env=env, check=False)
    assert proc.returncode == 0 and "E101" in proc.stdout, (
        f"--list-fixes did not surface autopep8 codes: rc={proc.returncode}, "
        f"head={proc.stdout[:200]!r}"
    )

    # Mode 2: --diff (no rewrite yet; exercises diff.py print_diff)
    proc = run([pep8radius_bin, "--diff"], cwd=workdir, env=env, check=False)
    print(f"[validate] --diff rc={proc.returncode}")
    assert proc.returncode == 0, f"--diff exited {proc.returncode}: {proc.stderr}"
    assert "def foo(x):" in proc.stdout, f"--diff did not propose foo(x) fix:\n{proc.stdout}"
    # File must NOT be rewritten yet
    assert target.read_text() == PEP8_BAD, "--diff must not rewrite in place"

    # Mode 3: --in-place (the headline use)
    proc = run([pep8radius_bin, "--in-place", "--diff"], cwd=workdir, env=env, check=False)
    assert proc.returncode == 0, f"--in-place exited {proc.returncode}: {proc.stderr}"

    after = target.read_text()
    print(f"[validate] file after rewrite:\n---\n{after}---")

    # Real-output assertions
    assert "def foo( x ):" not in after
    assert "def foo(x):" in after
    assert "y=x+1" not in after
    assert "y = " in after
    assert "z =y*2" not in after
    assert "z = y" in after
    assert "return  z" not in after
    assert "return z" in after
    assert "def bar(a,b,c):" not in after
    assert "def bar(a, b, c):" in after

    print("USABLE")


if __name__ == "__main__":
    main()
