# What the pipeline does, situation by situation

This document describes what happens when the pipeline runs in each situation it handles. It is written for the people who prepare the input files and check the output, not for programmers. For the code, see `docs/CODE.md`.

## The short version

- Every run reads **everything** in `DataWaiting/` and works out the full picture from scratch.
- An issue is written only when it has **both** its page list (tifflist) and its towns (Town List).
- Issues already in the year files are **recognized and left alone**. Running the pipeline twice does not write anything twice.
- If a year has a problem that might be a missing piece, the **whole year is held back** for that run. Its new issues are not written, and the files that feed it stay in `DataWaiting/`. Nothing is lost; the next run retries.
- Problems that are only waiting for something to arrive (a Town List with no TIFFs yet, for example) do **not** hold a year back.
- Input files move to `DataFilesCompleted/` only when everything in them has been used.
- The alert email is sent **only when the set of problems changes**, so you are not emailed the same thing every run.

## Situations at a glance

| # | Situation | Written? | Year held back? | Files move? | Email? |
|---|---|---|---|---|---|
| 1 | Normal run, everything matches | Yes | No | Yes | If problems changed |
| 2 | Re-run with nothing new | No | No | No | No |
| 3 | Town List has towns for an issue, no TIFFs yet | No (for that issue) | No | Town List stays | Yes, first time |
| 4 | TIFFs for an issue, no Town List entry yet | No | **Yes** | TIFF file stays | Yes, first time |
| 5 | Both kinds of gap in the same year | No | Yes | Feeding files stay | Yes |
| 6 | One year held back, others fine | Other years yes | Only that year | Unrelated files move | Yes |
| 7 | Invalid TIFF date, correctable | Yes | No | Yes | Yes (correction listed) |
| 8 | Invalid TIFF date, not correctable | No | Yes (if year found) | TIFF file stays | Yes |
| 9 | Unrecognized filename or line | Rest of file yes | No | Yes, unless something else pends | Yes, first time |
| 10 | A file cannot be read | Other files yes | No | That file stays | Yes |
| 11 | Same issue listed twice | First one used | No | Yes | Yes, first time |
| 12 | Issue already in year files, same data | No (matched) | No | Yes | No |
| 13 | Issue already in year files, different data | No (not overwritten) | No | Yes | No, report only |
| 14 | Plain paper numbers with no volume | No | No | Yes, unless something else pends | Yes, first time |
| 15 | Town List in one of three layouts | Yes | Per problems | Per problems | Per problems |
| 16 | Google Sheets Town List (manual mode) | Yes | Per problems | n/a | Per problems |
| 17 | Year file grows past the size limit | Yes, into a new part file | No | Yes | No |
| 18 | Year gap of more than one year | Yes, new file | No | Yes | No |
| 19 | Input file name already in DataFilesCompleted | Yes, renamed | No | Yes | No |
| 20 | Notes file missing | Nothing runs | n/a | No | No |
| 21 | Email password missing or sending fails | Yes | No | Yes | Skipped, warning printed |
| 22 | No input files at all | Nothing | n/a | No | No |
| 23 | Manual mode | Yes | Per problems | No | Per problems |

---

## 1. Normal run: everything matches

**Input.** A tifflist with pages for issues 39 and 40 of Volume XI, and a Town List that gives towns for the same two issues.

**What happens.**
- Both issues are complete, so both are written.
- Each issue gets one Publication Issue row and one Page row per TIFF page.
- The rows go into `IngestFiles/1885/1885-ingest.csv`, with a matching `.xlsx`.
- The tifflist and Town List both have nothing pending, so both move to `DataFilesCompleted/`.
- A merge report is written, because issues were added.
- The run log gets a line such as `new=2 matched=0 differing=0 problems=0 held_back_years=0 -> Ingest_merge_report_....txt`.
- The email is sent only if the set of problems changed. If there are no problems at all, there is no email, unless a date was auto-corrected.

## 2. Re-running with nothing new

**Input.** The same files as situation 1, run again, or a run with an empty `DataWaiting/`.

**What happens.**
- If the files are still there (they were not moved, for example because something else was pending), the issues are found in the year file and counted as **already present**. Nothing is written.
- If `DataWaiting/` is empty, the run says so and writes one line to the run log.
- No merge report is written, because nothing changed.
- No email is sent, because the problem set is the same as last time.

This is why running the pipeline twice is safe.

## 3. A Town List has towns for an issue, but no TIFFs yet

**Input.** A Town List lists towns for Volume XI issue 41, but no tifflist has issue 41 yet.

**What happens.**
- Issue 41 is **not written**.
- A `missing tiffs` problem is recorded. It does **not** hold back the year.
- Other issues in the same Town List that do have TIFFs are written normally.
- The Town List file **stays in `DataWaiting/`**, because one of its rows is still waiting. This includes the rows that were written, which will show as "already present" next time.
- When the tifflist for issue 41 arrives, the next run writes issue 41 and the Town List moves to `DataFilesCompleted/`.
- The email is sent the first time this problem appears, and again only when the set of problems changes.

## 4. TIFFs for an issue, but no Town List entry yet

**Input.** A tifflist has pages for Volume XI issue 42, but no Town List has issue 42.

**What happens.**
- Issue 42 is **not written**.
- A `missing town list` problem is recorded, and it **holds back the whole year**, 1885 in this example.
- Every other new issue from 1885 is also held back. Its rows are not written this run, even if they are complete.
- The tifflist **stays in `DataWaiting/`**.
- Issues from other years that are complete are written normally.
- When the Town List entry for issue 42 arrives, the year is released and all held-back issues are written together.

Holding the year back keeps each year's file in a complete, consistent state. It is safer than writing around a gap.

## 5. Both kinds of gap in the same year

**Input.** Volume XI issue 41 has TIFFs but no towns, and issue 43 has towns but no TIFFs. Issue 40 is complete.

**What happens.**
- Issue 40 is held back, because the year is held back. Its rows are not written.
- Issue 41 is not written, because it has no towns.
- Issue 43 is not written, because it has no TIFFs. It is a `missing tiffs` problem and does not hold the year on its own.
- All files that feed issue 40 and 41 stay in `DataWaiting/`.
- Once both gaps are filled, the year is released and all three issues are written in one run.

## 6. One year held back, others fine

**Input.** Issues from 1885 have a missing Town List entry (situation 4). Issues from 1903 are complete.

**What happens.**
- 1885 is held back, with its source files kept in `DataWaiting/`.
- 1903 is written normally.
- The files that only feed 1903 move to `DataFilesCompleted/`.
- The merge report lists 1885 under **Years held back this run**, with the number of waiting issues.
- The alert email's subject reads `Newspaper pipeline: 1 year held back`, and the body lists the year.

A held-back year never blocks other years.

## 7. Invalid TIFF date, and it can be corrected

**Input.** A TIFF is named `18850231_vXI_n41_0001.tif`. February 31 does not exist, so the date is invalid. Issue 40 is dated 1885-01-26 and issue 42 is dated 1885-02-09.

**What happens.** The pipeline tries two patterns, in order:
1. **Weekly midpoint.** The gap between the neighbors is 14 days, which is even. The midpoint is 1885-02-02. That is the date used.
2. **Transposed month and day.** If the midpoint pattern does not apply, swapping the month and day digits is tried. The result must be a real date strictly between the neighbors.

**What you will see.**
- The issue is written with the corrected date. Its title, year, and file name use the corrected date.
- The correction is listed in the merge report under **DATES AUTO-CORRECTED THIS RUN**.
- The alert email has an **Auto-corrected date** section, and its subject reads `all clear (1 date auto-corrected)` if nothing else is wrong.

**Check it.** A correction is only as good as the neighboring issues. Look at the corrected date against the scan before the file goes to the repository.

## 8. Invalid TIFF date, and it cannot be corrected

**Input.** A TIFF is named `19110231_vXI_n41_0001.tif` and neither neighbor pattern produces a valid date.

**What happens.**
- The issue is **not written**.
- An `invalid date` problem is recorded, showing the bad value, for example `'19110231'`.
- The year (1911) is **held back**, so the other 1911 issues wait too.
- The TIFF file stays in `DataWaiting/`.
- The alert email lists `invalid date ('19110231')` under 1911.

**To fix it.** Correct the date in the TIFF filename or the tifflist line. The next run picks it up.

**Known gap.** A date with an impossible month, such as `19111331`, is reported and the file stays in `DataWaiting/`, but the year is not held back. See the **Known limits** section at the end.

## 9. Unrecognized filename or line

**Input.** The tifflist has a line `scan_notes.jpg`, or a TIFF named `Vol_XI_extra.tif` that does not follow the pattern.

**What happens.**
- That line is skipped and reported as `unrecognized filename`.
- Every other line in the file is processed normally.
- This does **not** hold back any year.
- The file is still moved to `DataFilesCompleted/` if everything else in it was used. The merge report is the only place every skipped line is recorded, in full.
- The email lists them under **Needs a look** the first time they appear. Up to 3 skipped names are printed in full. More than 3 are summarized: a total, then one line per file type with its count and one example. For example:

  ```
  Needs a look:
    58 skipped names did not match the expected pattern, by type:
      .pdf: 52  (for example '19240229_vLI_n01.pdf' in 1924tifflist.txt)
      .txt: 6  (for example '1924tifflist.txt' in 1924tifflist.txt)  - each is the listing file's own name
      spread across 6 files
  ```

  A listing made by dumping a folder often includes its own filename. Those show up as a `.txt` line marked as the listing file's own name, and they are harmless.

## 10. A file cannot be read

**Input.** A Town List that is corrupt, locked by Excel, or in an unexpected encoding.

**What happens.**
- The file is skipped entirely and reported as `file_read_error`, with the error message.
- The file **stays in `DataWaiting/`**, because it contributed nothing.
- Other files are processed normally.
- This does not hold back a year.
- The email lists it under **Needs a look**. Up to 3 unreadable files are printed in full. More than 3 are summarized as a count with the first one as an example.

**Tip.** If a Town List is open in Excel, close it. Some systems lock open files.

## 11. The same issue listed twice

**Input.** Two tifflists both have Volume XI paper 39, or two Town Lists both have it.

**What happens.**
- The first one read is used. The second is ignored.
- A `duplicate tiff entry` or `duplicate town list entry` problem is recorded, naming the paper and the file.
- Duplicates have no date in the message, so they do not hold back a year.
- Both files can still move, if nothing else is pending.
- The email reports the duplicate once, and again only if the problem set changes.

Which file is "first" depends on the order of filenames in `DataWaiting/`, so check that the copy you want is the one used.

## 12. An issue already in the year files, same data

**Input.** Issue 39 was written on an earlier run, and the same tifflist is still in `DataWaiting/` (for example, because another issue in it was pending).

**What happens.**
- The issue is found by its `local_identifier` and compared with the stored row.
- The parent row is the same, so it is counted as **already present**.
- Nothing is written, and the page rows are not compared.
- The count appears in the report under **Already present (unchanged)**.

## 13. An issue already in the year files, different data

**Input.** Issue 39 is in the year file, but the Town List now gives different towns for it, or the title would change.

**What happens.**
- The existing row is **not overwritten**.
- The issue is listed under **DUPLICATES WITH DIFFERING DATA** in the report, with the message "NOT overwritten - please review manually".
- The difference is not a problem in the email sense, so it does not by itself send an email. The merge report is written, because it is a noteworthy event.
- The source files still move, because the differing issue does not hold them.

**To fix it.** Decide which data is right. If the existing row is wrong, remove it from the year CSV, then re-run. The issue will be written from the current input. Take a copy of the CSV first.

## 14. Plain paper numbers with no volume

**Input.** A Town List uses plain paper numbers (No. 39, No. 40) with no volume label, and no TIFF data shows a single volume that could apply.

**What happens.**
- The rows cannot be matched to a volume, so they are skipped.
- An `unresolved volume` problem is recorded, saying how many rows were skipped.
- It does not hold back a year.
- Volume is taken first from the Town List filename (such as `Vol_XI_Town_List.xlsx`). If the filename has no volume, and every TIFF issue is in one volume, that volume is used.

**To fix it.** Put the volume in the Town List filename, or use a layout with a filename column.

## 15. The three Town List layouts

The layout is detected from the header row. The filename and paper-number handling differs by layout.

**Format A (one row per issue).** The header has `No.` or `Paper No.`, and a column with `File` in its name holds the TIFF filename. Towns are every non-blank cell after the number. A filename column placed before the number supplies the volume. If there is no `No.` column, the paper number comes from the filename.

**Format B (transposed).** The top row holds paper numbers, and towns are stacked down each column. These rows have no volume, so the volume is resolved afterward, as in situation 14.

**Format C ("Slim").** The header has `Subject` and `Geographic`. The first column holds the TIFF filename. Towns are read back out of the Subject cell (`Newspaper -- Town, CT`), not from the Geographic column, so a hand-edit to Geographic does not change the output.

A Town List with an issue that has no towns still produces a record. The issue is written with empty subject and geographic fields. Check for these; they are usually a blank row by mistake.

## 16. Google Sheets as a Town List

**Input (manual mode only).** A sheet's link is given instead of a file.

**What happens.**
- The sheet is downloaded as CSV and read in the same way as a CSV file.
- If the sheet is not shared as "Anyone with the link can view", the run stops with a message explaining how to change it.
- If there is no internet connection, the run stops with a connection message.

In the default folder mode, Google Sheets are not used. Save the sheet as `.xlsx` or `.csv` in `DataWaiting/`.

## 17. A year file grows past the size limit

**What happens.**
- A year's file grows until the next issue would take it past 800 lines, counting the header.
- A new file is started: `1885-ingest_part2.csv`, then `_part3`, and so on.
- An issue's rows are never split across files. The whole issue goes into the next part.
- Each part gets its own `.xlsx` copy.
- The next run continues in the last part, if it has room.

The 800-line target is well under the repository's 1000-line limit.

## 18. A gap of more than one year between issues

**What happens.** When the next issue in a year is more than one year after the last, a new file starts, even if the current file has room. A gap of one year is treated as normal, for a volume that runs over New Year's.

This changes the file split only. Issues are still in date order.

## 19. An input file name already in DataFilesCompleted

**What happens.**
- A file that would overwrite one already in `DataFilesCompleted/` is saved under a new name: `Vol_XI_tifflist_dup2.txt`, then `_dup3`, and so on.
- The move is logged in the run log.

Nothing is ever overwritten in `DataFilesCompleted/`.

## 20. The notes file is missing

**What happens.**
- The script checks for `notes_config.txt` before doing anything else.
- If it is missing, or has no valid lines, the run stops with a message showing the expected format.
- Nothing is read, written, moved, or emailed.

Put `notes_config.txt` in the repository root, next to `build_issue_csv.py`.

## 21. The email password is missing, or sending fails

**What happens.**
- If `EMAIL_APP_PASSWORD` is not set, the console says `(EMAIL_APP_PASSWORD not set - skipping alert email)`. The run continues normally.
- If sending fails (no internet, wrong password, Gmail rejects the login), the console shows `WARNING: couldn't send alert email`. The run continues normally.
- The problem set is saved either way, so a failed email is not re-sent by the next run. **The email is lost** in that case. The merge report still has the full detail.

## 22. No input files at all

**What happens.**
- The console says `No tifflist or Town List files found.`
- The count file in each year folder is brought up to date (see **Output files**).
- One line is written to the run log.
- No issues are written, no files are moved, and no email is sent.

## 23. Manual mode

**Input.** Two arguments: a TIFF folder or listing file, and a Town List file or Google Sheets link. Used for one-off files outside the folder layout.

**What happens.**
- Output goes **into the folder that holds the TIFF source**. If the TIFF source is a folder, that folder is used. If it is a listing file, its folder is used.
- Year folders, the merge report, and `_Logs/` are created directly in that folder. There is no `DataWaiting/`, `IngestFiles/`, or `MergeReports/` layer.
- Input files are **not moved**.
- The same hold-back, correction, and duplicate rules apply.
- The same email rules apply, but against the output folder's own `_Logs/` state, not the root folder's.

Use the normal folder mode for regular work.

---

## Files that move, and files that stay

After a run, a file is in one of three places.

| Where | When |
|---|---|
| `DataFilesCompleted/` | It contributed at least one entry, and nothing in it is still pending. |
| `DataWaiting/` | It contributed nothing (read error), or it has an entry still waiting for a match or a date fix, or its year was held back and it feeds that year. |
| Nowhere new | It was already in `DataFilesCompleted/` and was not touched. |

A file that stays is re-read on the next run. Issues already written are recognized, so there is no double-counting.

## Output files

For every year that gets a new issue, the pipeline:

- appends to the last year file if there is room, or starts a new one
- writes a matching `.xlsx` copy of that file, regenerated in full

Then, for **every** year folder, it brings the **count file** up to date. This is a small text file whose name carries the year's totals, for example:

```
IngestFiles/1911/48issues432pages481lines.txt
```

- **issues** are the Publication Issue rows, **pages** are the Page rows, and **lines** are the physical lines in the year's CSV files, header lines included. This is the same number `wc -l` reports. When a year has several part files, the three numbers are the totals across all of them.
- The numbers are recounted from the CSV files on disk on every run, not carried over from earlier runs, so they always match what is really in the files.
- When the totals change, the old count file is deleted and a new one with the new name is created, so each year folder has exactly one. When nothing changed, the file is left alone.
- Inside the file is the same information in words, plus the line count of each CSV file, such as `1911-ingest.csv: 481 lines`.
- A year folder with no ingest CSVs gets no count file. Folders whose names are not four digits are ignored.
- The count files are also brought up to date on a run that finds nothing in `DataWaiting/`. That is how the files get created for years written before this feature existed.
- Counts of 1 still read `1issues` and `1pages`, so every file name has the same shape.

Issue rows appear in date order within a run. A Publication Issue row is followed by its Page rows, numbered from 1 to the number of pages.

The fields that come from the run are:

- **title**: `Deep River New Era - Jan 2, 1885 - Vol. XI No. 39`
- **persons**: the publisher in force on the issue's date, then the fixed credits
- **origin_information**: place, date created, date captured (the day the script ran), publisher, issuance, and frequency
- **subject** and **geographic_subject**: built from the Town List towns
- **notes**: the credits from `notes_config.txt`
- **local_identifier**: the issue ID, such as `18850102_vXI_n39`. This is how later runs recognize the issue.

The publisher is chosen by date. Sheldon up to 1885, Kirtland from 1885, Prann from 1903, Johnson from 1946. Where two publishers share 1903, Prann is used from 1 January 1903. This is an assumption; check it against the actual changeover if it matters for a specific issue.

## The merge report

Written only when the run added issues, found differing duplicates, changed the problem set, or auto-corrected a date. It lists, in this order:

1. Run time and folders
2. New issues, already present, and differing duplicates, with page counts
3. Breakdown by source file
4. Files written or updated
5. Years held back, with the number of waiting issues
6. Auto-corrected dates
7. Differing duplicates, in full
8. Other problems, in full

## The run log

`_Logs/run_log.txt` gets one line per run. Each line has a timestamp and a summary: how many issues were added, already present, differing, and how many problems and held-back years there were. It then names the report, or says `nothing new since last run, no report written`.

## The alert email

Sent when the problem set has changed since the previous run, or when a date was auto-corrected. Otherwise it is not sent.

**Subject**, in order of precedence:

1. `Newspaper pipeline: N year(s) held back`
2. `Newspaper pipeline: problems to review (nothing held back)`
3. `Newspaper pipeline: all clear (N date(s) auto-corrected)`
4. `Newspaper pipeline: all clear`

**Body.** Run time, folders read and written, new issues per year with the date range, problems by year, problems not tied to a year, items under **Needs a look**, held-back years, resolved problems since the last run (counts only), auto-corrected dates, and the report path.

**Keeping it short.** The email never lists a long run of lines. The full detail is always in the merge report named at the bottom.
- **Needs a look**: up to 3 items of a kind are printed in full. More than 3 are summarized. Skipped filenames are grouped by file type with a count and an example for each. Other kinds show a count and the first message as an example.
- **New issues added**, **Problems by year**, and **Resolved**: the first 10 years are shown, then one line such as `... and 4 more years (see the full report)`.
- **Invalid dates** in a year's line: the first 3 are shown, then `and N more`.
- **Auto-corrected dates**: the first 5 are shown, then `... and N more corrections (see the full report)`.
- The list of held-back years is a single line.

**"Resolved"** means a problem from the last run that is no longer present. A problem that goes away because its missing piece arrived shows here.

**Resetting the alert state.** Deleting `_Logs/last_problems.txt` makes the next run treat every current problem as new, so the email is sent again. Only do this on purpose.

---

## Known limits

These are the places where the pipeline behaves in a way you might not expect. They are listed here so nothing is a surprise.

1. **Impossible months do not hold back their year.** A date such as `19111331` fails the month check. The issue is reported and its files stay in `DataWaiting/`, but the year is not held back, so other issues from that year can be written.
2. **Differing duplicates do not hold files.** A file whose only effect is a differing duplicate moves to `DataFilesCompleted/`. The report and the email are the only record of the difference. Check the report after a run that lists differing duplicates.
3. **Legacy range-named files are not checked for existing issues.** Files named like `1885-1886-ingest.csv`, directly in `IngestFiles/`, are not read when the pipeline looks for issues it already wrote. Only year folders are read. If older range files still hold issues that could reappear in a tifflist, a duplicate can be written. Keep the year folders as the only place output is written.
4. **An email that fails to send is not retried.** The problem set is saved even when sending fails. The report still has the detail, but the email itself is not sent again.
5. **Which duplicate wins depends on file order.** The first file read keeps its entry. Check which copy you want.
6. **A Town List with a pending row stays whole.** Its other rows, already written, show as "already present" until the pending row is matched. This is by design, but it means the file can sit in `DataWaiting/` for a while.
7. **Date correction depends on the neighbors.** A corrected date is only as good as the issues on either side of it.
8. **The `date_captured` field is the run date on the machine.** On GitHub Actions, that is the UTC date, which can be one day ahead of the Eastern date late in the evening.
9. **Manual mode writes into the TIFF folder.** If that folder is your live root folder, manual output sits alongside the regular year folders and is recognized by later runs. Keep manual runs in a separate folder unless that is what you want.
