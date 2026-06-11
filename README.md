# Atomize fork-sync auditor

`sync_check.py` keeps the Atomize fork family consistent. It compares each
fork's `atomize/` package against the upstream lead (**plain `Atomize`**),
EOL-normalised, and prints **only real drift** — everything in its manifest of
intentional divergence is hidden.

Lives outside the repos (`/home/anatoly/atomize_sync/`) so it never needs
syncing itself. Repos audited live next to it under `/home/anatoly/`.

## Usage

```bash
cd /home/anatoly/atomize_sync

# AUDIT (read-only)
python3 sync_check.py                       # audit every fork (drift-only)
python3 sync_check.py -v                    # + count of ignored/expected files
python3 sync_check.py Atomize_ITC           # audit just one fork

# SYNC  (plain -> fork; never touches EXPECTED/per-fork files)
python3 sync_check.py --sync                # distribute shared files to ALL forks
python3 sync_check.py --sync Atomize_NIOCH  #   ... to one fork
python3 sync_check.py --sync -n             # dry-run: show what WOULD change
python3 sync_check.py --apply-drivers Atomize_NIOCH   # device_modules only (narrow)

python3 sync_check.py -h                     # help
```

Known forks: `Atomize_ITC`, `Atomize_NIOCH`, `Atomize_Cryomech`.

### `--sync` — distribute shared files plain → fork

Copies the shared, plain-led framework files that should be identical
everywhere — `device_modules/`, `math_modules/`, `general_modules/`, `main/`,
`__main__.py` — into the fork(s). It **skips every EXPECTED file**, so the
genuine per-fork divergences are never clobbered: `last_dir.py` (backend),
`main_window.py`, `local_config.py` (app_name), the fork-only `main.py` /
`__main__.py`, `control_center/`, configs.

Comparison is EOL-normalised (only real content differences are copied) and
writes **preserve each target's line endings** (a CRLF fork file stays CRLF).
Use `-n` for a dry-run first. `--apply-drivers` is the narrow variant that only
touches `device_modules/*.py`.

### What the report means

```
===== Atomize_ITC =====
  DRIFT — differs from plain (N):        ~ file   content differs
  DRIFT — in plain, MISSING in fork (N): - file   plain has it, fork doesn't
  DRIFT — fork-only, not in plain (N):   + file   fork has it, plain doesn't
```

`IN SYNC (only expected divergence)` = nothing to do for that fork.

## Direction of truth (important)

Plain is **not** globally the lead — it depends on the category. plain is the
**integration point**: features developed fork-side are lifted to plain by hand,
then `--sync` distributes them plain → fork.

| Category | Lead / source | Flow |
|---|---|---|
| `device_modules/`, math cores (`deer.py`, …) | **plain** | plain → fork (`--sync`) |
| shared GUI/general (`widgets.py`, `csv_opener_saver.py`, `client.py`, …) | **plain** (after lifting the fork feature up) | fork → plain by hand, then plain → fork (`--sync`) |
| `control_center/`, scripts, configs, `main_window.py`, `local_config.py` | **per fork** | not synced (EXPECTED) |
| docs (`atomize/documentation/`) | **`atomize_docs` repo** | atomize_docs → all |

`--sync` only ever pushes plain → fork. So if a fork is *ahead* of plain on a
shared file, lift it to plain first (the audit shows you the direction), then
`--sync`.

## Maintaining the manifest

Edit the constants at the top of `sync_check.py`:

- **`FORKS`** — add a new control-centre fork here and it's audited automatically.
- **`EXPECTED`** — fnmatch globs (relative to repo root) that are *allowed* to
  differ. Use `"ForkName:glob"` to scope an exemption to a single fork.
  Currently exempts: `control_center/*`, `script_examples/*`, `tests/*`,
  `config.ini`, device `config/*.ini`, `last_dir.py` (backend differs),
  `local_config.py` (app_name isolation), `main_window.py`, `main/main.py`,
  `__main__.py`, the fork-only `Keysight_2000_Xseries_2.py`, and Metrolab.
- **`PLAIN_LEAD`** — the broad shared-framework set `--sync` pushes plain →
  fork: `device_modules/`, `math_modules/`, `general_modules/`, `main/`,
  `__main__.py` (minus whatever EXPECTED skips).
- **`DRIVERS`** — the narrow set `--apply-drivers` uses: `device_modules/*.py`.

## Notes / gotchas

- Audits **`.py` and `.ini` only** — markdown docs are not checked; refresh them
  by re-mirroring `atomize_docs/docs/` into each repo's `atomize/documentation/`
  (exclude the web-only pages: `index/requirements/usage/ui_style/contributors`,
  `projects/`, `images/`, `javascripts/`, `stylesheets/`).
- CRLF vs LF is never reported as drift.
- Repo-root scaffolding (`libs/`, `tests/`, `setup.py`, `pyproject.toml`) is
  fork-specific by nature and not audited — only the shared `atomize/` package is.
