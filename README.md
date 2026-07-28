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
  ("tifflist" files) and town/subject metadata ("Town List" files),
  matches them up, and produces Islandora-compatible ingest CSVs. It's
  idempotent: re-running it against the same data never duplicates or
  silently overwrites previously reviewed issues. Changed data on an
  already-processed issue gets flagged for human review rather than
  overwritten automatically.

- **`notes_config.txt`** — a plain text file listing the contributor
  credits attached to every issue. Editing this file is how credits get
  added or changed; no code changes needed.

- **`run_from_drive.py`** — a wrapper that lets `build_issue_csv.py` run
  automatically on a schedule via GitHub Actions, even though GitHub's
  servers have no Google Drive folder of their own. It downloads the
  working files from Drive into a temporary folder, runs
  `build_issue_csv.py` against them exactly as it runs locally, then
  uploads back whatever's new or changed.

- **`.github/workflows/run-issue-builder.yml`** — the schedule
  definition: runs every 30 minutes on weekdays and hourly on weekends,
  roughly 7am–11pm Eastern.

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

GitHub Actions cron schedules run in UTC and don't automatically adjust
for daylight saving time. The schedule in
`run-issue-builder.yml` is written for Eastern Daylight Time (UTC-4).
Twice a year, it needs a one-hour adjustment:

- **Early November** (clocks fall back to EST, UTC-5): add 1 to each
  hour in the cron schedule.
- **Mid-March** (clocks spring forward to EDT, UTC-4): subtract 1.

A day or two of drift right around the change itself isn't worth
worrying about.

## Contributors

Patrick McGlamery, Adrian Nicholls, Sandy Forest, Simon LaPlace,
AC Proctor, and Lois Blood Bennett.
