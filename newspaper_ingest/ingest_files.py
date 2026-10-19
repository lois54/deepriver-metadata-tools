"""
Reading and writing the per-year ingest CSVs in IngestFiles/<year>/.
"""

import csv
import os

from .config import INGEST_COMPLETE_MARKER_NAMES
from .patterns import YEAR_COUNT_FILENAME_PATTERN, YEAR_INGEST_FILENAME_PATTERN
from .timeutil import parse_iso_date_or_none
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


def is_year_marked_complete(year_dir):
    """
    True if the year folder holds an 'ingest_complete' marker file (also
    accepted: 'ingest_complete.txt'; capitals don't matter). The marker is
    created by a person, never by the pipeline, and the pipeline never
    deletes it. Its contents don't matter.
    """
    if not os.path.isdir(year_dir):
        return False
    names = {n.lower() for n in INGEST_COMPLETE_MARKER_NAMES}
    return any(f.lower() in names for f in os.listdir(year_dir))


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

def _issue_entry(parent_row):
    """
    (date_iso, volume, paper_no) for one Publication Issue row.

    The date is the one actually ingested: date_created inside
    origin_information, which is the CORRECTED date when a typo in a filename
    was auto-corrected. (The date inside local_identifier is the raw filename
    date, typo and all, so it is only a fallback.) The volume and paper
    number come from local_identifier.
    """
    local_id = (parent_row.get("local_identifier") or "").strip()
    parsed = parse_issue_prefix(local_id)
    volume, paper_no = (parsed[1], parsed[2]) if parsed else (None, None)

    origin_parts = (parent_row.get("origin_information") or "").split("|")
    date_iso = None
    if len(origin_parts) == 13 and parse_iso_date_or_none(origin_parts[2]):
        date_iso = origin_parts[2]
    if date_iso is None and parsed:
        date_iso = parsed[0]

    return date_iso or local_id or "(unknown date)", volume, paper_no


def _format_issue_line(date_iso, volume, paper_no, page_count):
    """'1885-01-02  Vol. XI No. 39  4 pages' - one issue, as listed in the count file."""
    if volume and paper_no is not None:
        label = f"Vol. {volume} No. {paper_no:02d}"
    else:
        label = "(volume/number unknown)"
    noun = "page" if page_count == 1 else "pages"
    return f"{date_iso}  {label}  {page_count} {noun}"


def count_year_ingest_files(year_dir):
    """
    Totals and the issue list for every '<year>-ingest*.csv' in one year
    folder, or None if the folder has no ingest CSVs. Returns a dict:

      issues     - rows whose model is 'Publication Issue'
      pages      - rows whose model is 'Page'
      lines      - physical lines in the CSV files, header lines included, the
                   same number `wc -l` reports (summed across part files)
      per_file   - list of (filename, lines)
      issue_list - one (date_iso, volume, paper_no, page_count) per issue,
                   sorted by date. Page rows are matched to their issue
                   within the same file, since IDs restart in each part file.
    """
    file_infos = find_year_ingest_files(year_dir)
    if not file_infos:
        return None

    issues = pages = lines = 0
    per_file = []
    issue_list = []
    for info in file_infos:
        parents = []                # (ID, entry) for each issue in this file
        pages_by_parent = {}        # ID -> number of Page rows pointing at it
        for row in info["rows"]:
            model = row.get("model")
            if model == "Publication Issue":
                issues += 1
                parents.append((row.get("ID"), _issue_entry(row)))
            elif model == "Page":
                pages += 1
                parent_id = row.get("member_of")
                pages_by_parent[parent_id] = pages_by_parent.get(parent_id, 0) + 1
        for parent_id, (date_iso, volume, paper_no) in parents:
            issue_list.append((date_iso, volume, paper_no, pages_by_parent.get(parent_id, 0)))

        with open(info["path"], "r", newline="", encoding="utf-8") as f:
            file_lines = f.read().count("\n")
        lines += file_lines
        per_file.append((info["filename"], file_lines))

    issue_list.sort(key=lambda e: (e[0], e[2] if e[2] is not None else 0))
    return {
        "issues": issues,
        "pages": pages,
        "lines": lines,
        "per_file": per_file,
        "issue_list": issue_list,
    }


def write_year_count_file(year_dir, year):
    """
    Make the year folder's count marker file match the CSVs now on disk.

    The file is named '<issues>issues<pages>pages<lines>lines.txt'. Inside
    are the same numbers in words, the line count of each CSV, and then every
    issue in the year, one per line, by date (with volume, number, and page
    count), so a person can see exactly what has been done and spot what is
    missing. Any older marker with a different name is removed, so exactly
    one is ever left. If the folder already has the right marker with the
    right contents, nothing is touched. A folder with no ingest CSVs gets no
    marker (and loses a stale one).

    Returns the marker's filename, or None if there is no marker.
    """
    counts = count_year_ingest_files(year_dir)
    existing = [f for f in os.listdir(year_dir) if YEAR_COUNT_FILENAME_PATTERN.match(f)]

    if counts is None:
        for old in existing:
            os.remove(os.path.join(year_dir, old))
        return None

    issues, pages, lines = counts["issues"], counts["pages"], counts["lines"]
    marker_name = f"{issues}issues{pages}pages{lines}lines.txt"
    text_lines = [
        f"{year}: {issues} issues, {pages} pages, {lines} lines "
        f"(header lines included, as wc -l counts them)",
        "",
        "Files:",
    ]
    text_lines += [f"  {name}: {n} lines" for name, n in counts["per_file"]]
    text_lines += ["", f"Issues ({issues}), one per line:"]
    text_lines += [_format_issue_line(*entry) for entry in counts["issue_list"]]
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
