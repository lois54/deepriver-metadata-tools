"""
TIFF input: parsing TIFF filenames, reading them from a folder or from a
listing file (plain paths or a Windows 'dir' listing), and finding the
tifflist files in DataWaiting.
"""

import os
from datetime import datetime

from .config import DIGITAL_FILE_BASE
from .patterns import (
    INGEST_FILENAME_PATTERN,
    TIFF_NAME_PATTERN,
    TIFF_NAME_SEARCH_PATTERN,
    TIFFLIST_FILENAME_PATTERN,
)
from .townlist import is_town_list_filename
from .volumes import normalize_volume


def build_digital_file(date_iso, filename):
    """
    build_digital_file('1885-01-16', '18850116_vXI_n41_0001.tif')
      -> '/opt/ingest_data/uploads/3/1885/18850116_vXI_n41_0001.tif'
    """
    year = date_iso[:4]
    return f"{DIGITAL_FILE_BASE}{year}/{filename}"


def parse_tiff_filename(filename):
    """
    Pull the pieces out of one TIFF filename. Returns
    (issue_id, date_iso, volume, paper_no, page_number), or None if the
    filename doesn't match TIFF_NAME_PATTERN.

    If the date is not a real calendar date, date_iso is the raw digits, so
    the caller can detect and handle it.
    """
    match = TIFF_NAME_PATTERN.match(filename)
    if not match:
        return None

    date_text, volume_raw, paper_no_text, page_text = match.groups()
    volume = normalize_volume(volume_raw)
    paper_no = int(paper_no_text)

    try:
        date_obj = datetime.strptime(date_text, "%Y%m%d")
        date_iso = date_obj.strftime("%Y-%m-%d")
    except ValueError:
        date_iso = date_text

    issue_id = f"{date_text}_v{volume}_n{paper_no_text}"

    # A filename with no page number is almost certainly single-page.
    page_number = int(page_text) if page_text else 1

    return issue_id, date_iso, volume, paper_no, page_number


def _add_page(issues_by_key, key, issue_id, date_iso, volume, filename, page_number):
    """Add one page to the issue at `key`, creating the issue if new."""
    if key not in issues_by_key:
        issues_by_key[key] = {
            "issue_id": issue_id,
            "date": date_iso,
            "volume": volume,
            "pages": [],
        }

    issues_by_key[key]["pages"].append({
        "filename": filename,
        "page_number": page_number,
        "digital_file": build_digital_file(date_iso, filename),
    })


def scan_tiff_directory(tiff_dir):
    """
    Scan a real folder of .tif/.tiff files and group the pages into issues.

    Returns (issues_by_key, unrecognized_files), where issues_by_key maps
    (volume, paper_no) -> {issue_id, date, volume, pages: [...]}.

    The key includes the volume because paper numbers reset every volume.
    """
    issues_by_key = {}
    unrecognized_files = []

    for filename in sorted(os.listdir(tiff_dir)):
        if not filename.lower().endswith((".tif", ".tiff")):
            continue

        parsed = parse_tiff_filename(filename)
        if parsed is None:
            unrecognized_files.append(filename)
            continue

        issue_id, date_iso, volume, paper_no, page_number = parsed
        _add_page(issues_by_key, (volume, paper_no), issue_id, date_iso,
                  volume, filename, page_number)

    return issues_by_key, unrecognized_files


def read_text_lines(path):
    """
    Read a text file's lines. Tries UTF-8 first (with or without a BOM), then
    UTF-16. PowerShell's Out-File writes UTF-16 by default, which is the
    usual reason a Windows 'dir' listing fails to decode as UTF-8.
    """
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return f.readlines()
    except UnicodeDecodeError:
        with open(path, "r", encoding="utf-16") as f:
            return f.readlines()


def read_tiff_list_file(list_file_path):
    """
    Read TIFF filenames from a listing file. Handles both:
        - one full path per line, and
        - a Windows 'dir' listing line (the date/size is ignored)

    For each line, the TIFF filename is searched for anywhere in the line.
    The digital_file path is always rebuilt from the issue's year, even if
    the line contained its own path.

    Returns (issues_by_key, unrecognized_lines), the same shape as
    scan_tiff_directory.
    """
    issues_by_key = {}
    unrecognized_lines = []

    for raw_line in read_text_lines(list_file_path):
        line = raw_line.strip()
        if not line:
            continue

        match = TIFF_NAME_SEARCH_PATTERN.search(line)
        if not match:
            unrecognized_lines.append(line)
            continue

        filename = match.group(1)

        parsed = parse_tiff_filename(filename)
        if parsed is None:
            unrecognized_lines.append(line)
            continue

        issue_id, date_iso, volume, paper_no, page_number = parsed
        _add_page(issues_by_key, (volume, paper_no), issue_id, date_iso,
                  volume, filename, page_number)

    return issues_by_key, unrecognized_lines


def file_contains_tiff_filenames(path):
    """
    Look at a file's content (not its name) and decide whether it's a
    tifflist: at least half its non-blank lines must contain a TIFF filename.
    The majority rule avoids misidentifying a file that just mentions one.
    """
    try:
        lines = [line for line in read_text_lines(path) if line.strip()]
    except (UnicodeDecodeError, OSError):
        return False

    if not lines:
        return False

    matching = sum(1 for line in lines if TIFF_NAME_SEARCH_PATTERN.search(line))
    return matching / len(lines) >= 0.5


def find_tiff_source_files(directory):
    """
    Every tifflist file in `directory`. Matched by name first
    (TIFFLIST_FILENAME_PATTERN), then by content for .txt/.csv files that
    don't follow the naming convention. Town List files and this script's
    own output files are never considered.
    """
    by_name = []
    maybe_by_content = []

    for f in sorted(os.listdir(directory)):
        if f.startswith("."):
            continue
        path = os.path.join(directory, f)
        if not os.path.isfile(path):
            continue
        if TIFFLIST_FILENAME_PATTERN.match(f):
            by_name.append(f)
        elif (
            f.lower().endswith((".txt", ".csv"))
            and not is_town_list_filename(f)
            and not INGEST_FILENAME_PATTERN.match(f)
            and not f.startswith("Ingest_merge_report_")
        ):
            # Excludes this script's own output. An ingest CSV's digital_file
            # column is full of TIFF filenames, so without these checks the
            # content test would read the output back in as a tifflist.
            maybe_by_content.append(f)

    by_content = [
        f for f in maybe_by_content
        if file_contains_tiff_filenames(os.path.join(directory, f))
    ]
    for f in by_content:
        print(f"  (recognized '{f}' as a tifflist by its content, not its name)")

    return sorted(by_name + by_content)
