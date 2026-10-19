# Deep River New Era ingest pipeline

This pipeline turns scan lists (TIFF filenames) and Town List spreadsheets for the *Deep River New Era* into per-year CSV files that the library's repository ingest can load. Each run reads the input folder, matches each issue's pages to its towns, adds any new issues to the year files, and reports anything that needs a human look.

The code is split across a short entry point and a package:

```
build_issue_csv.py          entry point (run this)
newspaper_ingest/           the pipeline code (16 modules)
notes_config.txt            the credits text used in every issue's notes field
run_from_drive.py           calls build_issue_csv.py (unchanged)
README.md                   this file
docs/BEHAVIOR.md            what the pipeline does in every situation
docs/CODE.md                reference for the code itself
```

## Quick start

1. Put the tifflist files and Town List files into `DataWaiting/`.
2. Run:
   ```
   python build_issue_csv.py <root_folder>
   ```
3. Look in `IngestFiles/<year>/` for the new CSVs (and matching `.xlsx` copies), and in `MergeReports/` for the run report.

Re-running is safe. Issues already written are recognized and left alone.

## Folder layout

The root folder holds these subfolders. They are created automatically the first time the script runs.

| Folder | What it holds |
|---|---|
| `DataWaiting/` | Input. Tifflist and Town List files go here. |
| `DataFilesCompleted/` | Input files moved here once everything in them has been used. |
| `IngestFiles/<year>/` | Output. One folder per year, containing `<year>-ingest.csv` (or `<year>-ingest_partN.csv` when a year grows large), a matching `.xlsx` copy of each CSV, and a count file such as `48issues432pages481lines.txt`. |
| `MergeReports/` | `Ingest_merge_report_<timestamp>.txt`. Written only when the run added something, found a difference, or the set of problems changed. |
| `_Logs/` | `run_log.txt`, one line per run. `last_problems.txt` and `last_corrections.txt`, what the previous run reported, used to decide whether anything is new (so the same thing is not emailed twice). Do not edit. |

## Input files

**Tifflist** (lists the scanned pages). Any of these is picked up:
- a `.txt` or `.csv` whose name ends in `tifflist` (for example `Vol_XI_tifflist.txt`), or
- any other `.txt` or `.csv` in `DataWaiting/` where at least half the non-blank lines contain a TIFF filename.

Each line is either a plain filename, a full path, or a Windows `dir` listing line. Filenames look like:

```
18850116_vXI_n41_0001.tif
YYYYMMDD _ vVOLUME _ nPAPERNUMBER _ PAGE .tif
```

The page part is optional. A filename without one is treated as page 1.

**Town List** (lists the towns each issue covers). A `.xlsx` or `.csv` file with "Town List" in its name (for example `Vol_XI_Town_List.xlsx`). Three layouts are recognized automatically:
- **Format A**: one row per issue, with a `No.` or `Paper No.` column and a `File` column, and towns across the row.
- **Format B**: paper numbers across the top row, towns stacked down each column.
- **Format C** ("Slim"): a filename column plus a `Subject` column already filled in as `Newspaper -- Town, CT`.

In manual mode the Town List can also be a Google Sheets link. The sheet must be shared as "Anyone with the link can view".

## Setup

1. **Python 3.9 or newer.**
2. **`openpyxl`** (`pip install openpyxl`). It is needed for `.xlsx` Town Lists and for writing the `.xlsx` copies, which the pipeline makes for every file it writes.
3. **`notes_config.txt`** in the repository root, next to `build_issue_csv.py`. One credit per line, as `note type: note text`. Blank lines and lines starting with `#` are ignored. If the file is missing, the script stops before doing anything.
4. **Alert email (optional).** Set the `EMAIL_APP_PASSWORD` environment variable to a Gmail app password. Without it, alerts are skipped and the run continues. Addresses and sender are set in `newspaper_ingest/config.py` (`EMAIL_SENDER`, `EMAIL_RECIPIENTS`).

## Commands

```
python build_issue_csv.py <root_folder>
python build_issue_csv.py --by-year <root_folder>          # same as above

python build_issue_csv.py <tiff_dir_or_listing> <townlist_file_or_sheet_url>   # manual mode
```

The first two read everything in `DataWaiting/` and are the normal way to run it. Manual mode handles a one-off pair of files that is not in the folder layout. See `docs/BEHAVIOR.md`, situation 23.

## Where things are configured

| Setting | Where |
|---|---|
| Fixed credits, rights statement, held-by, collection ID, column list | `newspaper_ingest/config.py` |
| Publisher names and the dates they took over | `PUBLISHER_BY_DATE` in `newspaper_ingest/config.py` |
| Digital file path base on the server | `DIGITAL_FILE_BASE` in `newspaper_ingest/config.py` |
| Maximum rows per ingest file (default 800) | `TARGET_LINES_PER_FILE` in `newspaper_ingest/config.py` |
| Gap between years that forces a new file | `MAX_CONTIGUOUS_YEAR_GAP` in `newspaper_ingest/config.py` |
| How far apart neighbors can be for date correction | `MAX_DATE_CORRECTION_GAP_DAYS` in `newspaper_ingest/config.py` |
| Notes credits | `notes_config.txt` |
| Email password | `EMAIL_APP_PASSWORD` environment variable |

## Things to know

- A year with a problem that could be a missing piece is held back as a whole. Its new issues are not written until the problem is fixed. This is deliberate. See `docs/BEHAVIOR.md`.
- Nothing is lost by a hold-back. Every run rebuilds the picture from the input files, so a held-back issue is picked up as soon as its missing piece appears.
- Dates in filenames are checked. Some typos are corrected automatically and reported. Others are reported and held back. See `docs/BEHAVIOR.md`, situations 7 and 8.
- The `.xlsx` copies are regenerated from the CSVs each time a file is written. Edit the CSV, not the `.xlsx`.
- Each year folder has a **count file** whose name gives the year's totals, for example `48issues432pages481lines.txt`: 48 issues, 432 pages, and 481 lines across the year's ingest CSVs, header lines included (the number `wc -l` shows). It is recounted from the CSVs on every run and renamed when the totals change, so there is only ever one. Inside is the same information, each CSV's line count, and a list of every issue in the year, one per line, by date, with volume, issue number, and page count. Use it to check whether a year is complete before giving its ingest file to Patrick.
- **Marking a year finished.** When a year's ingest file has been handed over, create an empty file named `ingest_complete` in that year's folder (`IngestFiles/1922/ingest_complete`). The pipeline then never changes that year's existing ingest files. If new issues for that year turn up anyway, they go into a new numbered file (`1922-ingest_part2.csv`, and so on) and the run reports it (merge report, console, and an alert email). See `docs/BEHAVIOR.md`, situation 24.

## Documentation

- `docs/BEHAVIOR.md`: what happens in each situation, what files move, when emails are sent.
- `docs/CODE.md`: module-by-module reference for developers.
