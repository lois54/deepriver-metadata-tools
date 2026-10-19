# Code reference

This document describes the code in `build_issue_csv.py` and the `newspaper_ingest/` package: how the modules fit together, what each function does, and the rules a developer needs to keep in mind when changing it. For what the pipeline does from the user's side, see `docs/BEHAVIOR.md`.

## Structure

The package is layered. A module may import from modules above it in this list, never from modules below. This keeps the import graph free of cycles.

| Layer | Module | Role |
|---|---|---|
| 0 | `config.py` | Fixed values: credits, publisher timeline, folder names, column list, limits |
| 0 | `patterns.py` | Every compiled regular expression |
| 0 | `timeutil.py` | Eastern-time timestamps, long date formatting, ISO date parsing |
| 1 | `volumes.py` | Roman numerals, volume normalization, issue-prefix parsing |
| 2 | `townlist.py` | Reading Town Lists (xlsx, csv, Google Sheets), parsing the three layouts, volume resolution |
| 2 | `tiffs.py` | Parsing TIFF filenames, reading tifflists, finding input files |
| 2 | `notes.py` | Loading `notes_config.txt` |
| 3 | `records.py` | Building per-issue records (title, persons, subject, origin), date correction, gathering inputs |
| 4 | `problems.py` | Problem categories, year extraction, grouping for reports and email |
| 4 | `ingest_rows.py` | Building the 64-column parent and page rows, chunking, duplicate comparison |
| 4 | `ingest_files.py` | Reading and writing the per-year CSVs, `.xlsx` copies, finding already-ingested issues |
| 5 | `runlog.py` | `_Logs/`: run log and last-run problem set |
| 5 | `folders.py` | Creating folders, moving completed input files |
| 5 | `alerts.py` | Building and sending the alert email |
| 5 | `merge.py` | The merge engine: per-year merge, hold-back, report, email trigger |
| 6 | `cli.py` | Command-line modes and `main()` |
| entry | `build_issue_csv.py` | Calls `newspaper_ingest.cli.main()` |

Only `cli.py` and `merge.py` are long. Everything else is small and focused.

## Data flow

A default run goes through these steps.

1. `cli.main` checks that `notes_config.txt` loads. Without it, the run stops.
2. `cli.run_by_year` creates the folders and calls `ingest_files.scan_existing_issue_keys` to collect the `(volume, paper_no)` keys of every issue already in `IngestFiles/<year>/`.
3. `records.gather_all_records` reads every tifflist (`tiffs.read_tiff_list_file`) and every Town List (`townlist.read_grid`, `townlist.parse_town_list`, `townlist.resolve_town_list_volumes`) into one pool. It joins the two pools on `(volume, paper_no)` and produces:
   - `records`: complete issues, each with a title, persons, subject, origin, and pages
   - `problems`: strings beginning with a `[category]` tag
   - `file_usable_counts` and `file_pending`: which input files contributed and which still have unmatched entries
   - `year_to_filenames`: which input files fed each year
   - `corrections`: dates auto-corrected this run
4. `merge.merge_and_write_records` decides which years are held back, then for each year:
   - compares each record against the existing rows (`ingest_files.find_year_ingest_files`, `ingest_rows.normalize_for_compare`)
   - skips and reports duplicates that differ
   - writes new issues, either appended to the active file or into a new file (`ingest_rows.chunk_records_by_line_limit`, `ingest_rows.rows_from_issue_record`)
   - regenerates `.xlsx` copies
   - refreshes the count file in every year folder (`ingest_files.refresh_year_count_files`)
5. `merge.py` writes the merge report if the run was noteworthy, saves the problem set, sends the alert email if the problem set changed, and writes the run log line.
6. `cli.run_by_year` moves input files that are fully used (`folders.move_processed_input_files`). Held-back years keep their sources in `DataWaiting/`.

## Module reference

### `config.py`

Plain constants. No functions.

- `HELD_BY`, `RIGHTS_STATEMENT`, `PUBLISH`, `RESOURCE_TYPE`, `NEWSPAPER_NAME`, `DESCRIPTION`, `MEMBER_OF_EXISTING_ENTITY_ID`, `GENRE`, `LANGUAGE`: fixed values for each row.
- `EMAIL_SENDER`, `EMAIL_RECIPIENTS`: alert email addresses. The password is not stored here.
- `PERSONS_STATIC_SUFFIX`: the fixed credits appended after the publisher in the `persons` field.
- `NOTES_CONFIG_FILENAME`: name of the notes file, looked up in the repository root.
- `ORIGIN_PLACE`, `ORIGIN_ISSUANCE`, `ORIGIN_FREQUENCY`: fixed parts of `origin_information`.
- `PUBLISHER_BY_DATE`: a list of `(effective_date, name)` pairs in date order. See the note below.
- `DIGITAL_FILE_BASE`: server path prefix for `digital_file`. The year folder is always appended.
- `MULTI_SEP` (`^^`): separator for multi-valued cells.
- `TARGET_LINES_PER_FILE` (800): the file size target. Repository hard limit is 1000 lines.
- `MAX_CONTIGUOUS_YEAR_GAP` (1): a gap larger than this between consecutive issues forces a new file.
- `MAX_DATE_CORRECTION_GAP_DAYS` (60): the widest neighbor gap that date correction will trust.
- `COLUMNS`: the 64 column names, in the order the repository expects. Changing the order breaks the ingest.
- Folder and file names: `DATA_WAITING_SUBDIR`, `DATA_COMPLETED_SUBDIR`, `INGEST_FILES_SUBDIR`, `MERGE_REPORTS_SUBDIR`, `LOGS_SUBDIR_NAME`, `RUN_LOG_FILENAME`, `LAST_PROBLEMS_FILENAME`, `LAST_CORRECTIONS_FILENAME`.
- `INGEST_COMPLETE_MARKER_NAMES`: file names (`ingest_complete`, `ingest_complete.txt`) that mark a year folder as complete. Compared in lower case.

**Note on `PUBLISHER_BY_DATE`.** The list is searched in order. The publisher for a date is the last entry whose effective date is on or before it. Where two publishers' ranges share a year (1903), the later publisher is treated as starting on 1 January of that year. This is an assumption and is marked in the source.

### `patterns.py`

Compiled regular expressions. Each has a comment explaining the groups.

- `TIFF_NAME_PATTERN`: anchored match for one TIFF filename. Groups: date, volume, paper number, optional page number.
- `TIFF_NAME_SEARCH_PATTERN`: unanchored version, used to find a filename inside a longer line.
- `GOOGLE_SHEETS_URL_PATTERN`, `GOOGLE_SHEETS_GID_PATTERN`: pull the sheet ID and tab ID from a URL.
- `TIFFLIST_FILENAME_PATTERN`: matches names ending `tifflist.txt` or `tifflist.csv`.
- `TOWNLIST_KEYWORD_PATTERN`: matches "town list" with `_`, `-`, space, or nothing between the words.
- `INGEST_FILENAME_PATTERN`: the older range-based file name, for example `1885-1886-ingest.csv`.
- `YEAR_INGEST_FILENAME_PATTERN`: the current per-year file name, for example `1883-ingest_part2.csv`.
- `ISSUE_PREFIX_PATTERN`: matches the issue part at the start of a string, for example `18850102_vXI_n39`.
- `SUBJECT_ENTRY_PATTERN`: matches one `Newspaper -- Town, CT` entry from a Subject cell.
- `PROBLEM_YEAR_PATTERN`: finds a plausible YYYYMMDD date inside a problem message. Month 01 to 12 and day 01 to 31 are enforced, so a date like `19110231` matches but `19111331` does not.
- `PROBLEM_CATEGORY_PATTERN`: finds the leading `[category]` tag.
- `INVALID_DATE_VALUE_PATTERN`: pulls the bad date out of an `invalid_date` message for the email.
- `SOURCE_LABEL_IN_PROBLEM_PATTERN`: matches the "has been found in N tifflist file(s) yet" phrase in a `missing tiffs` message, for `normalize_problem_for_compare`.
- `YEAR_COUNT_FILENAME_PATTERN`: matches the count file name in a year folder, such as `48issues432pages481lines.txt`.
- `UNRECOGNIZED_ITEM_PATTERN`: pulls the skipped name out of an `unrecognized_filename` message, so the email can group names by file type.
- `PROBLEM_SOURCE_FILE_PATTERN`: pulls the source file tag (`[1924tifflist.txt]`) that precedes the category tag, when there is one.

### `timeutil.py`

- `EASTERN_TZ`: `ZoneInfo("America/New_York")`.
- `now_eastern()`: current time in Eastern.
- `format_eastern_timestamp(dt=None)`: `2026-10-17 02:07:32 PM EDT` style.
- `format_date_long(date_iso)`: `'1885-01-16'` becomes `Jan 16, 1885`. Raises if the input is not a valid date.
- `parse_iso_date_or_none(text)`: a `datetime` for a valid `YYYY-MM-DD`, else `None`.

### `volumes.py`

- `int_to_roman(n)`: 1 becomes `I`, 14 becomes `XIV`.
- `normalize_volume(text)`: digits become roman numerals, letters are uppercased. This is how `1` and `I` are made the same volume.
- `extract_volume_token(prefix)`: strips a `Vol` or lowercase `v` label from the text before a keyword. A lowercase `v` followed by uppercase letters counts as a roman label (`vI`). A bare uppercase `VI` does not.
- `parse_issue_prefix(text)`: returns `(date_iso, volume, paper_no)` from the start of a string, or `None`. If the 8-digit date is not a real calendar date, `date_iso` keeps the raw digits so the caller can detect the problem.
- `volume_from_town_list_filename(filename)`: the volume label from a Town List filename, or `None`.

### `townlist.py`

**Reading.**
- `read_grid(source)`: returns a list of rows of plain-text cells. Dispatches on the source: a Google Sheets URL, an `.xlsx`, or a `.csv`. Anything else raises `ValueError`. `openpyxl` is imported only when an `.xlsx` is read.
- `is_google_sheets_url(text)`.
- `fetch_google_sheet_grid(url)`: downloads the sheet as CSV from the export URL. HTTP errors and network errors are turned into messages that say how to fix the sharing setting or the connection.
- `cell_to_text(value)`: converts an Excel cell to text. Whole-number floats become integers, so `39.0` becomes `39`. Without this, `isdigit()` checks would skip valid issues.

**Parsing.**
- `parse_town_list(grid)`: returns `(town_list, town_dates)`. Chooses the layout:
  - a header row containing both `Subject` and `Geographic` goes to Format C
  - a first cell starting with `Paper` goes to Format B
  - anything else goes to Format A
- `parse_format_a_rows(grid)`: one row per issue. The paper number comes from a `No.` or `Paper No.` column. If there is no such column, the paper number comes from the filename column. A filename column placed before the paper-number column supplies the volume. Every non-blank cell after the number is a town.
- `parse_format_b_transposed(grid)`: paper numbers across the top row, towns down each column. Keys have `volume = None`, to be resolved later.
- `parse_format_c_slim(grid)`: reads towns back out of the `Subject` column, not the `Geographic` column. This protects against drift if the Geographic column was hand-edited.

**Discovery and resolution.**
- `is_town_list_filename(name)`: `.xlsx` or `.csv` with the keyword in the name.
- `find_town_list_source_files(directory)`: sorted list of Town List filenames in a folder.
- `resolve_town_list_volumes(town_lists, tiff_issues, filename_hint)`: replaces `None` volumes. It tries, in order, the volume label in the Town List filename, then the single volume present in the TIFF data. If neither works, the rows are dropped and an `unresolved_volume` problem is returned.

### `tiffs.py`

- `build_digital_file(date_iso, filename)`: `DIGITAL_FILE_BASE` + year + filename. The year is always taken from the date, never from the listing.
- `parse_tiff_filename(filename)`: returns `(issue_id, date_iso, volume, paper_no, page_number)` or `None`. The `issue_id` is `YYYYMMDD_vVOL_nNUM` and uses the raw digits, so an invalid date still gets a stable ID. A missing page number becomes page 1.
- `_add_page(...)`: adds one page to the issue at a key, creating the issue if needed. Private.
- `scan_tiff_directory(folder)`: groups the TIFF files in a real folder into issues. Used in manual mode.
- `read_text_lines(path)`: reads a text file as UTF-8 (with or without BOM), falling back to UTF-16. Windows `dir` listings are often UTF-16.
- `read_tiff_list_file(path)`: groups TIFF filenames from a listing into issues, returning `(issues_by_key, unrecognized_lines)`.
- `file_contains_tiff_filenames(path)`: true when at least half the non-blank lines contain a TIFF filename.
- `find_tiff_source_files(folder)`: tifflists in a folder. Name matches first. Then `.txt` or `.csv` files whose content is mostly TIFF filenames, excluding Town Lists, ingest outputs, and merge reports.

### `notes.py`

- `get_notes_config_path()`: the repository root, one level above the package.
- `load_notes()`: reads `notes_config.txt`, one `type: text` entry per line, and returns them joined with `^^`. Results are cached in the module-level `_notes_cache`, so the file is read once per run. Raises `FileNotFoundError` or `ValueError` on a missing or empty file. A line without a colon is skipped with a warning.

### `records.py`

**Fields for one issue.**
- `build_origin_information(date_created, publisher)`: the 13-part `origin_information` string. `date_captured` is the date the script ran, from `datetime.now()`.
- `get_publisher(date_created)`: the publisher in force on a date.
- `build_persons(date_created)`: the era publisher with `relators:pbl`, followed by `PERSONS_STATIC_SUFFIX`.
- `build_subject_and_geo(towns)`: builds `subject` (`Newspaper -- Town, CT`) and `geographic_subject` (`Town (Conn.)`) from the town list. An empty list gives two empty strings.
- `compute_issue_record(key, issue, town_lists)`: builds the full record dict: `issue_id`, `date`, `year`, `volume`, `paper_no`, sorted `pages`, `title`, `subject`, `geographic_subject`, `persons`, `origin_information`. Title format: `Deep River New Era - Jan 2, 1885 - Vol. XI No. 39`. Raises `ValueError` if the date is not valid.

**Date correction.**
- `attempt_date_correction(key, issue, tiff_issues)`: for an issue with an invalid date, looks at paper numbers N-1 and N+1 in the same volume. Two patterns are tried, in order:
  1. **Weekly midpoint.** If the gap between the neighbors is even and at most `MAX_DATE_CORRECTION_GAP_DAYS`, the midpoint is the date.
  2. **Transposed month and day.** If swapping the digits gives a valid date strictly between the neighbors, that date is used.
  Returns `(date_iso, method)` or `(None, None)`.

**Joining one source.**
- `records_from_single_source(tiff_issues, town_lists, unrecognized_items, source_label, problem_prefix, town_dates, already_ingested_keys)`: joins one TIFF pool and one Town List pool. Returns `(records, problems, pending_tiff_keys, pending_town_keys, corrections)`.
  - A Town-List-only key becomes `missing_tiffs`, unless it is already ingested.
  - Unrecognized items become `unrecognized_filename`.
  - A TIFF issue whose date fails becomes a correction if possible, otherwise `invalid_date`.
  - A TIFF-only issue becomes `missing_town_list`.
  - Only issues with both sides become records.

**Gathering all inputs.**
- `gather_all_records(waiting_dir, already_ingested_keys)`: reads every tifflist and every Town List in the folder into one pool. Duplicate keys keep the first entry and add a `duplicate_*` problem. Read errors add `file_read_error` and mark the file as contributing nothing. Returns an 8-tuple: `(records, problems, tiff_filenames, townlist_filenames, file_usable_counts, file_pending, year_to_filenames, corrections)`.

### `problems.py`

Problem strings are the link between the pipeline and its reports. Each starts with a `[category]` tag, and most include an 8-digit date so they can be attached to a year.

- `PROBLEM_CATEGORY_LABELS`: readable names for the email.
- `PROBLEM_CATEGORY_VERBATIM` (`file_read_error`, `unrecognized_filename`): listed under "Needs a look" in the email instead of being folded into a count. Up to `VERBATIM_FULL_LIMIT` (3) of a kind are printed in full. More are summarized (see `summarize_verbatim_problems`).
- `VERBATIM_FULL_LIMIT` (3), `EMAIL_SECTION_LINE_LIMIT` (10), `INVALID_DATE_LIST_LIMIT` (3): the limits that keep the email short. Change them here.
- `PROBLEM_CATEGORIES_NEVER_BLOCK` (`missing_tiffs`, `unrecognized_filename`): these never hold a year back. A Town List waiting for its TIFFs is a normal state, not an error.
- `extract_year_from_problem(text)`: the year from the first plausible date in a message, or `None`.
- `problem_category(text)`: the leading tag, or `"other"`.
- `normalize_problem_for_compare(text)`: the form of a message used to tell whether it is the same problem as last run's. It removes the "found in N tifflist file(s)" part of `missing tiffs` messages (`SOURCE_LABEL_IN_PROBLEM_PATTERN`), which changes whenever a tifflist moves out of `DataWaiting/`. Both this run's and last run's problems go through it before they are compared.
- `group_problems(problems)`: returns `(by_year_category, invalid_dates_by_year, aggregate_by_category, verbatim_counts)`.
- `format_date_list(dates, limit)`: `'19110231', '19110230'` for a few dates, or the first few plus `and N more`.
- `format_year_problem_line(year, category_counts, invalid_dates)`: one year's line, such as `  1911: 2 invalid date ('19110231', '19110230'); 1 missing town list`.
- `cap_lines(lines, limit, noun, pointer)`: shows the first `limit` lines and replaces the rest with `... and N more <noun>`. The `pointer` text (default ` (see the full report)`) is dropped where the full report does not list the items, as in the resolved section.
- `summarize_verbatim_problems(problems, full_limit)`: the "Needs a look" lines. Few problems are printed in full. For many `unrecognized_filename` problems it groups the skipped names by file extension, with a count and one example (and source file) each, notes names that are a listing file's own name, and notes how many files they came from. Other verbatim categories get a count and their first message.
- `format_problem_summary_lines(problems, verbatim_as_lines)`: summary lines for the resolved-problems section of the email. The per-year lines are capped.

Problem categories the code emits:

| Category | Meaning | Holds back its year? |
|---|---|---|
| `missing_tiffs` | Town List entry with no TIFF yet | No |
| `missing_town_list` | TIFF issue with no Town List entry yet | Yes |
| `invalid_date` | TIFF date not a real date and not correctable | Yes, if a year can be found |
| `unrecognized_filename` | Filename or line did not match the pattern | No |
| `duplicate_tiff_entry` | Same paper appeared in two tifflists | No (no year) |
| `duplicate_town_list_entry` | Same paper appeared in two Town Lists | No (no year) |
| `file_read_error` | A file could not be read | No |
| `unresolved_volume` | Plain paper numbers with no way to get a volume | No (no year) |

### `ingest_rows.py`

- `build_parent_row_dict(record)`: the 64-column dict for a Publication Issue row, without an ID. `local_identifier` is set to the issue ID, which is how later runs recognize the issue.
- `rows_from_issue_record(record, start_id)`: returns `(rows, next_id)`. The parent gets `start_id`. Each page row gets the next ID, `member_of` set to the parent, `model` `Page`, `weight` set to the page number, `digital_file` set, `media_use` `Original File`, and `digital_origin` `reformatted digital`.
- `chunk_records_by_line_limit(records, start_line_count, target_lines)`: splits an ordered list of records into chunks. A chunk ends when the next issue would exceed the target, or when the year jumps by more than `MAX_CONTIGUOUS_YEAR_GAP`. An issue's rows are never split. `start_line_count` is the number of lines already used in the first chunk's file, counting the header.
- `normalize_for_compare(row)`: a comparable copy of a parent row. Drops `ID` and `member_of`, and blanks `date_captured` inside `origin_information`, because that value is always the run date.

### `ingest_files.py`

- `find_year_ingest_files(folder)`: every `<year>-ingest*.csv` in a year folder as a list of dicts with `filename`, `path`, `part_num`, and `rows`, sorted by part number.
- `is_year_marked_complete(year_dir)`: True if the folder holds a file named in `INGEST_COMPLETE_MARKER_NAMES` (any capitalization). The marker is made by a person; no code creates or deletes it, and `YEAR_COUNT_FILENAME_PATTERN` cleanup never matches it.
- `scan_existing_issue_keys(ingest_dir)`: the `(volume, paper_no)` key of every Publication Issue already in any year folder, read from `local_identifier`. Only year subfolders are read. Files sitting directly in `IngestFiles/` are not.
- `make_year_ingest_filename(folder, year, taken_names)`: `<year>-ingest.csv`, or `<year>-ingest_partN.csv` when that name is taken.
- `write_matching_xlsx(csv_path)`: rewrites `<same name>.xlsx` from the CSV. Uses `openpyxl`, imported only here.
- `_issue_entry(parent_row)`: `(date_iso, volume, paper_no)` for one Publication Issue row. The date is `date_created` from `origin_information`, which is the corrected date when a filename date was auto-corrected. `local_identifier` carries the raw filename date, so it is only a fallback for the date, and is the source of the volume and number.
- `_format_issue_line(date_iso, volume, paper_no, page_count)`: one line of the issue list, such as `1885-01-02  Vol. XI No. 39  4 pages`.
- `count_year_ingest_files(year_dir)`: returns a dict for the year's CSVs, or `None` if there are none. Keys: `issues`, `pages`, `lines`, `per_file` (a list of `(filename, lines)`), and `issue_list` (one `(date_iso, volume, paper_no, page_count)` per issue, sorted by date). Issues and pages are counted from the `model` column (`Publication Issue`, `Page`). A Page row is matched to its issue through `member_of`, within the same file, because IDs restart at 1 in each part file. Lines are counted as the number of newline characters in each file, header included, which matches `wc -l`.
- `write_year_count_file(year_dir, year)`: makes the folder's count file match the CSVs. The name is `<issues>issues<pages>pages<lines>lines.txt`. The body repeats the numbers in words, lists each CSV's line count, and then lists every issue, one per line. The file is rewritten whenever its content differs, so it is also refreshed when the list changes but the counts do not. It deletes any other file matching `YEAR_COUNT_FILENAME_PATTERN` first, so only one exists, and does not rewrite a file whose content is already right (its modified time stays the same, which matters to `run_from_drive.py`, which uploads by modified time). Returns the file name, or `None` for a folder with no CSVs.
- `refresh_year_count_files(ingest_dir)`: runs `write_year_count_file` for every four-digit folder under `ingest_dir` and returns `{year: filename}`. Called at the end of `merge_and_write_records` after the `.xlsx` files are written, and from `run_by_year` on a run with no input files.

### `runlog.py`

- `logs_dir_path(root)`: returns `root/_Logs`, creating it if needed.
- `append_run_log(root, message)`: one timestamped line appended to `run_log.txt`.
- `read_last_problems(root)` / `write_last_problems(root, problems)`: the set of problem strings saved at the end of the previous run, in normalized form (see `normalize_problem_for_compare`). `write_last_problems` is called on every run.
- `read_last_corrections(root)` / `write_last_corrections(root, corrections)`: the auto-correction notes the previous run reported. `read_last_corrections` returns `None`, not an empty set, when the file does not exist, so the caller can tell "no corrections last time" from "a folder last run by an older version".
- `last_problems_file_exists(root)`: whether a previous run has saved its problem set at all.

### `folders.py`

- `ensure_subdir(root, name)`: creates and returns a subfolder.
- `move_processed_input_files(waiting_dir, completed_dir, filenames, file_usable_counts, file_pending, log_root)`: moves a file to `DataFilesCompleted/` only if it contributed at least one entry and is not in `file_pending`. If a file of the same name already exists there, the new one is saved as `<name>_dup2.<ext>`, `_dup3`, and so on. Each move is logged.

### `alerts.py`

- `build_alert_email(..., corrections=(), complete_year_notices=())`: returns `(subject, body)`. The body has the run time, folders, new issues per year with date ranges, problems by year, problems not tied to a year, "Needs a look" items (full or summarized), years held back, resolved problems (counts only), auto-corrected dates, and the report path. Every section that could be long is capped with the helpers in `problems.py`: per-year sections show 10 years, corrections show 5, and "Needs a look" is summarized past 3 items of a kind. The subject reflects the state, in this order of precedence: held-back years, then problems with nothing held back, then new data for a year marked complete, then corrections with all clear, then all clear. The notices get their own section, capped at 10 lines. (Held-back and problems subjects take precedence, so the section may appear under those subjects.)
- `send_error_email(subject, body)`: sends through `smtp.gmail.com` on port 465 with SSL. Reads the password from `EMAIL_APP_PASSWORD`. Never raises. A missing password or a failed send prints a warning and returns.

### `merge.py`

- `merge_and_write_records(log_root, ingest_dir, reports_dir, all_records, volume_problems, source_line, corrections)`: the main engine. Steps:
  1. **Hold-back set.** Every year that appears in a problem that is not in `PROBLEM_CATEGORIES_NEVER_BLOCK` and that can yield a year.
  2. **Per-year loop.** For each year in records or held-back years:
     - existing rows indexed by `local_identifier`
     - for each record, in date order:
       - if the issue exists and matches after normalization: counted as *matched*
       - if it exists and differs: listed as a *differing duplicate*, not overwritten
       - if the year is held back: counted in *held back*, not written
       - otherwise: *new*, queued for writing
  3. **Writing.** New records are chunked. The first chunk appends to the active (last) file if there is room, unless the year is marked complete (`is_year_marked_complete`), in which case `can_continue` is forced false so every chunk goes to a new `_partN` file, and a line is added to `complete_year_notices`. Remaining chunks go into new `_partN` files. IDs continue from the highest existing ID.
  4. **`.xlsx`.** Each written file gets a fresh `.xlsx`.
  5. **Report.** Written only when the run added issues, wrote new data for a year marked complete, found differing duplicates, changed the problem set, or made a correction not reported before. "Changed" is judged on normalized problem text, and a correction is "new" if its note is not in `_Logs/last_corrections.txt`. A folder with a saved problem list but no saved corrections (last run by an older version) treats its current corrections as already reported.
  6. **Problem set.** Saved every run.
  7. **Email.** Sent when the problem set changed, there is a new correction, or `complete_year_notices` is non-empty. The notices are one-time events and are not saved in `last_problems.txt`, since after the new part file is written the issues are present and the notice does not repeat. Only the new corrections are listed in it.
  8. **Run log and console summary.**

  Returns the set of held-back years. The caller uses it to keep their source files in `DataWaiting/`.

  Note on the active file: its row count includes the header, so the test is `1 + rows < TARGET_LINES_PER_FILE`.

### `cli.py`

- `run_by_year(directory)`: default mode. Creates the four folders, scans for existing issues, gathers inputs, merges, and moves completed files. Holds back the sources of held-back years.
- `run_manual(tiff_source, townlist_file)`: single-pair mode. If the TIFF source is a folder, output goes into that folder. If it is a listing file, output goes into the listing's folder. Years, reports, and logs are created directly inside that output folder. Files are not moved.
- `main(argv)`: checks `notes_config.txt` first. Then chooses between default mode (one folder argument, or `--by-year <folder>`) and manual mode (two arguments). Prints usage and exits with status 1 otherwise. In manual mode, a local Town List that does not exist exits with status 1. Google Sheets URLs are not checked on disk.

### `build_issue_csv.py`

Imports `main` from `newspaper_ingest.cli` and calls it under `if __name__ == "__main__"`. `run_from_drive.py` runs this file by name, so it must stay in the repository root.

## Rules for changing the code

1. **Keep the column order.** `COLUMNS` must match the repository's expected order exactly.
2. **Keep problem text stable.** The alert email and the resolved-problems count compare problem strings from one run to the next. Changing the wording of a message makes every existing problem look resolved and new on the next run. If you must change wording, expect one alert email. Anything in a message that can change without the problem changing (a count of files searched, a timestamp) must be stripped in `normalize_problem_for_compare`, or it will cause repeat emails. The `missing tiffs` message's "found in N tifflist file(s)" is the existing example.
3. **Keep the `[category]` tag first** in every problem message. The grouping depends on it.
4. **Keep the hold-back categories in sync.** A new category that should not hold back a year must be added to `PROBLEM_CATEGORIES_NEVER_BLOCK`. A new category that should hold back a year needs an 8-digit date in its message if it is to be attached to a year.
5. **Do not overwrite existing issues.** Differing duplicates are reported, never replaced. This is the rule that protects earlier data.
6. **Date-only comparison in `normalize_for_compare`.** Any new field that changes every run (a timestamp, for example) must be blanked there too, or every issue will be reported as differing.
7. **Respect the layers.** A new function that needs something from a higher layer probably belongs in that higher layer.
8. **Test with real data.** The sample test used during the refactor covers the basic path only. Changes to parsing, date correction, the hold-back rule, or chunking should be tested against copies of real DataWaiting and IngestFiles folders, with the output diffed.

## Known limits

- **Impossible months are not year-attached.** A date like `19111331` fails the month check in `PROBLEM_YEAR_PATTERN`, so its `invalid_date` problem carries no year and does not hold back its year. The issue's files still stay in `DataWaiting/`.
- **Legacy range-named files are not scanned.** `scan_existing_issue_keys` reads only year subfolders. Files such as `1885-1886-ingest.csv` directly under `IngestFiles/` are not used to recognize existing issues.
- **Differing duplicates do not hold files.** A file whose only effect is a differing duplicate is moved to `DataFilesCompleted/`, and the report and email are the only record of the difference.
- **Date correction assumes the neighbors are right.** A correction is only as good as the surrounding issues' dates.
- **Town names are not standardized.** Subject and geographic values are used exactly as typed in the Town List.
- **`date_captured` uses the machine's local time**, not Eastern time, because it comes from `datetime.now()`. The GitHub runners run in UTC, so the value is the UTC date on those machines.
- **`ingest_complete` is checked only in the merge loop.** A marked year is protected from being modified by `merge_and_write_records`. Nothing else writes year files, but a manual-mode run writes into its own folder with the same rule.
