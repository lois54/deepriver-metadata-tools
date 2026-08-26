# Deep River Metadata Tools

Tools for digitizing and cataloging historical issues of the *Deep River
New Era*, a Connecticut newspaper, for ingest into an Islandora-based
digital repository. This project is a collaboration between the Deep
River Public Library, Chester Historical Society, Westbrook Historical
Society, and Deep River Historical Society.

[Islandora](https://islandora.ca/) is an open-source digital repository
platform commonly used by libraries and archives to host and catalog
digitized materials. "Islandora-compatible," used below, means the CSV
files this project produces follow the exact column layout and
formatting Islandora requires for a bulk import to succeed.

## What's in this repo

- **`build_issue_csv.py`** — the core script. Reads TIFF scan listings
  ("tifflist" files) and town/subject metadata ("Town List" files) out
  of a `DataWaiting` folder, matches them up, and produces
  Islandora-compatible ingest CSVs in `IngestFiles`. It's idempotent:
  re-running it against the same data never duplicates or silently
  overwrites previously reviewed issues. Changed data on an
  already-processed issue gets flagged for human review rather than
  overwritten automatically. Input files that were successfully
  processed are moved automatically into `DataFilesCompleted`; a run
  report goes to `MergeReports` whenever something new or noteworthy
  happens. See the script's own header comment for the full breakdown
  of this four-folder layout.

- **`check_duplicates.py`** — runs before `build_issue_csv.py`. Checks
  every file in `DataWaiting` for duplicate entries *within* that one
  file (the same TIFF filename listed twice, or the same paper number
  on two rows). If it finds any, it moves the original file into
  `DataFilesCompleted` tagged `-has_duplicates`, and leaves a corrected
  copy behind under the original name for `build_issue_csv.py` to pick
  up normally.

- **`notes_config.txt`** — a plain text file listing the contributor
  credits attached to every issue. Editing this file is how credits get
  added or changed; no code changes needed.

- **`run_from_drive.py`** — a wrapper that lets `check_duplicates.py`
  and `build_issue_csv.py` run automatically on a schedule via GitHub
  Actions, even though GitHub's servers have no Google Drive folder of
  their own. It downloads each of the managed Drive subfolders
  (`DataWaiting`, `DataFilesCompleted`, `IngestFiles`, `MergeReports`,
  `_Logs`) into a temporary folder, runs both scripts against them
  exactly as they'd run locally, then uploads back whatever's new,
  changed, or moved.

- **`.github/workflows/issue-builder-schedule.yml`** — the schedule
  definition: runs five times a day (9:07am, 12:07pm, 3:07pm, 6:07pm,
  and 9:07pm Eastern).

## Where the actual data lives

**Not here.** All scan listings, metadata, and generated ingest CSVs
live in a Google Drive folder, not in this repository. This repo
contains only code and a small, non-sensitive credits file. Nothing
in this repo, or in any GitHub Actions log it produces, reveals the
content of the newspaper metadata itself.

## How the automation is secured

This repository is public, since there's nothing sensitive in the code
itself. Making the automation work safely under that condition relies
on a few things:

- **Credentials are never in the code.** The script authenticates to
  Google Drive using two credentials — a service account (for reading
  files and updating existing ones) and a narrowly-scoped OAuth
  credential (for creating brand-new files, working around a Google
  Drive quirk where service accounts have no storage quota of their
  own). Both are stored as encrypted [GitHub Actions
  secrets](https://docs.github.com/en/actions/security-guides/encrypted-secrets),
  never committed to the repo, never visible in logs, and never
  exposed even to people who can read the code.

- **Access is scoped to one folder, not the whole Drive.** The service
  account can only see the single Drive folder it's been explicitly
  shared on — sharing it with a folder is what grants access, not
  anything in this code. The OAuth credential is scoped to
  `drive.file` — limited to files it creates itself — rather than
  broad access to the account's entire Drive.

- **Nothing persists on GitHub's servers between runs.** Every
  scheduled run spins up a brand-new, disposable virtual machine.
  Downloaded files live only in that machine's temporary storage for
  the few minutes the job runs, and the whole machine is destroyed
  afterward. No data file is ever written into the git repository
  itself.

- **A public repo does not mean anyone can run this against our
  data.** The workflow only runs on its defined schedule, or via a
  manual "Run workflow" button that's only visible to people with
  write access to this repository. Someone could copy this code (fork
  it) to adapt it for their own Drive folder, but GitHub secrets never
  travel with a fork — a copy of this workflow run anywhere else would
  have no credentials and would fail immediately, unable to reach this
  project's actual data.

## Maintaining the schedule

`issue-builder-schedule.yml` schedules directly in Eastern time, using
GitHub Actions' `timezone` field on the cron trigger. GitHub adjusts
for daylight saving automatically — no manual hour adjustment needed
twice a year.

## Contributors

Patrick McGlamery, Adrian Nicholls, Sandy Forest, Simon LaPlace,
AC Proctor, and Lois Blood Bennett.
