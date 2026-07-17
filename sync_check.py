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
  * shared EPR control-centre tools (data_treatment, deer_analysis, ...): NOT in
    plain; developed in ITC and mirrored to the other endstation forks -> ITC is
    the lead, synced fork->fork with ``--sync-cc``.
plain is the integration point for the shared framework. ``--sync`` fans the
plain-lead set plain->fork; ``--lift`` ports a fork-side feature the other way
(fork->plain) so it can then be ``--sync``'d out. ``--lift`` writes to plain (the
lead), so it acts only on the file(s) you name (or --all) and previews otherwise.
control_center (other than the shared tools above) / configs (the EXPECTED set)
are never auto-copied. ``--sync-cc`` carries just the named shared CC tools
ITC->endstation forks, exempting them from the control_center EXPECTED skip.
"""

import os
import sys
import fnmatch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # /home/anatoly
LEAD = "Atomize"
FORKS = ["Atomize_ITC", "Atomize_NIOCH", "Atomize_NIOCH_Q", "Atomize_Cryomech"]

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
    "atomize/device_modules/Spectrum_M4I_4450_X8_invert.py",
    "atomize/general_modules/csv_opener_saver_invert.py",
    "atomize/general_modules/inversion_param.py",
    "atomize/main/widgets_invert.py",
    "atomize/epr_auto/*",
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

# --- EPR control-center tools (fork -> fork, ITC-led) ------------------------
# A handful of control-centre data-analysis tools are SHARED among the EPR
# endstation forks but DO NOT exist in plain Atomize, so the plain-led machinery
# above can't carry them. They are developed in ITC and mirrored to the other
# endstation forks (NIOCH today, more later). control_center/* is in EXPECTED,
# so `--sync-cc` exempts exactly the named files (via the `allow` arg) to copy
# EPR_LEAD -> EPR_FORKS while still leaving every other control_center file
# (fork-specific widgets, presets, wiring) untouched.
EPR_LEAD = "Atomize_ITC"
EPR_FORKS = ["Atomize_NIOCH", "Atomize_NIOCH_Q"]        # endstation forks that receive ITC's tools; add future forks here
CONTROL_CENTER_SHARED = [
    "atomize/control_center/data_treatment.py",
    "atomize/control_center/data_treatment_2d.py",
    "atomize/control_center/deer_analysis.py",
    "atomize/control_center/excitation_profile.py",
    "atomize/control_center/sequence_calculator.py",
    "atomize/control_center/spin_dynamics_sim.py",
]

# --- config files (EXPECTED; NEVER auto-synced; manual review/port only) ------
# Device + main config hold PER-INSTALLATION hardware settings (GPIB addresses,
# serial ports, IPs, calibration), so they are in EXPECTED and never carried by
# --sync. But two cases legitimately need to move: a brand-new device's DEFAULT
# config (plain->fork, the operator then edits it) and a shared new option/key.
# `--check-config` un-hides config drift for review; `--port-config` is the
# opt-in escape hatch to copy NAMED config file(s) by hand (either direction).
CONFIG_FILES = [
    "atomize/config.ini",
    "atomize/device_modules/config/*.ini",
]


def matches(path, globs):
    # fnmatch '*' spans '/', so a single '*' after a dir matches the whole subtree.
    return any(fnmatch.fnmatch(path, g) for g in globs)


def _path_selected(rel, paths):
    """True if ``rel`` (repo-root-relative, e.g. atomize/general_modules/x.py) is
    named by any user-given ``paths``. Accepts the full relative path, a trailing
    suffix, or a bare basename so ``--lift FORK client.py`` just works."""
    for p in paths:
        p = p.replace(os.sep, "/")
        if rel == p or rel.endswith("/" + p) or os.path.basename(rel) == p:
            return True
    return False


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


def _copy_set(src_repo, dst_repo, globs, label, dry_run=False, only=None, allow=()):
    """Copy src_repo->dst_repo for every file matching ``globs`` that differs in
    content or is missing in the destination, skipping anything in EXPECTED.
    Content comparison is EOL-normalised, and writes preserve the destination's
    line endings.

    ``only`` (optional) restricts the operation to that explicit set of relative
    paths — used by ``--lift`` so a single fork-side feature can be ported to
    plain without dragging along every other drifting file.

    ``allow`` (optional) is a glob set that is EXEMPTED from the EXPECTED skip —
    used by ``--sync-cc`` to copy the named shared control-centre tools even
    though ``control_center/*`` is otherwise EXPECTED (never auto-synced)."""
    src_files = list_files(src_repo)
    dst_files = list_files(dst_repo)
    changed = []
    for rel, src in sorted(src_files.items()):
        if not matches(rel, globs) or (matches(rel, EXPECTED) and not matches(rel, allow)):
            continue
        if only is not None and not _path_selected(rel, only):
            continue
        if rel not in dst_files:
            changed.append(("+", rel))
        elif norm(src) != norm(dst_files[rel]):
            changed.append(("~", rel))
        else:
            continue
        if not dry_run:
            _write_preserving_eol(src, os.path.join(ROOT, dst_repo, rel))
    verb = "would copy" if dry_run else "copied"
    print(f"\n=== {label} ===")
    if not changed:
        print("  already in sync — nothing to do")
    for sign, rel in changed:
        print(f"  {verb} {sign} {rel}")
    return [rel for _, rel in changed]


def sync(fork, globs, label, dry_run=False):
    """Distribute plain -> fork for the shared, plain-led file set."""
    return len(_copy_set(LEAD, fork, globs, f"{fork}: {label}", dry_run=dry_run))


def lift(fork, dry_run=False, only=None):
    """Port a fork's version of a shared file UP to plain (fork -> plain).

    This is the deliberate inverse of ``--sync``: a feature developed fork-side
    is lifted into plain (the integration point) so ``--sync`` can then fan it
    out to the other forks. It writes to PLAIN — the source of truth for every
    fork — so callers gate the bulk form behind an explicit opt-in (see main)."""
    return _copy_set(fork, LEAD, PLAIN_LEAD, f"lift {fork} -> plain",
                     dry_run=dry_run, only=only)


def sync_cc(fork, dry_run=False, only=None):
    """Distribute the shared EPR control-centre tools EPR_LEAD -> fork.

    Fork -> fork (ITC-led), independent of the plain-led sets: these tools don't
    exist in plain. ``allow=CONTROL_CENTER_SHARED`` exempts exactly the named
    files from the EXPECTED ``control_center/*`` skip; every other control-centre
    file in the destination is left untouched."""
    return _copy_set(EPR_LEAD, fork, CONTROL_CENTER_SHARED,
                     f"{fork}: EPR control-centre tools", dry_run=dry_run,
                     only=only, allow=CONTROL_CENTER_SHARED)


def audit_cc():
    """Report drift of the shared EPR control-centre tools across the endstation
    forks against EPR_LEAD (ITC). Plain isn't involved — these are fork-led."""
    lead = list_files(EPR_LEAD)
    cc = sorted(r for r in lead if matches(r, CONTROL_CENTER_SHARED))
    print(f"\n===== EPR control-centre  (lead: {EPR_LEAD}, {len(cc)} shared tools) =====")
    any_drift = False
    for fork in EPR_FORKS:
        fk = list_files(fork)
        differ = [r for r in cc if r in fk and norm(lead[r]) != norm(fk[r])]
        missing = [r for r in cc if r not in fk]
        if not (differ or missing):
            print(f"  {fork}: in sync with {EPR_LEAD}")
            continue
        any_drift = True
        for r in differ:
            print(f"  {fork}: ~ {r}")
        for r in missing:
            print(f"  {fork}: - {r}  (missing in fork)")
    return any_drift


def check_config(fork):
    """Report config-file drift (fork vs plain). Config is EXPECTED-hidden in the
    normal audit because it holds per-installation hardware settings, so this is
    REVIEW-ONLY: eyeball each, then --port-config by hand the ones that should
    actually move (a new device's default config, a shared new option)."""
    lead = list_files(LEAD)
    fk = list_files(fork)
    cfg = sorted(r for r in (set(lead) | set(fk)) if matches(r, CONFIG_FILES))
    differ = [r for r in cfg if r in lead and r in fk and norm(lead[r]) != norm(fk[r])]
    missing = [r for r in cfg if r in lead and r not in fk]
    extra = [r for r in cfg if r not in lead and r in fk]
    print(f"\n===== {fork}: config vs plain ({len(cfg)} files) =====")
    if not (differ or missing or extra):
        print("  identical to plain")
        return False
    for r in differ:
        print(f"  ~ {r}  (differs — usually per-installation hardware)")
    for r in missing:
        print(f"  - {r}  (in plain, MISSING in fork — new device default config?)")
    for r in extra:
        print(f"  + {r}  (fork-only)")
    return True


def port_config(fork, files, dry_run=False, to_plain=False):
    """Manually copy NAMED config file(s) between plain and a fork. Config is in
    EXPECTED (never auto-synced) because it's per-installation; this is the opt-in
    escape hatch for the files that SHOULD move. Default plain->fork (seed a new
    device's default config); ``to_plain`` reverses it (publish a fork-authored
    config up). Requires explicit file names — NEVER bulk-copies hardware config."""
    src, dst = (fork, LEAD) if to_plain else (LEAD, fork)
    return _copy_set(src, dst, CONFIG_FILES, f"port config {src} -> {dst}",
                     dry_run=dry_run, only=files, allow=CONFIG_FILES)


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

SYNC-CC (ITC -> endstation forks; the SHARED EPR control-centre tools only)
  python3 sync_check.py --sync-cc        push ITC's shared CC tools to all EPR forks
  python3 sync_check.py --sync-cc <Fork>           ... to one endstation fork
  python3 sync_check.py --sync-cc <Fork> <path>    ... just that tool (basename ok)
  python3 sync_check.py --sync-cc -n     dry-run: show what WOULD change
  These tools (data_treatment, data_treatment_2d, deer_analysis, excitation_profile,
  sequence_calculator, spin_dynamics_sim) live only in the endstation forks, are
  developed in ITC, and are mirrored to the others. Every OTHER control_center file
  (fork-specific widgets, presets, wiring) is left untouched.

CONFIG (per-installation, EXPECTED -> never auto-synced; review + manual port)
  python3 sync_check.py --check-config             show config drift vs plain (all forks)
  python3 sync_check.py --check-config <Fork>      ... one fork
  python3 sync_check.py --port-config <Fork> <file.ini>   copy ONE config plain->fork
  python3 sync_check.py --port-config <Fork> <file.ini> --to-plain   ... fork->plain
  python3 sync_check.py --port-config <Fork> <file.ini> -n           dry-run
  Config holds per-installation hardware settings, so it is EXPECTED to differ and
  is never carried by --sync. --check-config un-hides the drift for review;
  --port-config is the opt-in copy for the files that SHOULD move (a new device's
  default config, a shared new option). It requires explicit file names (basename
  ok) — it never bulk-copies hardware config.

LIFT (fork -> plain; port a fork-side feature UP into plain)
  python3 sync_check.py --lift <ForkName>          preview what the fork is ahead on
  python3 sync_check.py --lift <ForkName> <path>   lift just that file (basename ok)
  python3 sync_check.py --lift <ForkName> --all    lift every shared file the fork leads
  python3 sync_check.py --lift <ForkName> ... -n   dry-run
  Writes to PLAIN (the lead). Preview-only unless you name path(s) or pass --all,
  since plain is the source of truth for every fork. After lifting, run --sync to
  fan the change out to the other forks. EXPECTED/per-fork files are never touched.

  python3 sync_check.py -h | --help      show this help

KNOWN FORKS
  {forks}

EPR ENDSTATION FORKS (share ITC-led control-centre tools via --sync-cc)
  {epr_forks}  (lead: {epr_lead})

WHAT --sync COPIES
  Shared, plain-led framework files that should be identical everywhere:
  device_modules/, math_modules/, general_modules/, main/, __main__.py.
  EXPECTED files are always skipped, so genuine per-fork divergences are safe:
  last_dir.py (backend), local_config.py (app_name), the fork-only
  main.py/__main__.py, control_center/, configs.

WORKFLOW
  plain is the integration point. Develop a GUI/feature in a fork, lift it to
  plain with --lift (fork -> plain), then run --sync to distribute it to the
  others. Run an audit first to see direction. --lift writes to the lead so it
  only ever acts on the file(s) you name (or --all); --sync pushes plain->fork.

NOTES
  * atomize/ package only; repo-root libs/, tests/, setup.py are fork-specific.
  * CRLF vs LF never counts as drift; --sync preserves each target's line endings.
  * Audits .py and .ini only — NOT markdown docs (those mirror from atomize_docs).
  * New intentional divergence -> add a glob to EXPECTED ("ForkName:glob" for
    per-fork). New fork -> FORKS. Widen/narrow auto-sync via PLAIN_LEAD/DRIVERS.
  * EPR control-centre tools are fork-led (ITC), NOT in plain: synced fork->fork
    with --sync-cc. New shared tool -> CONTROL_CENTER_SHARED. New endstation fork
    that should receive them -> EPR_FORKS.
"""


def _check_fork(name):
    if name not in FORKS:
        sys.exit(f"unknown fork {name!r}; known: {', '.join(FORKS)}")


def _check_epr_fork(name):
    if name not in EPR_FORKS:
        sys.exit(f"unknown EPR fork {name!r}; known: {', '.join(EPR_FORKS)} "
                 f"(lead {EPR_LEAD} is the source, not a target)")


def main():
    args = sys.argv[1:]
    if "-h" in args or "--help" in args:
        print(USAGE.format(forks=", ".join(FORKS),
                           epr_forks=", ".join(EPR_FORKS), epr_lead=EPR_LEAD))
        return

    if "--apply-drivers" in args:
        named = [a for a in args if not a.startswith("-")]
        if not named:
            sys.exit("usage: sync_check.py --apply-drivers <ForkName>")
        _check_fork(named[0])
        sync(named[0], DRIVERS, "device drivers", dry_run="-n" in args)
        return

    if "--lift" in args:
        # fork -> plain: port a fork-side feature UP into plain. Writes to PLAIN
        # (the lead / source of truth for every fork), so the bulk form is gated
        # behind --all; otherwise we only PREVIEW unless explicit paths are named.
        dry = "-n" in args
        take_all = "--all" in args
        named = [a for a in args if not a.startswith("-")]
        if not named:
            sys.exit("usage: sync_check.py --lift <ForkName> [path ...] [--all] [-n]")
        fork, paths = named[0], named[1:]
        _check_fork(fork)
        if paths:
            changed = lift(fork, dry_run=dry, only=paths)
            if not changed:
                print("  (no shared file matched those path(s) — typo, or already in sync)")
        elif take_all:
            changed = lift(fork, dry_run=dry)
        else:
            # safety: no paths and no --all -> show candidates, write nothing.
            changed = lift(fork, dry_run=True)
            if changed:
                print("\n  ^ preview only. Lift specific files:")
                print(f"      python3 sync_check.py --lift {fork} <path ...>")
                print(f"    or all of them:  python3 sync_check.py --lift {fork} --all")
        return

    if "--check-config" in args:
        # review-only: un-hide the EXPECTED config files so drift can be judged.
        named = [a for a in args if not a.startswith("-")]
        targets = named or FORKS
        for t in targets:
            _check_fork(t)
        any_drift = False
        for f in targets:
            any_drift |= check_config(f)
        print()
        print("Config drift above — per-installation settings are EXPECTED to differ.\n"
              "Move only new device default configs / shared options, by hand:\n"
              "    python3 sync_check.py --port-config <Fork> <file.ini>"
              if any_drift else "All config files identical to plain.")
        return

    if "--port-config" in args:
        # manual, explicit-file-only config copy (default plain->fork).
        dry = "-n" in args
        to_plain = "--to-plain" in args
        named = [a for a in args if not a.startswith("-")]
        if not named:
            sys.exit("usage: sync_check.py --port-config <ForkName> <file ...> "
                     "[--to-plain] [-n]")
        fork, files = named[0], named[1:]
        _check_fork(fork)
        if not files:
            # safety: name the exact file(s) — never bulk-copy hardware config.
            print("  name the config file(s) to port (basename ok), e.g.:")
            print(f"      python3 sync_check.py --port-config {fork} Lakeshore_335_config.ini")
            print(f"  see what differs first:  python3 sync_check.py --check-config {fork}")
            return
        changed = port_config(fork, files, dry_run=dry, to_plain=to_plain)
        if not changed:
            print("  (no config file matched those name(s) — typo, or already in sync)")
        return

    if "--sync-cc" in args:
        # ITC -> endstation forks: the shared EPR control-centre tools only.
        # Named tokens split into target forks (in EPR_FORKS) and optional file
        # filters (basename ok), like --lift. A token that looks like a fork
        # name but isn't a known EPR fork is a typo -> clear error.
        dry = "-n" in args
        named = [a for a in args if not a.startswith("-")]
        # A token is a file filter iff it looks like one (.py or contains '/');
        # everything else is a fork name and must be a known EPR fork (a typo'd
        # fork would otherwise be silently swallowed as a no-match filter).
        paths = [a for a in named if a.endswith(".py") or "/" in a] or None
        fork_tokens = [a for a in named if not (a.endswith(".py") or "/" in a)]
        for a in fork_tokens:
            _check_epr_fork(a)
        forks = fork_tokens or EPR_FORKS
        total = sum(len(sync_cc(f, dry_run=dry, only=paths)) for f in forks)
        tip = "  (dry-run — re-run without -n to apply)" if dry else ""
        print(f"\n{total} file(s) {'would change' if dry else 'synced'}.{tip}")
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
    # Also report the fork-led EPR control-centre tools (ITC -> endstation forks)
    # whenever the run covers the lead and at least one of its EPR targets.
    if EPR_LEAD in targets and any(f in targets for f in EPR_FORKS):
        any_drift |= audit_cc()
    print()
    print("Drift found — review above." if any_drift
          else "All forks in sync (only expected divergence).")


if __name__ == "__main__":
    main()
