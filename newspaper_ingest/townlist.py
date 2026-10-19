"""
Town List handling: reading the three possible layouts (local .xlsx,
local .csv, or a Google Sheets URL) into a plain grid, parsing that grid
into {(volume, paper_no): [towns]}, and finding Town List files.
"""

import csv
import io
import os
import urllib.error
import urllib.request

from .config import MULTI_SEP
from .patterns import (
    GOOGLE_SHEETS_GID_PATTERN,
    GOOGLE_SHEETS_URL_PATTERN,
    SUBJECT_ENTRY_PATTERN,
    TOWNLIST_KEYWORD_PATTERN,
)
from .volumes import parse_issue_prefix, volume_from_town_list_filename


# =============================================================================
# STEP 1 - READ THE TOWN LIST FILE INTO A SIMPLE GRID
# Whether the source is .xlsx, .csv, or a Google Sheets URL, the result is a
# list of rows, each a list of plain-text cells.
# =============================================================================

def read_grid(source):
    """Read a Town List from a local .xlsx/.csv path or a Google Sheets URL."""
    if is_google_sheets_url(source):
        return fetch_google_sheet_grid(source)

    extension = os.path.splitext(source)[1].lower()

    if extension == ".xlsx":
        # Imported here so people whose Town List is a .csv or a Sheets URL
        # never need openpyxl installed.
        import openpyxl

        workbook = openpyxl.load_workbook(source, data_only=True)
        worksheet = workbook.active
        grid = []
        for row in worksheet.iter_rows(values_only=True):
            grid.append([cell_to_text(cell) for cell in row])
        return grid

    elif extension == ".csv":
        with open(source, "r", newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            return [[cell.strip() for cell in row] for row in reader]

    else:
        raise ValueError(
            f"Don't know how to read a Town List with extension "
            f"'{extension}'. Expected .xlsx, .csv, or a Google Sheets URL."
        )


def is_google_sheets_url(text):
    """True if the string contains a docs.google.com/spreadsheets/d/ URL."""
    return bool(GOOGLE_SHEETS_URL_PATTERN.search(text))


def fetch_google_sheet_grid(sheet_url):
    """
    Download a Google Sheet as CSV and parse it into a grid. The sheet must
    be shared as 'Anyone with the link can view'. No API key or login needed.
    """
    id_match = GOOGLE_SHEETS_URL_PATTERN.search(sheet_url)
    if not id_match:
        raise ValueError(
            f"This doesn't look like a Google Sheets URL: {sheet_url}"
        )
    sheet_id = id_match.group(1)

    gid_match = GOOGLE_SHEETS_GID_PATTERN.search(sheet_url)
    gid = gid_match.group(1) if gid_match else "0"

    export_url = (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}"
        f"/export?format=csv&gid={gid}"
    )

    try:
        with urllib.request.urlopen(export_url) as response:
            raw_bytes = response.read()
    except urllib.error.HTTPError as err:
        raise RuntimeError(
            f"Couldn't download the Google Sheet (HTTP error {err.code}). "
            f"Make sure the sheet's sharing setting is set to 'Anyone "
            f"with the link can view' (click Share, top right of the "
            f"sheet, then change 'Restricted' to 'Anyone with the "
            f"link'), then try again."
        ) from err
    except urllib.error.URLError as err:
        raise RuntimeError(
            f"Couldn't reach Google to download the sheet ({err.reason}). "
            f"Check your internet connection and try again."
        ) from err

    text = raw_bytes.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    return [[cell.strip() for cell in row] for row in reader]


def cell_to_text(value):
    """
    Turn one raw Excel cell into clean text. Excel stores whole numbers as
    floats (39.0), so a float with no fractional part becomes '39', not
    '39.0'. Without this, isdigit() checks downstream would silently skip
    the issue.
    """
    if value is None:
        return ""

    if isinstance(value, float) and value.is_integer():
        return str(int(value))

    return str(value).strip()


# =============================================================================
# STEP 2 - TURN THE GRID INTO {(volume, paper_no): [town1, town2, ...]}
# =============================================================================

def parse_town_list(grid):
    """
    Parse a grid into (town_list, town_dates):
        town_list  - dict[(volume, paper_no)] -> list of town names
        town_dates - dict[(volume, paper_no)] -> date_iso, where a filename
                     column supplied one (may be empty)

    Auto-detects which layout the grid is in:
        Format A - one row per issue, "No." column, towns across columns
        Format B - "Paper No." header row, towns stacked down columns
        Format C - "Slim" layout with pre-filled Subject/Geographic columns
    """
    if not grid or not grid[0]:
        raise ValueError("Town List file appears to be empty.")

    header_row = grid[0]
    header_lower = [cell.strip().lower() for cell in header_row]
    first_cell = header_row[0].lower()

    if "subject" in header_lower and "geographic" in header_lower:
        return parse_format_c_slim(grid)
    elif first_cell.startswith("paper"):
        return parse_format_b_transposed(grid)
    else:
        return parse_format_a_rows(grid)


def parse_format_a_rows(grid):
    """
    Parse the "one row per issue" layout. The paper number comes from a
    'No.' / 'Paper No.' column, or, if there is none, from a filename column
    (a header containing 'file') whose values look like
    '19030102_vXXIX_n40'. Every column after the number (or filename) is a
    town name; blank cells are skipped.

    A reference-filename column placed BEFORE the paper-number column
    supplies each row's volume, since paper numbers reset every volume.

    Returns (town_list, town_dates), as in parse_town_list.
    """
    header_row = grid[0]

    paper_no_col = None
    for col_index, header_text in enumerate(header_row):
        cleaned = header_text.strip().lower().rstrip(".")
        if cleaned in ("no", "paper no", "papernum", "paper number"):
            paper_no_col = col_index
            break

    if paper_no_col is not None:
        reference_col = None
        for col_index in range(paper_no_col):
            if "file" in header_row[col_index].strip().lower():
                reference_col = col_index
                break
    else:
        reference_col = None
        for col_index, header_text in enumerate(header_row):
            if "file" in header_text.strip().lower():
                reference_col = col_index
                break

        if reference_col is None:
            raise ValueError(
                "Couldn't find a paper-number column (looked for a "
                "header like 'No.' or 'Paper No.') or a filename "
                "column (looked for a header containing 'File') to "
                "get the paper number from in this Town List file."
            )

    town_list = {}
    town_dates = {}

    for row in grid[1:]:
        volume = None
        date_iso = None

        if paper_no_col is not None:
            if paper_no_col >= len(row):
                continue

            paper_no_text = row[paper_no_col].strip()
            if not paper_no_text.isdigit():
                continue

            paper_no = int(paper_no_text)

            if reference_col is not None and reference_col < len(row):
                parsed = parse_issue_prefix(row[reference_col])
                if parsed:
                    date_iso, volume, _ = parsed

            towns_start_col = paper_no_col + 1
        else:
            if reference_col >= len(row):
                continue

            parsed = parse_issue_prefix(row[reference_col])
            if not parsed:
                continue
            date_iso, volume, paper_no = parsed

            towns_start_col = reference_col + 1

        towns = [
            cell.strip()
            for cell in row[towns_start_col:]
            if cell.strip()
        ]

        town_list[(volume, paper_no)] = towns
        if date_iso:
            town_dates[(volume, paper_no)] = date_iso

    return town_list, town_dates


def parse_format_b_transposed(grid):
    """
    Parse the "new method" layout: paper numbers across row 0, towns stacked
    down each column below. There is no per-row volume, so every key's
    volume is None (resolved later by resolve_town_list_volumes).

    Returns (town_list, {}). There are no filename dates in this layout.
    """
    header_row = grid[0]
    town_list = {}

    for col_index in range(1, len(header_row)):
        paper_no_text = header_row[col_index].strip()
        if not paper_no_text.isdigit():
            continue

        paper_no = int(paper_no_text)

        towns = []
        for row in grid[1:]:
            if col_index < len(row):
                town = row[col_index].strip()
                if town:
                    towns.append(town)

        town_list[(None, paper_no)] = towns

    return town_list, {}


def parse_format_c_slim(grid):
    """
    Parse the "Slim" layout, where Subject is already filled in as
    'Newspaper -- Deep River, CT^^...'. The plain town names are pulled back
    out of the Subject column, so the Geographic column isn't trusted on its
    own (it could drift out of sync if hand-edited).

    Each row is identified by the filename in column 0, which supplies the
    volume and date. Rows that don't parse, or have a blank Subject, are
    skipped.

    Returns (town_list, town_dates).
    """
    header_row = grid[0]
    header_lower = [cell.strip().lower() for cell in header_row]
    subject_col = header_lower.index("subject")

    town_list = {}
    town_dates = {}

    for row in grid[1:]:
        if not row or not row[0].strip():
            continue

        parsed = parse_issue_prefix(row[0])
        if parsed is None:
            continue

        date_iso, volume, paper_no = parsed

        towns = []
        if subject_col < len(row) and row[subject_col].strip():
            for entry in row[subject_col].split(MULTI_SEP):
                match = SUBJECT_ENTRY_PATTERN.match(entry.strip())
                if match:
                    towns.append(match.group(1))

        town_list[(volume, paper_no)] = towns
        if date_iso:
            town_dates[(volume, paper_no)] = date_iso

    return town_list, town_dates


# =============================================================================
# FILE DISCOVERY AND VOLUME RESOLUTION
# =============================================================================

def is_town_list_filename(filename):
    """True for any .xlsx/.csv whose name contains the 'town list' keyword."""
    if not filename.lower().endswith((".xlsx", ".csv")):
        return False
    return bool(TOWNLIST_KEYWORD_PATTERN.search(filename))


def find_town_list_source_files(directory):
    """Every file in `directory` that looks like a Town List, by name."""
    return sorted(
        f for f in os.listdir(directory)
        if not f.startswith(".") and is_town_list_filename(f)
    )


def resolve_town_list_volumes(town_lists, tiff_issues, filename_hint=None):
    """
    Entries keyed (None, paper_no) don't say which volume they belong to.
    Resolve them, in order of preference:
        1. The volume label in the Town List's own filename (e.g. Vol_1_...)
        2. If every TIFF issue belongs to one volume, use that volume
        3. Otherwise drop the rows and report a problem

    Returns (resolved_town_lists, problems). Every key in resolved_town_lists
    is (volume, paper_no).
    """
    none_keys = [k for k in town_lists if k[0] is None]
    if not none_keys:
        return town_lists, []

    resolved = {k: v for k, v in town_lists.items() if k[0] is not None}
    problems = []

    fallback_volume = volume_from_town_list_filename(filename_hint) if filename_hint else None
    if fallback_volume is None:
        candidate_volumes = {k[0] for k in tiff_issues}
        if len(candidate_volumes) == 1:
            fallback_volume = next(iter(candidate_volumes))

    if fallback_volume:
        for (_, paper_no) in none_keys:
            resolved[(fallback_volume, paper_no)] = town_lists[(None, paper_no)]
    else:
        problems.append(
            f"[unresolved_volume] {len(none_keys)} row(s) use plain paper "
            f"numbers with no way to tell which volume they belong to "
            f"(no per-row filename reference, no single matching volume "
            f"among the TIFF data, and no volume label in this file's own "
            f"name) - these rows were skipped."
        )

    return resolved, problems
