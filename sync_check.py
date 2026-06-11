#!/usr/bin/env python3
"""Audit the Atomize fork family against the upstream lead (plain ``Atomize``).

The forks all share the same ``atomize/`` framework but each adds its own
control-centre, scripts, ``libs/`` and (sometimes) device-specific drivers. The
hard part of keeping them in sync is telling *intentional* divergence apart from
*accidental* drift. This tool encodes that knowledge once, in the MANIFEST
below, and then:

  * lists every file that differs / is missing / is extra per fork,
  * classifies each as EXPECTED (matches the manifest) or DRIFT,
  * normalises CRLF<->LF so line-endings never raise a false positive,
  * optionally copies the proven-safe ``plain -> fork`` category (device
    drivers + shared math) with ``--apply-drivers``.

Run:   python3 sync_check.py              # audit all forks, drift only
       python3 sync_check.py -v           # also show the expected-divergence list
       python3 sync_check.py --apply-drivers FORK   # sync plain-lead files into FORK

Direction of truth (learned the hard way, see the project memory):
  * device_modules + math cores : plain is the LEAD  -> changes flow plain->fork
  * control_center / GUI / scripts: developed in the forks -> flow fork->plain
So this tool only ever *auto-applies* the plain-lead category; everything else
it reports for a human to resolve by hand.
"""

import os
import sys
import fnmatch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # /home/anatoly
LEAD = "Atomize"
FORKS = ["Atomize_ITC", "Atomize_NIOCH", "Atomize_Cryomech"]

# Only these file types are compared (skip binaries, caches, presets).
EXTS = (".py", ".ini")
SKIP_DIR_PARTS = {"__pycache__", ".git", "build", "dist"}

# ---------------------------------------------------------------------------
# MANIFEST: paths (fnmatch globs, relative to repo root) that are ALLOWED to
# differ from plain. Anything matching is reported as EXPECTED, never DRIFT,
# and is never auto-synced. Add to this list whenever a new intentional
# divergence is introduced.
# ---------------------------------------------------------------------------
EXPECTED = [
    # whole fork-specific subtrees
    "atomize/control_center/*",
    "atomize/script_examples/*",
    "atomize/tests/*",                       # NIOCH keeps its scripts here
    # per-installation hardware configuration
    "atomize/config.ini",
    "atomize/device_modules/config/*.ini",
    # intentional framework divergences
    "atomize/general_modules/last_dir.py",   # libs/ vs user_config_dir backend
    "atomize/main/local_config.py",          # per-fork app_name isolation
    "atomize/main/main.py",                  # fork-only MainExtended (EPR tab)
    "atomize/__main__.py",                   # imports the fork's extended main
    # fork-only / gitignored device drivers
    "atomize/device_modules/Keysight_2000_Xseries_2.py",
    "atomize/device_modules/Metrolab_PT2025.py",
    "atomize/device_modules/config/Metrolab_PT2025_config.ini",
]

# --- auto-sync sets (plain -> fork) -----------------------------------------
# Files that should be IDENTICAL across plain and every fork. plain is the
# integration point: a feature developed fork-side is first lifted to plain by
# hand (fork->plain), then `--sync` distributes it plain->fork to the others.
# EXPECTED files are ALWAYS skipped, so the genuine per-fork divergences
# (last_dir.py backend, local_config.py app_name, the fork-only main.py /
# __main__.py, control_center, configs) are never clobbered. main_window.py is
# now plain-led too (the per-fork wiring lives in main.py, not here).
#
# DRIVERS    — device drivers only; the narrow, always-safe plain->fork set
#              used by `--apply-drivers`.
# PLAIN_LEAD — the broad shared-framework set used by `--sync`.
DRIVERS = [
    "atomize/device_modules/*.py",
]
PLAIN_LEAD = DRIVERS + [
    "atomize/math_modules/*.py",
    "atomize/general_modules/*.py",   # last_dir.py is in EXPECTED -> skipped
    "atomize/main/*.py",              # local_config/main are EXPECTED -> skipped
    "atomize/__main__.py",            # also EXPECTED -> skipped
]


def matches(path, globs):
    # fnmatch '*' spans '/', so a single '*' after a dir matches the whole subtree.
    return any(fnmatch.fnmatch(path, g) for g in globs)


def list_files(repo):
    # Only the shared ``atomize/`` package is audited. Repo-root scaffolding
    # (libs/, tests/, setup.py, pyproject.toml) is fork-specific by nature.
    base = os.path.join(ROOT, repo)
    out = {}
    for dirpath, dirnames, filenames in os.walk(os.path.join(base, "atomize")):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_PARTS]
        for fn in filenames:
            if fn.endswith(EXTS):
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, base)
                out[rel.replace(os.sep, "/")] = full
    return out


def norm(path):
    with open(path, "rb") as fh:
        return fh.read().replace(b"\r\n", b"\n")


def audit(fork, verbose=False):
    lead = list_files(LEAD)
    fk = list_files(fork)
    differ, missing, extra, expected = [], [], [], []

    for rel in sorted(set(lead) | set(fk)):
        exp = matches(rel, EXPECTED)
        in_lead, in_fork = rel in lead, rel in fk
        if in_lead and in_fork:
            if norm(lead[rel]) == norm(fk[rel]):
                continue
            (expected if exp else differ).append(rel)
        elif in_lead and not in_fork:
            (expected if exp else missing).append(rel)
        else:  # fork-only
            (expected if exp else extra).append(rel)

    print(f"\n===== {fork} =====")
    drift = bool(differ or missing or extra)
    if not drift:
        print("  IN SYNC (only expected divergence)")
    if differ:
        print(f"  DRIFT — differs from plain ({len(differ)}):")
        for r in differ:
            print(f"      ~ {r}")
    if missing:
        print(f"  DRIFT — in plain, MISSING in fork ({len(missing)}):")
        for r in missing:
            print(f"      - {r}")
    if extra:
        print(f"  DRIFT — fork-only, not in plain ({len(extra)}):")
        for r in extra:
            print(f"      + {r}")
    if verbose and expected:
        print(f"  (expected divergence, ignored: {len(expected)} files)")
    return drift


def _write_preserving_eol(src, dst):
    """Write plain's content into dst, but keep dst's existing line endings so a
    CRLF fork file (e.g. NIOCH main/*) doesn't turn into a whole-file diff. New
    files are written with plain's bytes verbatim (LF)."""
    data = open(src, "rb").read()
    if os.path.exists(dst) and b"\r\n" in open(dst, "rb").read():
        data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    open(dst, "wb").write(data)


def sync(fork, globs, label, dry_run=False):
    """Copy plain->fork for every file matching ``globs`` that differs in content
    or is missing, skipping anything in EXPECTED. Content comparison is
    EOL-normalised, and writes preserve the target's line endings."""
    lead = list_files(LEAD)
    fk = list_files(fork)
    changed = []
    for rel, src in sorted(lead.items()):
        if not matches(rel, globs) or matches(rel, EXPECTED):
            continue
        if rel not in fk:
            changed.append(("+", rel))
        elif norm(src) != norm(fk[rel]):
            changed.append(("~", rel))
        else:
            continue
        if not dry_run:
            _write_preserving_eol(src, os.path.join(ROOT, fork, rel))
    verb = "would sync" if dry_run else "synced"
    print(f"\n=== {fork}: {label} ===")
    if not changed:
        print("  already in sync — nothing to do")
    for sign, rel in changed:
        print(f"  {verb} {sign} {rel}")
    return len(changed)


USAGE = """\
Atomize fork-sync auditor / distributor — compares each fork's atomize/ package
against the upstream lead (plain Atomize), reports drift, and can push the
shared plain-led files plain -> fork.

AUDIT (read-only)
  python3 sync_check.py                  audit every fork (drift-only report)
  python3 sync_check.py -v               also count the ignored/expected files
  python3 sync_check.py <ForkName>       audit just one fork (e.g. Atomize_ITC)

SYNC (plain -> fork; never touches EXPECTED/per-fork files)
  python3 sync_check.py --sync           distribute shared files to ALL forks
  python3 sync_check.py --sync <ForkName>          ... to one fork
  python3 sync_check.py --sync -n        dry-run: show what WOULD change
  python3 sync_check.py --apply-drivers <ForkName> device_modules only (narrow)

  python3 sync_check.py -h | --help      show this help

KNOWN FORKS
  {forks}

WHAT --sync COPIES
  Shared, plain-led framework files that should be identical everywhere:
  device_modules/, math_modules/, general_modules/, main/, __main__.py.
  EXPECTED files are always skipped, so genuine per-fork divergences are safe:
  last_dir.py (backend), local_config.py (app_name), the fork-only
  main.py/__main__.py, control_center/, configs.

WORKFLOW
  plain is the integration point. Develop a GUI/feature in a fork, lift it to
  plain by hand (fork -> plain), then run --sync to distribute it to the others.
  Run an audit first to see direction; --sync only ever pushes plain -> fork.

NOTES
  * atomize/ package only; repo-root libs/, tests/, setup.py are fork-specific.
  * CRLF vs LF never counts as drift; --sync preserves each target's line endings.
  * Audits .py and .ini only — NOT markdown docs (those mirror from atomize_docs).
  * New intentional divergence -> add a glob to EXPECTED ("ForkName:glob" for
    per-fork). New fork -> FORKS. Widen/narrow auto-sync via PLAIN_LEAD/DRIVERS.
"""


def _check_fork(name):
    if name not in FORKS:
        sys.exit(f"unknown fork {name!r}; known: {', '.join(FORKS)}")


def main():
    args = sys.argv[1:]
    if "-h" in args or "--help" in args:
        print(USAGE.format(forks=", ".join(FORKS)))
        return

    if "--apply-drivers" in args:
        named = [a for a in args if not a.startswith("-")]
        if not named:
            sys.exit("usage: sync_check.py --apply-drivers <ForkName>")
        _check_fork(named[0])
        sync(named[0], DRIVERS, "device drivers", dry_run="-n" in args)
        return

    if "--sync" in args:
        dry = "-n" in args
        named = [a for a in args if not a.startswith("-")]
        targets = named or FORKS
        for t in targets:
            _check_fork(t)
        total = sum(sync(f, PLAIN_LEAD, "shared framework", dry_run=dry) for f in targets)
        tip = "  (dry-run — re-run without -n to apply)" if dry else ""
        print(f"\n{total} file(s) {'would change' if dry else 'synced'}.{tip}")
        return

    verbose = "-v" in args
    named = [a for a in args if not a.startswith("-")]
    targets = named or FORKS
    for t in targets:
        _check_fork(t)
    any_drift = False
    for fork in targets:
        any_drift |= audit(fork, verbose=verbose)
    print()
    print("Drift found — review above." if any_drift
          else "All forks in sync (only expected divergence).")


if __name__ == "__main__":
    main()
