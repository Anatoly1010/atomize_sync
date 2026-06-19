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

# LIFT  (fork -> plain; port a fork-side feature UP into plain)
python3 sync_check.py --lift Atomize_ITC                # preview what ITC is ahead on
python3 sync_check.py --lift Atomize_ITC client.py      # lift one file (basename ok)
python3 sync_check.py --lift Atomize_ITC --all          # lift everything ITC leads
python3 sync_check.py --lift Atomize_ITC client.py -n   # dry-run

# SYNC-CC  (ITC -> endstation forks; the shared EPR control-centre tools only)
python3 sync_check.py --sync-cc                          # ITC -> all EPR forks
python3 sync_check.py --sync-cc Atomize_NIOCH            #   ... to one fork
python3 sync_check.py --sync-cc Atomize_NIOCH deer_analysis.py   # one tool (basename ok)
python3 sync_check.py --sync-cc -n                       # dry-run

# CONFIG  (per-installation; EXPECTED -> never auto-synced; review + manual port)
python3 sync_check.py --check-config                     # config drift vs plain (all forks)
python3 sync_check.py --check-config Atomize_NIOCH       #   ... one fork
python3 sync_check.py --port-config Atomize_NIOCH Rigol_mso8104_config.ini      # copy ONE config plain->fork
python3 sync_check.py --port-config Atomize_ITC Foo_config.ini --to-plain       #   ... fork->plain
python3 sync_check.py --port-config Atomize_NIOCH Rigol_mso8104_config.ini -n   # dry-run

python3 sync_check.py -h                     # help
```

Known forks: `Atomize_ITC`, `Atomize_NIOCH`, `Atomize_Cryomech`.

### `--sync` — distribute shared files plain → fork

Copies the shared, plain-led framework files that should be identical
everywhere — `device_modules/`, `math_modules/`, `general_modules/`, `main/`,
`__main__.py` — into the fork(s). It **skips every EXPECTED file**, so the
genuine per-fork divergences are never clobbered: `last_dir.py` (backend),
`local_config.py` (app_name), the fork-only `main.py` / `__main__.py`,
`control_center/`, configs.

Comparison is EOL-normalised (only real content differences are copied) and
writes **preserve each target's line endings** (a CRLF fork file stays CRLF).
Use `-n` for a dry-run first. `--apply-drivers` is the narrow variant that only
touches `device_modules/*.py`.

### `--lift` — port a fork feature up to plain (fork → plain)

The inverse of `--sync`. When a shared GUI/general feature is developed in a
fork, `--lift` copies the fork's version of the shared file(s) **up into plain**
(the integration point), so `--sync` can then fan it out to the other forks.

Because it writes to **plain — the source of truth for every fork** — it is
deliberately conservative:

- `--lift FORK` with no file names only **previews** what the fork is ahead on
  and writes nothing.
- name one or more files (full path, suffix, or bare basename) to lift exactly
  those, or pass `--all` to lift every shared file the fork leads.
- requires **one** fork (you can't lift "from all forks" — which version wins?).
- skips every `EXPECTED`/per-fork file, EOL-normalises the comparison, and
  preserves plain's line endings — same safety rules as `--sync`.

Typical flow: `--lift FORK file.py` → review plain → `--sync` to distribute.

### `--sync-cc` — share the EPR control-centre tools (ITC → endstation forks)

A handful of control-centre data-analysis tools are **shared among the EPR
endstation forks but do not exist in plain Atomize**, so the plain-led machinery
above can't carry them. They are developed in **ITC** and mirrored to the other
endstation forks. `--sync-cc` is the deliberate path for that — a **fork → fork,
ITC-led** sync, independent of `--sync`/`--lift`.

The shared tools (`CONTROL_CENTER_SHARED`):
`data_treatment.py`, `data_treatment_2d.py`, `deer_analysis.py`,
`excitation_profile.py`, `sequence_calculator.py`, `spin_dynamics_sim.py`.

- `--sync-cc` copies ITC → **all** endstation forks (`EPR_FORKS`); name a fork to
  target just one, and name `.py` file(s) after it to copy just those tools.
- `control_center/*` stays in `EXPECTED`, so **every other control-centre file**
  (fork-specific widgets, presets, launcher wiring) is left untouched — only the
  named shared tools are exempted from the skip and copied.
- EOL-normalised comparison, destination line endings preserved, `-n` dry-run —
  same safety rules as `--sync`. A mistyped fork name is a hard error.

The default audit also prints an **"EPR control-centre"** section (ITC vs the
endstation forks for these tools) whenever the run covers ITC and at least one
of its EPR forks.

### `--check-config` / `--port-config` — config files (manual only)

Device + main config (`config.ini`, `device_modules/config/*.ini`) hold
**per-installation hardware settings** (GPIB addresses, serial ports, IPs,
calibration), so they are in `EXPECTED` and **never** carried by `--sync`. Two
cases still legitimately move: a **new device's default config** added upstream
(seed the fork, then the operator edits it), and a **shared new option/key**.

- `--check-config [Fork]` is **review-only**: per fork vs plain it reports configs
  that `~` differ (usually expected hardware settings), `-` are missing in the
  fork (a new device default to seed), or `+` are fork-only.
- `--port-config <Fork> <file.ini ...>` is the **opt-in manual copy**: it requires
  explicit file name(s) (basename ok) — **never bulk-copies** hardware config —
  defaults to plain → fork, takes `--to-plain` to publish a fork config up, and
  honours `-n`. Same EOL rules as `--sync`.

Typical flow: `--check-config FORK` → spot a `- missing` device config →
`--port-config FORK That_config.ini`.

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
| shared GUI/general (`main_window.py`, `widgets.py`, `csv_opener_saver.py`, `client.py`, …) | **plain** (after lifting the fork feature up) | fork → plain (`--lift`), then plain → fork (`--sync`) |
| shared EPR control-centre tools (`data_treatment*`, `deer_analysis.py`, `excitation_profile.py`, `sequence_calculator.py`, `spin_dynamics_sim.py`) — endstation forks only, not in plain | **ITC** | fork → fork (`--sync-cc`) |
| other `control_center/`, scripts, configs, `main.py`, `local_config.py` | **per fork** | not synced (EXPECTED) |
| docs (`atomize/documentation/`) | **`atomize_docs` repo** | atomize_docs → all |

`--sync` only ever pushes plain → fork. So if a fork is *ahead* of plain on a
shared file, lift it to plain first with `--lift` (the audit shows you the
direction), then `--sync`.

## Maintaining the manifest

Edit the constants at the top of `sync_check.py`:

- **`FORKS`** — add a new control-centre fork here and it's audited automatically.
- **`EXPECTED`** — fnmatch globs (relative to repo root) that are *allowed* to
  differ. Use `"ForkName:glob"` to scope an exemption to a single fork.
  Currently exempts: `control_center/*`, `script_examples/*`, `tests/*`,
  `config.ini`, device `config/*.ini`, `last_dir.py` (backend differs),
  `local_config.py` (app_name isolation), `main/main.py` (fork-only
  MainExtended), `__main__.py`, the fork-only `Keysight_2000_Xseries_2.py`, and
  Metrolab. (`main_window.py` was promoted to plain-led — now `--sync`'d.)
- **`PLAIN_LEAD`** — the broad shared-framework set `--sync` pushes plain →
  fork: `device_modules/`, `math_modules/`, `general_modules/`, `main/`,
  `__main__.py` (minus whatever EXPECTED skips).
- **`DRIVERS`** — the narrow set `--apply-drivers` uses: `device_modules/*.py`.
- **`EPR_LEAD` / `EPR_FORKS` / `CONTROL_CENTER_SHARED`** — the `--sync-cc` set:
  the lead is `Atomize_ITC`, the recipients are `EPR_FORKS` (add a future
  endstation fork here so it starts receiving the tools), and
  `CONTROL_CENTER_SHARED` lists the shared tool paths (add a new shared tool
  here). These are copied even though they live under the EXPECTED
  `control_center/*`.
- **`CONFIG_FILES`** — the config set `--check-config`/`--port-config` work on
  (`config.ini`, `device_modules/config/*.ini`). Also in EXPECTED, so they're
  never auto-synced; these two commands are the manual review/port escape hatch.

## Notes / gotchas

- Audits **`.py` and `.ini` only** — markdown docs are not checked; refresh them
  by re-mirroring `atomize_docs/docs/` into each repo's `atomize/documentation/`
  (exclude the web-only pages: `index/requirements/usage/ui_style/contributors`,
  `projects/`, `images/`, `javascripts/`, `stylesheets/`).
- CRLF vs LF is never reported as drift.
- Repo-root scaffolding (`libs/`, `tests/`, `setup.py`, `pyproject.toml`) is
  fork-specific by nature and not audited — only the shared `atomize/` package is.
