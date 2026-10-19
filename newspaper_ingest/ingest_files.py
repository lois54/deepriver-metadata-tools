"""
Reading and writing the per-year ingest CSVs in IngestFiles/<year>/.
"""

import csv
import os

from .patterns import YEAR_COUNT_FILENAME_PATTERN, YEAR_INGEST_FILENAME_PATTERN
from .volumes import parse_issue_prefix


def find_year_ingest_files(directory):
    """
    Every '<year>-ingest.csv' (and '_partN') file in one IngestFiles/<year>/
    folder, as a list of dicts (filename, path, part_num, rows), sorted so the
    most recent part comes last.
    """
    files = []
    for filename in os.listdir(directory):
        match = YEAR_INGEST_FILENAME_PATTERN.match(filename)
        if not match:
            continue
        part_text = match.group(2)
        path = os.path.join(directory, filename)
        with open(path, "r", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        files.append({
            "filename": filename,
            "path": path,
            "part_num": int(part_text) if part_text else 1,
            "rows": rows,
        })

    files.sort(key=lambda info: info["part_num"])
    return files


def scan_existing_issue_keys(ingest_dir):
    """
    The (volume, paper_no) key of every issue already written to any year
    folder under ingest_dir, read back from each parent row's local_identifier.

    Lets a run recognize a Town List entry that was already ingested in an
    earlier run, even after its tifflist has moved out of DataWaiting.
    """
    keys = set()
    if not os.path.isdir(ingest_dir):
        return keys

    for year in os.listdir(ingest_dir):
        year_dir = os.path.join(ingest_dir, year)
        if not os.path.isdir(year_dir):
            continue
        for file_info in find_year_ingest_files(year_dir):
            for row in file_info["rows"]:
                if row.get("model") != "Publication Issue":
                    continue
                issue_id = (row.get("local_identifier") or "").strip()
                if not issue_id:
                    continue
                parsed = parse_issue_prefix(issue_id)
                if parsed:
                    _, volume, paper_no = parsed
                    keys.add((volume, paper_no))

    return keys


def make_year_ingest_filename(directory, year, taken_names):
    """'<year>-ingest.csv', or '<year>-ingest_partN.csv' if that name is taken."""
    candidate = f"{year}-ingest.csv"
    part_num = 2
    while candidate in taken_names or os.path.exists(os.path.join(directory, candidate)):
        candidate = f"{year}-ingest_part{part_num}.csv"
        part_num += 1
    return candidate


def write_matching_xlsx(csv_path):
    """
    Write an .xlsx copy of an ingest CSV, for anyone who prefers Excel. The
    CSV stays the file of record; the .xlsx is regenerated from it each time
    and is never read back.
    """
    import openpyxl  # imported here so the CSV-only path doesn't need it

    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)

    xlsx_path = os.path.splitext(csv_path)[0] + ".xlsx"
    workbook.save(xlsx_path)


# =============================================================================
# THE COUNT MARKER FILE IN EACH YEAR FOLDER
# A small text file whose NAME carries the totals for the year's ingest CSVs,
# e.g. "48issues432pages481lines.txt", so the counts show up in a folder
# listing without opening anything. The totals are always recounted from the
# CSV files on disk, so they cannot drift from what the files really hold.
# =============================================================================

def count_year_ingest_files(year_dir):
    """
    Totals across every '<year>-ingest*.csv' in one year folder:
    (issues, pages, lines, per_file), where per_file is a list of
    (filename, lines). Returns None if the folder has no ingest CSVs.

    - issues - rows whose model is 'Publication Issue'
    - pages  - rows whose model is 'Page'
    - lines  - physical lines in the CSV files, header lines included, the
               same number `wc -l` reports (summed across part files)
    """
    file_infos = find_year_ingest_files(year_dir)
    if not file_infos:
        return None

    issues = pages = lines = 0
    per_file = []
    for info in file_infos:
        for row in info["rows"]:
            model = row.get("model")
            if model == "Publication Issue":
                issues += 1
            elif model == "Page":
                pages += 1
        with open(info["path"], "r", newline="", encoding="utf-8") as f:
            file_lines = f.read().count("\n")
        lines += file_lines
        per_file.append((info["filename"], file_lines))

    return issues, pages, lines, per_file


def write_year_count_file(year_dir, year):
    """
    Make the year folder's count marker file match the CSVs now on disk.

    The file is named '<issues>issues<pages>pages<lines>lines.txt' and holds
    the same numbers in words, plus the line count of each CSV. Any older
    marker with a different name is removed, so exactly one is ever left. If
    the folder already has the right marker, nothing is touched. A folder
    with no ingest CSVs gets no marker (and loses a stale one).

    Returns the marker's filename, or None if there is no marker.
    """
    counts = count_year_ingest_files(year_dir)
    existing = [f for f in os.listdir(year_dir) if YEAR_COUNT_FILENAME_PATTERN.match(f)]

    if counts is None:
        for old in existing:
            os.remove(os.path.join(year_dir, old))
        return None

    issues, pages, lines, per_file = counts
    marker_name = f"{issues}issues{pages}pages{lines}lines.txt"
    text_lines = [
        f"{year}: {issues} issues, {pages} pages, {lines} lines "
        f"(header lines included, as wc -l counts them)",
        "",
    ]
    text_lines += [f"{name}: {n} lines" for name, n in per_file]
    text = "\n".join(text_lines) + "\n"

    marker_path = os.path.join(year_dir, marker_name)
    for old in existing:
        if old != marker_name:
            os.remove(os.path.join(year_dir, old))

    unchanged = False
    if os.path.isfile(marker_path):
        with open(marker_path, "r", encoding="utf-8") as f:
            unchanged = f.read() == text
    if not unchanged:
        with open(marker_path, "w", encoding="utf-8") as f:
            f.write(text)

    return marker_name


def refresh_year_count_files(ingest_dir):
    """
    Bring the count marker in every four-digit year folder under ingest_dir up
    to date. Returns {year: marker_filename} for the folders that have one.
    Folders whose names are not four digits are left alone.
    """
    markers = {}
    if not os.path.isdir(ingest_dir):
        return markers

    for name in sorted(os.listdir(ingest_dir)):
        year_dir = os.path.join(ingest_dir, name)
        if not (len(name) == 4 and name.isdigit() and os.path.isdir(year_dir)):
            continue
        marker = write_year_count_file(year_dir, name)
        if marker:
            markers[name] = marker

    return markers
