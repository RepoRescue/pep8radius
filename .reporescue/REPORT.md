# pep8radius — Usability Validation (v2)

**Selected rescue**: kimi (T2 PASS, srconly **FAIL** — kimi full-rescue passes T2 but the source-only patch fails when test edits are stripped; gpt-codex is the only model with srconly PASS, but per user instruction we validate kimi here)
**Scenario type**: A (CLI tool — `entry_points.console_scripts: pep8radius = pep8radius.main:_main`)
**Real-world use**: format only the lines a developer touched since the last commit / branch base; used as a pre-commit hook or PR-CI gate.

## Step 0: Import sanity
`/tmp/pep8radius-clean/bin/python -c "import pep8radius"` -> OK

## Step 4: Install + core feature (clean venv, OUTSIDE rescue tree)

| Step | Command | Result |
|---|---|---|
| Build clean venv | `python3.13 -m venv /tmp/pep8radius-clean` | OK |
| Editable install of rescue | `pip install -e repos/rescue_kimi/pep8radius` | **OK** (pulls autopep8 2.3.2, yapf 0.43.0, docformatter 1.7.7, colorama 0.4.6 — all latest) |
| Leave rescue tree | `cd /tmp/pep8radius-clean` | OK |
| Run validate | `/tmp/pep8radius-clean/bin/python artifacts/pep8radius/usability_validate.py` | **USABLE** |
| `pep8radius` resolves | `/tmp/pep8radius-clean/bin/pep8radius` | clean venv, NOT rescue-tree venv-t2 |

Modes exercised: `--version`, `--list-fixes`, `--diff`, `--in-place`. Real git workflow: init -> commit baseline -> stage PEP8-violating edit -> CLI rewrite. Real-output asserts confirm `def foo(x):`, `y = `, `z = y`, `return z`, `def bar(a, b, c):`.

## Hard constraint 5: 3 distinct submodules exercised
- `pep8radius.radius` — `Radius.__init__`, `_modified_lines`
- `pep8radius.vcs` — `Git.modified_lines` subprocess git-diff parsing
- `pep8radius.diff` — `print_diff` / `udiff_lines_fixed` / `line_numbers_from_file_udiff`
- `pep8radius.main` — CLI entry

## Hard constraint 6: Py3.13 break surface stressed (evidence from `outputs/kimi/pep8radius/pep8radius.src.patch`)

| Surface | Evidence |
|---|---|
| `ast.Str` / `ast.parse(...).body[0].value.s` (removed 3.12) | `setup.py:11-22` — replaced AST `.s` access with text split |
| Invalid escape sequences in regex literals (3.12 SyntaxWarning, stricter in 3.13) | `diff.py:13/28/74`, `radius.py:141`, `vcs.py:208/253` — raw-prefixed |
| `from __future__ import print_function` halo | `diff.py`, `main.py`, `radius.py` — removed |
| `basestring` (py2-only) | `radius.py:14-21` — sentinel removed, `isinstance(..., str)` |
| `ConfigParser` py2 fallback | `main.py:7-13` — collapsed to py3-only `from configparser import ConfigParser as SafeConfigParser, NoSectionError` |
| `IOError` py2 alias | `setup.py:30` -> `OSError` |
| py<2.7 `argparse` install_requires conditional | `setup.py:26-37` — collapsed |

Three of the listed 3.13 break surfaces directly hit (ast.Str removal, invalid-escape, py2 stdlib fallbacks). Not TRIVIAL_RESCUE.

## Beyond unit tests (constraint 3)
`grep -r "subprocess.run.*pep8radius" tests/` -> no hit. The unit suite calls `Radius` and `main()` in-process; it never spawns the installed console_script across a clean venv against a real git workspace, and it does not test `--in-place origin/main` (PR-CI mode). `usability_validate.py` and `scenario_validate.py` cover that gap.

## Step 6 — Path B: real CI-hook business script (`scenario_validate.py`, ~140 lines)
1. Build a git repo with `main` containing intentionally messy *legacy* code that must NOT be reformatted.
2. Branch `feature` adds a brand-new `pkg/feature.py` and edits one helper.
3. CI worker runs `pep8radius --in-place --diff origin/main`.
4. Assertions:
   - new `pkg/feature.py`: `compute(values)`, `total = 0`, `total += v`, `for v in values:`, `return total` -> all reformatted
   - `pkg/helper.py`: `def mul(a, b):` reformatted
   - **legacy untouched lines** (`def legacy_fn(a,b):`, `def untouched(x ):`) **remain in their messy form** — this is the entire raison d'être of pep8radius.

Output: `SCENARIO_USABLE` (run.log).

Path A skipped: live downstreams of pep8radius are mostly fork wrappers; the primary use IS the CI hook embodied in Path B.

## Step 7: bug-hunt (`bug_hunt.py`, 7 probes)
| Probe | Result |
|---|---|
| P1 empty commit | OK |
| P2 binary file mixed in changeset | OK (E226 on `+` deliberately ignored by default; E225 on `=` fixed as expected) |
| P3 file with live merge-conflict markers | **BUG** — pep8radius/autopep8 silently mangles markers (`<<<<<<< HEAD` -> `<< << << < HEAD`, dedents lines). CI hook on a half-resolved merge could lose conflict context. Layer: `pep8radius/main.py` -> autopep8 has no marker awareness, no pre-flight check in pep8radius. |
| P4 latin-1 source file | **BUG** — `UnicodeDecodeError` even with PEP 263 cookie. Pre-existing pep8radius/autopep8 limitation; rescue did not introduce it. |
| P5 unicode path (`包/café/测试.py`) | **BUG** — file not picked up by `Git.modified_lines` regex over `git diff --stat`. Pre-existing. |
| P6 idempotent re-run | OK |
| P7 3.13 surface | OK — zero DeprecationWarning at import; static scan of shipped re.* literals finds zero invalid escapes after rescue |

Per skill spec, bugs do NOT flip USABLE -> TESTS_ONLY. P3/P4/P5 are documented limitations of pep8radius's primary library, not rescue-quality regressions.

## Verdict
STATUS: USABLE

Reason: clean-venv `pip install -e` succeeds; `pep8radius --in-place` rewrites real PEP8-violating Python via real git diff in two distinct workflows (HEAD-touch and `origin/main` PR-CI hook); 3 submodules (radius/vcs/diff) walked at runtime; the kimi rescue removed concrete 3.13 break surfaces (`ast.Str`, invalid-escape regex, py2 stdlib aliases). Bug-hunt found three honest edge-case fragilities pre-existing in pep8radius itself.

Caveat for org publish: kimi srconly is FAIL (full rescue passes only because of test-side edits). If GitHub-org publish ships srconly only, prefer **gpt-codex** (its srconly is PASS). The kimi rescue source is independently functional as validated.
