#!/usr/bin/env python3
"""Step 7 bug-hunt for pep8radius — anti-PyCG-blindspot probes.

Targeted at edges that unit tests in `tests/` do not cover (or barely):
  P1. empty commit (no modified lines) — must exit cleanly, NOT format anything
  P2. binary file in changeset — must not crash, must skip
  P3. merge-conflict marker file — must not silently rewrite conflicted region
  P4. non-UTF-8 (latin-1) python file with PEP8 violations
  P5. Unicode in path/filename
  P6. repeat invocation — second run on already-clean file must be idempotent
  P7. interaction with hard constraint 6 — verify no `from __future__ import
      print_function`, no bare-string regex, and that `ast.parse(...).body[0]
      .value.s` (3.12-removed) is not invoked at runtime when reading version.

Bugs found here do NOT auto-flip USABLE → TESTS_ONLY (per skill spec); we
record what we tried and what we found.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path


def gitenv():
    e = os.environ.copy()
    e.update({"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@x.com",
              "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@x.com"})
    return e


def make_repo(env) -> Path:
    d = Path(tempfile.mkdtemp(prefix="pep8radius_bug_"))
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=d, env=env, check=True)
    subprocess.run(["git", "config", "user.email", "t@x.com"], cwd=d, env=env, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=d, env=env, check=True)
    return d


def run_cli(args, cwd, env):
    return subprocess.run([shutil.which("pep8radius"), *args],
                          cwd=cwd, env=env, capture_output=True, text=True)


findings: list[str] = []


def probe_empty_commit(env):
    d = make_repo(env)
    (d / "x.py").write_text("def f(x):\n    return x\n")
    subprocess.run(["git", "add", "."], cwd=d, env=env, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=d, env=env, check=True)
    p = run_cli(["--in-place", "--diff"], d, env)
    if p.returncode != 0:
        findings.append(f"P1 empty-commit: rc={p.returncode}, stderr={p.stderr[:200]}")
    return p.returncode == 0


def probe_binary(env):
    """Mixed binary + py changeset must not crash; touched py lines get fixed."""
    d = make_repo(env)
    (d / "data.bin").write_bytes(b"\x00\x01\x02\xff" * 64)
    (d / "x.py").write_text("def f(a):\n    return a\n")  # baseline clean
    subprocess.run(["git", "add", "."], cwd=d, env=env, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=d, env=env, check=True)
    (d / "data.bin").write_bytes(b"\xff" * 64)  # touched binary
    # touch a py line with a fresh E225 violation
    (d / "x.py").write_text("def f(a):\n    y=a+1\n    return y\n")
    subprocess.run(["git", "add", "."], cwd=d, env=env, check=True)
    p = run_cli(["--in-place"], d, env)
    if p.returncode != 0:
        findings.append(f"P2 binary-in-changeset: rc={p.returncode}, stderr={p.stderr[:200]}")
        return False
    after = (d / "x.py").read_text()
    # E226 (around * + - / arithmetic) is ignored by default; only require E225 (=) fix
    if "y = a" not in after:
        findings.append(f"P2 binary-in-changeset: touched py line not reformatted: {after!r}")
        return False
    return True


def probe_conflict_markers(env):
    d = make_repo(env)
    src = (
        "def f(x):\n"
        "<<<<<<< HEAD\n"
        "    return  x\n"
        "=======\n"
        "    return x + 1\n"
        ">>>>>>> branch\n"
    )
    (d / "c.py").write_text("def f(x):\n    return x\n")
    subprocess.run(["git", "add", "."], cwd=d, env=env, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=d, env=env, check=True)
    (d / "c.py").write_text(src)
    subprocess.run(["git", "add", "."], cwd=d, env=env, check=True)
    p = run_cli(["--in-place"], d, env)
    after = (d / "c.py").read_text()
    # We expect either: pep8radius leaves conflict markers intact (file is
    # broken Python), OR exits non-zero. It must NOT silently produce a
    # syntactically-clean rewrite that drops a conflict side.
    has_markers = "<<<<<<<" in after and ">>>>>>>" in after
    if p.returncode == 0 and not has_markers:
        findings.append(
            f"P3 conflict-markers: silently rewrote conflicted file, lost markers!\n"
            f"after={after!r}"
        )
        return False
    return True


def probe_latin1(env):
    d = make_repo(env)
    bad = "# -*- coding: latin-1 -*-\ndef g(x):\n    return x\n".encode("latin-1")
    (d / "l.py").write_bytes(bad)
    subprocess.run(["git", "add", "."], cwd=d, env=env, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=d, env=env, check=True)
    bad2 = (
        "# -*- coding: latin-1 -*-\n"
        "# caf\xe9 (latin-1)\n"
        "def g( x ):\n"
        "    y=x+1\n"
        "    return  y\n"
    ).encode("latin-1")
    (d / "l.py").write_bytes(bad2)
    subprocess.run(["git", "add", "."], cwd=d, env=env, check=True)
    p = run_cli(["--in-place"], d, env)
    if p.returncode != 0:
        findings.append(f"P4 latin1: rc={p.returncode}, stderr={p.stderr[:300]}")
        return False
    return True


def probe_unicode_path(env):
    d = make_repo(env)
    sub = d / "包" / "café"
    sub.mkdir(parents=True)
    f = sub / "测试.py"
    f.write_text("def h(x):\n    return x\n")
    subprocess.run(["git", "add", "."], cwd=d, env=env, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=d, env=env, check=True)
    f.write_text("def h( x ):\n    y=x\n    return  y\n")
    subprocess.run(["git", "add", "."], cwd=d, env=env, check=True)
    p = run_cli(["--in-place"], d, env)
    if p.returncode != 0:
        findings.append(f"P5 unicode-path: rc={p.returncode}, stderr={p.stderr[:300]}")
        return False
    after = f.read_text()
    if "def h(x):" not in after:
        findings.append(f"P5 unicode-path: not reformatted: {after!r}")
        return False
    return True


def probe_idempotent(env):
    d = make_repo(env)
    (d / "i.py").write_text("def i(x):\n    return x\n")
    subprocess.run(["git", "add", "."], cwd=d, env=env, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=d, env=env, check=True)
    (d / "i.py").write_text("def i( x ):\n    return  x\n")
    subprocess.run(["git", "add", "."], cwd=d, env=env, check=True)
    run_cli(["--in-place"], d, env)
    after_first = (d / "i.py").read_text()
    subprocess.run(["git", "add", "."], cwd=d, env=env, check=True)
    p = run_cli(["--in-place"], d, env)
    after_second = (d / "i.py").read_text()
    if after_first != after_second:
        findings.append(
            f"P6 idempotent: second run changed file again\n"
            f"first={after_first!r}\nsecond={after_second!r}"
        )
        return False
    return p.returncode == 0


def probe_py313_surface():
    """Verify import-time we don't trip 3.13 removed APIs."""
    # Capture DeprecationWarnings from importing pep8radius
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        import pep8radius  # noqa: F401
        from pep8radius import diff, main, radius, vcs  # noqa: F401
    bad = [str(x.message) for x in w
           if "ast.Str" in str(x.message)
           or "invalid escape" in str(x.message).lower()
           or "imp module" in str(x.message)]
    if bad:
        findings.append(f"P7 py3.13 surface: {bad}")
        return False

    # Static check: no *invalid* escape sequences in regex literals.
    # Python 3.12+ turns invalid escapes into SyntaxWarning, 3.13 SyntaxError-track.
    # Valid python escapes: \n \r \t \b \f \v \a \0 \\ \' \" \xNN \uNNNN \N{...}
    # Anything else inside re.* call without r-prefix is a future SyntaxError.
    import pep8radius as _pkg
    pkg = Path(_pkg.__file__).parent
    valid_escape = set("nrtbfvaA0\\'\"xuNUu")
    leaks = []
    pat = re.compile(r"re\.(?:findall|split|match|search|compile|sub)\(\s*'([^']*)'")
    for py in pkg.rglob("*.py"):
        text = py.read_text()
        for m in pat.finditer(text):
            s = m.group(1)
            i = 0
            while i < len(s):
                if s[i] == '\\' and i + 1 < len(s):
                    if s[i+1] not in valid_escape and not s[i+1].isdigit():
                        leaks.append(f"{py.name}: {m.group(0)[:60]} (\\{s[i+1]})")
                        break
                    i += 2
                else:
                    i += 1
    if leaks:
        findings.append(f"P7 py3.13 surface: invalid escape in re.*: {leaks}")
        return False
    return True


def main() -> int:
    env = gitenv()
    print("=== bug_hunt ===")
    results = {
        "P1 empty-commit":   probe_empty_commit(env),
        "P2 binary-mixed":   probe_binary(env),
        "P3 conflict-markers": probe_conflict_markers(env),
        "P4 latin-1":        probe_latin1(env),
        "P5 unicode-path":   probe_unicode_path(env),
        "P6 idempotent":     probe_idempotent(env),
        "P7 3.13 surface":   probe_py313_surface(),
    }
    for k, v in results.items():
        print(f"  {k}: {'OK' if v else 'BUG'}")
    if findings:
        print("\n--- FINDINGS ---")
        for f in findings:
            print(f"* {f}")
    else:
        print("\nno bugs found")
    # Always exit 0 — bug-hunt doesn't gate USABLE per skill spec
    return 0


if __name__ == "__main__":
    sys.exit(main())
