"""
Reading and writing the per-year ingest CSVs in IngestFiles/<year>/.
"""

import csv
import os

from .patterns import YEAR_INGEST_FILENAME_PATTERN
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
