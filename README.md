# pep8radius (RepoRescue rescue)

> **PEP8 only the lines you've changed in git.** A diff-only Python formatter — more precise than running `autopep8` or `black` over the whole tree, because it leaves untouched legacy lines alone and never explodes review diffs.

**Modernized for Python 3.13.** This fork is the [RepoRescue](https://github.com/RepoRescue) rescue of the abandoned upstream `hayd/pep8radius`, made to install and run cleanly under Python 3.13 with the latest `autopep8` / `yapf` / `docformatter`.

---

## Why pep8radius (vs autopep8 / black)

`autopep8` and `black` reformat **everything**. On a long-lived codebase, that is exactly what you do not want in a PR — every untouched legacy line becomes a noisy diff and `git blame` gets shredded.

`pep8radius` asks git which lines *you* touched since the merge-base (or a given rev), and only feeds those line ranges to `autopep8` / `yapf`. Result: PEP8-clean changes, untouched legacy lines stay verbatim.

It is the right tool for **PR-CI hooks** and **pre-commit hooks** that want to enforce style on new code without rewriting the past.

---

## Install

```sh
pip install -e git+https://github.com/RepoRescue/pep8radius.git#egg=pep8radius
```

Pulls `autopep8 >= 2.3`, `yapf >= 0.43`, `docformatter >= 1.7`, `colorama` — all latest, all Python 3.13 compatible.

## Quick start

Run inside any real git repo, after staging some PEP8-violating edits:

```sh
$ git add my_messy_change.py

$ pep8radius --diff           # preview the rewrite
$ pep8radius --in-place       # apply it
$ pep8radius --in-place origin/main   # PR-CI mode: format vs merge-base
```

Minimal end-to-end example:

```sh
$ cat bad.py
def foo( x ):
    y=x+1
    z =y*2
    return  z

$ git add bad.py && pep8radius --in-place

$ cat bad.py
def foo(x):
    y = x + 1
    z = y * 2
    return z
```

Other primary modes: `--list-fixes`, `--from-diff -`, `--yapf`, `--docformatter`, `--exclude`, `--select`, `--ignore`. See `pep8radius --help`.

---

## What this rescue fixed (Python 3.13 compatibility)

The kimi rescue resolved concrete 3.13 break surfaces in the original codebase. From `outputs/kimi/pep8radius/pep8radius.src.patch`:

- **`ast.Str.s` removal (3.12+)** — `setup.py` previously read `__version__` via `ast.parse(...).body[0].value.s`; replaced with text parsing.
- **6+ invalid-escape sequences in regex literals** — `diff.py`, `radius.py`, `vcs.py` now use `r"..."` raw strings (3.12 SyntaxWarning, hardened in 3.13).
- **`IOError` → `OSError`** alias collapsed in `setup.py`.
- **Python 2 fallbacks removed** — `from __future__ import print_function`, `basestring` sentinel, the py2-conditional `argparse` install_requires, and the dual `ConfigParser`/`SafeConfigParser` import in `main.py`.

Validated end-to-end (clean Python 3.13 venv, install + real `git init` + edit + `pep8radius --in-place` + assertions on rewritten output): **USABLE** (see `.reporescue/usability_validate.py`).

---

## Caveats — known fragilities (pre-existing in pep8radius/autopep8, NOT introduced by the rescue)

We ran a 7-probe bug hunt against this rescue. Three of those probes hit honest fragilities that **already existed upstream** and the rescue did not introduce or fix them. They are flagged here so you do not get bitten in production:

- **Live merge-conflict markers are silently mangled.** If a file under reformatting still contains `<<<<<<< HEAD` / `=======` / `>>>>>>> branch`, `autopep8` (which `pep8radius` calls under the hood) will dedent and rewrite the markers (`<<<<<<< HEAD` → `<< << << < HEAD`). A CI hook running on a half-resolved merge could lose conflict context. **Mitigation**: have your CI hook bail out early if `git diff --check` reports conflict markers.
- **Latin-1 source files raise `UnicodeDecodeError`** even with a PEP 263 `# -*- coding: latin-1 -*-` cookie. UTF-8 only.
- **Non-ASCII paths** (e.g. `包/café/测试.py`) are not picked up by `Git.modified_lines` parsing of `git diff --stat`. Stick to ASCII filenames.

These three are documented limitations of the upstream library, not rescue-quality regressions. The other four probes (empty commit, binary mixed in changeset, idempotent re-run, 3.13 import surface) all passed.

See `.reporescue/bug_hunt.py` for the full reproduction.

---

## Path B: real CI-hook scenario

For evidence beyond the unit suite, `.reporescue/scenario_validate.py` exercises pep8radius the way it is actually used in the wild — as a **PR formatter CI hook** running `pep8radius --in-place --diff origin/main` against a feature branch, asserting that:

- new code on the PR gets reformatted (`def compute(values):`, `total = 0`, `total += v`),
- the untouched legacy file (`def legacy_fn(a,b):`, `def untouched(x ):`) **remains in its messy form** — which is the entire raison d'être of pep8radius.

Result: `SCENARIO_USABLE`.

---

## Disclaimer

This fork exists only to keep `pep8radius` runnable under modern Python. The original project is unmaintained and we do not claim ownership of the design. All credit for the tool itself goes to [Andy Hayden (hayd)](https://github.com/hayd/pep8radius). The rescue patch is a minimal-change modernization, not a feature fork.

If something works incorrectly here that worked in the original Python 2/3.6-era release, file an issue on the RepoRescue fork — do not bother upstream.

## License

MIT — same as upstream. See `LICENSE.md`.
