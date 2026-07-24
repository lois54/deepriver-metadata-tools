#!/usr/bin/env python3
# =============================================================================
# BUILD ISSUE CSV
# =============================================================================
#
# WHAT THIS SCRIPT DOES
# ----------------------------------------------------------------------------
# You have two things:
#
#   1. INFORMATION ABOUT YOUR TIFF FILES - one TIFF per newspaper *page*,
#      named like:  18850116_vXI_n41_0001.tif
#                   |________| |_| |__| |__|
#                    date       vol issue page
#
#      This can come from any ONE of three sources (auto-detected):
#        (a) a real folder full of .tif files on your computer, OR
#        (b) a CSV file listing one full TIFF path per line, e.g.:
#              /opt/ingest_data/uploads/3/1885/18850102_vXI_n39_0001.tif
#        (c) a text file that's a Windows "dir" command listing, e.g.:
#              06/24/2025  08:05 AM   9,082,646  18850102_vXI_n39_0001.tif
#
#   2. A "TOWN LIST" FILE - a spreadsheet (xlsx, csv, or a Google Sheets
#      URL) that a human filled in by looking at each issue and writing
#      down which towns that issue covers. This file can be in EITHER of
#      two layouts (we auto-detect which one you gave us):
#
#        FORMAT A ("old method" - one row per issue):
#            filename                 | No. | Subject 1  | Subject 2 | ...
#            18850102_vXI_n39.pdf     | 39  | Deep River | Chester   | ...
#
#        FORMAT B ("new method" - one column per issue, towns stacked down):
#            Paper No. | 39         | 40         | ...
#            Towns     | Deep River | Deep River | ...
#                       | Chester    | Chester    | ...
#
# WHAT THIS SCRIPT PRODUCES (written to the same folder as the TIFF
# source - the folder itself if you gave us one, or the folder the
# listing file lives in if you gave us that instead)
# ----------------------------------------------------------------------------
#   <base_name>_metadata.csv
#       This is the FULL, 64-COLUMN, ingest-ready CSV - the same shape
#       used elsewhere in the pipeline (process_newspapers.py):
#
#         - One "Publication Issue" PARENT row per issue, with fields
#           like held_by, rights_statement, description, persons,
#           origin_information, genre, notes, etc. already filled in
#           with the project's fixed values (see CONFIGURATION below).
#           subject / geographic_subject on this row are auto-filled
#           from the Town List (see below).
#
#         - One "Page" CHILD row per TIFF page, linked back to its
#           parent issue via the member_of column, with its own
#           digital_file path and page-number-based weight/title.
#
#       "ID" numbers count up continuously across the WHOLE file (parent
#       and page rows share one counter), matching how the repository
#       ingest format expects rows to be linked.
#
#       subject is auto-filled as:      "Newspaper -- <Town>, CT"  (one
#                                        per town, joined with ^^)
#       geographic_subject is filled as: "<Town> (Conn.)"           (one
#                                        per town, joined with ^^)
#
#       If an issue has TIFFs but no matching Town List entry, its
#       subject / geographic_subject are simply left blank - the issue
#       still gets a full row (so nothing is silently dropped from the
#       ingest file), but the errors CSV will flag it so you know to
#       track down the missing town data.
#
#   <base_name>_errors.csv
#       Every mismatch we found, so you can go fix the source data:
#           missing_tiffs       -> the Town List has a paper number that
#                                  doesn't have any matching TIFF files
#                                  (this paper number will NOT appear in
#                                  the metadata CSV at all, since there's
#                                  nothing to scan)
#           missing_town_list   -> we found TIFFs for a paper number that
#                                  isn't in the Town List (this issue DOES
#                                  still appear in the metadata CSV, just
#                                  with blank subject/geographic_subject)
#
# HOW TO RUN
# ----------------------------------------------------------------------------
#   python build_issue_csv.py /path/to/tiff_directory /path/to/TownList.xlsx
#
#   ...or use a listing file instead of a real folder:
#
#   python build_issue_csv.py /path/to/tiff_list.csv /path/to/TownList.xlsx
#
#   ...and/or a Google Sheets URL instead of a local Town List file:
#
#   python build_issue_csv.py /path/to/tiff_directory "https://docs.google.com/spreadsheets/d/XXXXXXXX/edit"
#
#   For a Google Sheets URL to work, the sheet's sharing setting must be
#   at least "Anyone with the link can view" (Share button, top right of
#   the sheet, then "Change to anyone with the link"). No Google login
#   or API key is needed - the script just downloads it as a CSV.
#
# DEPENDENCIES
# ----------------------------------------------------------------------------
#   pip install openpyxl --break-system-packages
#   (openpyxl is only needed if your Town List file is .xlsx; plain .csv
#    Town Lists, Google Sheets URLs, and TIFF listing files need no extra
#    install at all)
# =============================================================================

import os
import re
import io
import sys
import csv
import urllib.request
import urllib.error
from datetime import datetime

# =============================================================================
# CONFIGURATION - fixed values that go into every "Publication Issue" row.
# These match the values already established for process_newspapers.py -
# edit here if any of them ever change.
# =============================================================================

HELD_BY                      = "Deep River Public Library"
RIGHTS_STATEMENT             = "NO COPYRIGHT - UNITED STATES"
PUBLISH                      = "Y"
RESOURCE_TYPE                = "Text"
NEWSPAPER_NAME                = "Deep River New Era"
DESCRIPTION = ("Contact the Deep River Historical Society at "
               "860-526-1449 or info@deepriverhistoricalsociety.org.")

# member_of_existing_entity_id - the parent collection ID in the repository
MEMBER_OF_EXISTING_ENTITY_ID = 61106

GENRE = "newspapers"

# persons field - fixed credits block for every issue
PERSONS = (
    "Prann, Ernest L.|relators:pbl^^"
    "Deep River Historical Society|relators:ctb^^"
    "Webb, Robert; Charter Oak Scanning and Digitization|relators:ctb"
)

# notes field - fixed credits block for every issue
NOTES = (
    "creation/production credits|Deep River Public Library -- Patrick McGlamery^^"
    "creation/production credits|Chester Historical Society -- Adrian Nicholls^^"
    "creation/production credits|Westbrook Historical Society -- Sandy Forest^^"
    "credits|Deep River Historical Society--Simon LaPlace^^"
    "credits|Deep River Historical Society--AC Proctor"
)

# origin_information - treated as fixed (same value on every issue)
ORIGIN_INFORMATION = (
    "|Deep River, Conn.|Deep River (Conn.)^^"
    "||||2026-03-31|||Deep River New Era||serial|Weekly"
)

# The server-side path prefix that gets glued onto each TIFF's own filename
# to build the "digital_file" column, e.g.:
#   DIGITAL_FILE_PREFIX + "18850116_vXI_n41_0001.tif"
#   -> "/opt/ingest_data/uploads/3/tiff/18850116_vXI_n41_0001.tif"
DIGITAL_FILE_PREFIX = "/opt/ingest_data/uploads/3/tiff/"

# The character(s) used to glue multiple values into one CSV cell.
MULTI_SEP = "^^"

# All 64 column names, in the exact order the repository ingest expects.
COLUMNS = [
    "ID", "member_of", "member_of_existing_entity_id", "publish",
    "model", "held_by", "title", "rights_statement", "weight",
    "digital_file", "media_use", "digital_origin", "creative_commons",
    "use_and_reproduction", "restriction_on_access", "resource_type",
    "description", "local_identifier", "family_name", "persons",
    "organizations", "origin_information", "language", "genre",
    "subject", "temporal_subject", "geographic_subject", "notes",
    "scale", "physical_form", "reformatting_quality",
    "physical_description_note", "access_restriction_term",
    "related_items", "table_of_contents", "handle", "isbn",
    "oclc_number", "loc_classification", "coordinates",
    "geographic_code", "west_bounding_coordinate",
    "east_bounding_coordinate", "north_bounding_coordinate",
    "south_bounding_coordinate", "extent", "physical_location",
    "sublocation", "shelf_locator", "location_url",
    "record_information", "degree_name", "degree_level",
    "degree_discipline", "kingdom_dwr", "phylum_dwr", "class_dwr",
    "order_dwr", "family_dwr", "genus_dwr", "sci_name_auth_dwr",
    "locality_dwr", "location_remarks_dwr", "recorded_by_dwr",
]

# The pattern every TIFF filename must match. Written out piece by piece:
#   (\d{8})       - 8 digit date, e.g. 18850116
#   _v([A-Za-z]+) - underscore, "v", then the volume in roman numerals
#   _n(\d+)       - underscore, "n", then the issue/paper number
#   (?:_(\d+))?   - OPTIONAL underscore + page number (e.g. "_0001")
#   \.tiff?       - ".tif" or ".tiff", case-insensitive
TIFF_NAME_PATTERN = re.compile(
    r'^(\d{8})_v([A-Za-z]+)_n(\d+)(?:_(\d+))?\.tiff?$',
    re.IGNORECASE,
)

# Same idea as TIFF_NAME_PATTERN above, but WITHOUT the ^ and $ anchors,
# so it can find a TIFF filename ANYWHERE inside a longer line of text -
# e.g. buried in a full path ("/opt/.../18850116_vXI_n41_0001.tif") or
# at the end of a directory-listing line ("06/24/2025 8:05 AM  9,082,646
# 18850116_vXI_n41_0001.tif"). Used by read_tiff_list_file() below.
TIFF_NAME_SEARCH_PATTERN = re.compile(
    r'(\d{8}_v[A-Za-z]+_n\d+(?:_\d+)?\.tiff?)',
    re.IGNORECASE,
)

# Matches the sheet ID out of any Google Sheets URL, e.g. out of:
#   https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOp/edit#gid=0
# this captures "1AbCdEfGhIjKlMnOp".
GOOGLE_SHEETS_URL_PATTERN = re.compile(
    r'docs\.google\.com/spreadsheets/d/([a-zA-Z0-9_-]+)'
)

# Matches the specific TAB (worksheet) of the sheet, if the URL includes
# one, e.g. the "0" in "...edit#gid=0". If a Town List spreadsheet has
# more than one tab, this is how we know which one to read.
GOOGLE_SHEETS_GID_PATTERN = re.compile(r'[#&?]gid=(\d+)')


# =============================================================================
# STEP 1 - READ THE TOWN LIST FILE INTO A SIMPLE GRID
# =============================================================================
# Regardless of whether the Town List is .xlsx or .csv, we turn it into the
# same simple shape first: a list of rows, where each row is a list of
# plain-text cell values. Everything after this point works off that grid,
# so the rest of the code doesn't need to care which file format we started
# from.
# =============================================================================

def read_grid(source):
    """
    Read a Town List from EITHER:
        - a local file path ending in .xlsx or .csv, OR
        - a Google Sheets URL (the sheet just needs to be shared as
          "Anyone with the link can view" - no Google login needed)

    Either way, this returns the same simple list-of-lists "grid" shape,
    so nothing else in the script needs to know or care which kind of
    source the Town List actually came from.
    """
    if is_google_sheets_url(source):
        return fetch_google_sheet_grid(source)

    # Not a Google Sheets URL - treat it as a path to a local file.
    extension = os.path.splitext(source)[1].lower()

    if extension == ".xlsx":
        # openpyxl reads real Excel files. We only import it here (instead
        # of at the top of the file) so that people whose Town List is a
        # plain .csv (or a Google Sheet) never need to install openpyxl.
        import openpyxl

        workbook = openpyxl.load_workbook(source, data_only=True)
        worksheet = workbook.active  # the first/only sheet

        grid = []
        for row in worksheet.iter_rows(values_only=True):
            text_row = [cell_to_text(cell) for cell in row]
            grid.append(text_row)
        return grid

    elif extension == ".csv":
        with open(source, "r", newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            grid = [[cell.strip() for cell in row] for row in reader]
        return grid

    else:
        raise ValueError(
            f"Don't know how to read a Town List with extension "
            f"'{extension}'. Expected .xlsx, .csv, or a Google Sheets URL."
        )


def is_google_sheets_url(text):
    """
    True if the given string looks like a Google Sheets URL rather than
    a local file path. We just check whether it contains the
    "docs.google.com/spreadsheets/d/..." pattern that every Sheets URL
    has, regardless of whatever comes after it (/edit, #gid=123, etc.).
    """
    return bool(GOOGLE_SHEETS_URL_PATTERN.search(text))


def fetch_google_sheet_grid(sheet_url):
    """
    Download a Google Sheet as CSV text and parse it into the same
    list-of-lists "grid" shape that read_grid() produces for local files.

    HOW THIS WORKS: Google Sheets has a built-in "export as CSV" link for
    any sheet that's shared with at least "Anyone with the link can
    view". We build that export link ourselves from the URL you gave us,
    then download it with Python's built-in urllib (no extra libraries,
    no API key, no login needed) - it behaves just like clicking
    File > Download > CSV in your browser.
    """
    # Pull the long ID out of the URL, e.g. the "1AbCdEfGh..." part of
    # https://docs.google.com/spreadsheets/d/1AbCdEfGh.../edit
    id_match = GOOGLE_SHEETS_URL_PATTERN.search(sheet_url)
    if not id_match:
        raise ValueError(
            f"This doesn't look like a Google Sheets URL: {sheet_url}"
        )
    sheet_id = id_match.group(1)

    # If the URL specifies a particular tab (gid=...), use that tab.
    # Otherwise default to gid=0, which is the FIRST tab in the sheet.
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
        # This almost always means the sheet isn't shared publicly yet.
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

    # The downloaded bytes are plain CSV text - decode and parse them
    # exactly the same way we'd parse a downloaded .csv file. "utf-8-sig"
    # quietly strips a byte-order-mark if Google includes one.
    text = raw_bytes.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    grid = [[cell.strip() for cell in row] for row in reader]
    return grid


def cell_to_text(value):
    """
    Convert one raw Excel cell value into clean text.

    The tricky case this handles: Excel often stores whole numbers like
    "Paper No. 39" internally as the FLOAT 39.0, not the integer 39. If we
    just did str(39.0) we'd get the text "39.0" - and later code that
    checks "is this text just digits?" (paper_no_text.isdigit()) would
    say NO, because of the decimal point, and silently skip that whole
    issue. We fix that here, once, so nothing downstream has to worry
    about it: any float that has no fractional part (39.0, 40.0, ...)
    gets turned into a plain integer string ("39", "40", ...) instead.
    """
    if value is None:
        return ""

    if isinstance(value, float) and value.is_integer():
        return str(int(value))

    return str(value).strip()


# =============================================================================
# STEP 2 - TURN THE GRID INTO {paper_no: [town1, town2, ...]}
# =============================================================================
# This is the part that has to understand the TWO possible layouts.
# We look at the grid and decide which layout it is, then parse accordingly.
# =============================================================================

def parse_town_list(grid):
    """
    Parse a Town List grid (see read_grid) into a dictionary that maps:
        paper number (int)  ->  list of town names (list of str)

    Auto-detects whether the grid is in "Format A" (one row per issue,
    towns spread across columns) or "Format B" (one column per issue,
    towns stacked down rows) and calls the matching parser below.
    """
    if not grid or not grid[0]:
        raise ValueError("Town List file appears to be empty.")

    header_row = grid[0]
    first_cell = header_row[0].lower()

    if first_cell.startswith("paper"):
        # e.g. header_row[0] == "Paper No." -> issue numbers run ACROSS
        # this row, and towns are stacked DOWN each column below it.
        return parse_format_b_transposed(grid)
    else:
        # Otherwise assume Format A: one issue per row, with a "No." (or
        # similar) column holding the paper number.
        return parse_format_a_rows(grid)


def parse_format_a_rows(grid):
    """
    Parse "old method" layout:

        filename  | No. | Subject 1  | Subject 2 | ...
        18850...  | 39  | Deep River | Chester   | ...

    One issue per ROW. We find whichever column is the paper-number column
    (its header is something like "No." or "Paper No."), and every column
    after that is treated as a town name (blank cells are just skipped).
    """
    header_row = grid[0]

    # Find the column whose header looks like a paper-number column.
    # We accept things like "No.", "No", "Paper No.", case-insensitively.
    paper_no_col = None
    for col_index, header_text in enumerate(header_row):
        cleaned = header_text.strip().lower().rstrip(".")
        if cleaned in ("no", "paper no", "papernum", "paper number"):
            paper_no_col = col_index
            break

    if paper_no_col is None:
        raise ValueError(
            "Couldn't find a paper-number column (looked for a header "
            "like 'No.' or 'Paper No.') in this Town List file."
        )

    town_list_by_paper_no = {}

    # Walk every data row (skip the header row itself).
    for row in grid[1:]:
        if paper_no_col >= len(row):
            continue  # row is too short to even have a paper number

        paper_no_text = row[paper_no_col].strip()
        if not paper_no_text.isdigit():
            continue  # blank trailing row, or something we can't parse

        paper_no = int(paper_no_text)

        # Every column AFTER the paper-number column is a potential town.
        # Blank cells are simply skipped (that's how the padding works).
        towns = [
            cell.strip()
            for cell in row[paper_no_col + 1:]
            if cell.strip()
        ]

        town_list_by_paper_no[paper_no] = towns

    return town_list_by_paper_no


def parse_format_b_transposed(grid):
    """
    Parse "new method" layout:

        Paper No. | 39         | 40         | ...
        Towns     | Deep River | Deep River | ...
                   | Chester    | Chester    | ...

    One issue per COLUMN. Row 0 holds the paper numbers themselves
    (starting at column 1; column 0 is just the "Paper No." label).
    Every row after that holds one more town for each column, reading
    top-to-bottom until the cells run out (blank = no more towns).
    """
    header_row = grid[0]
    town_list_by_paper_no = {}

    # Walk every column starting at index 1 (index 0 is the row label).
    for col_index in range(1, len(header_row)):
        paper_no_text = header_row[col_index].strip()
        if not paper_no_text.isdigit():
            continue  # not a real paper-number column, skip it

        paper_no = int(paper_no_text)

        # Collect every non-blank town for this column, from row 1 down
        # to the bottom of the grid.
        towns = []
        for row in grid[1:]:
            if col_index < len(row):
                town = row[col_index].strip()
                if town:
                    towns.append(town)

        town_list_by_paper_no[paper_no] = towns

    return town_list_by_paper_no


# =============================================================================
# STEP 3 - GET TIFF FILENAMES AND GROUP PAGES INTO ISSUES
# =============================================================================
# There are two ways to tell this script about your TIFFs:
#   (a) point it at a real folder full of TIFFs on your computer, or
#   (b) point it at a CSV/text file that just LISTS the filenames (handy
#       when the actual TIFFs live somewhere you can't browse directly,
#       like a remote ingest server).
# Both paths end up producing the exact same "issues_by_paper_no" shape,
# via the shared parse_tiff_filename() helper below.
# =============================================================================

def parse_tiff_filename(filename):
    """
    Pull the useful pieces out of one TIFF filename, e.g.
    "18850116_vXI_n41_0001.tif" ->

        issue_id   = "18850116_vXI_n41"   (filename with page # removed)
        date_iso   = "1885-01-16"
        volume     = "XI"
        paper_no   = 41                   (as an int)
        page_number = 1                   (as an int, defaults to 1 if
                                            the filename has no page #)

    Returns None if the filename doesn't match TIFF_NAME_PATTERN at all
    (callers are expected to check for that and handle it themselves).
    """
    match = TIFF_NAME_PATTERN.match(filename)
    if not match:
        return None

    date_text, volume, paper_no_text, page_text = match.groups()
    paper_no = int(paper_no_text)

    # Turn "18850116" into a readable date like "1885-01-16".
    # If a filename ever has a nonsense date, we don't want the whole
    # script to crash - fall back to the raw text instead.
    try:
        date_obj = datetime.strptime(date_text, "%Y%m%d")
        date_iso = date_obj.strftime("%Y-%m-%d")
    except ValueError:
        date_iso = date_text  # fall back to raw digits

    issue_id = f"{date_text}_v{volume}_n{paper_no_text}"

    # The page number group is OPTIONAL in the filename pattern (see
    # TIFF_NAME_PATTERN above). If a filename has no page number at all,
    # we just use 1 - it's almost certainly a single-page issue.
    page_number = int(page_text) if page_text else 1

    return issue_id, date_iso, volume, paper_no, page_number


def scan_tiff_directory(tiff_dir):
    """
    Look at every .tif/.tiff file in a real folder on disk, parse each
    filename, and group the individual PAGE files into ISSUES.

    Returns a dictionary that maps:
        paper number (int) -> {
            "issue_id": "18850116_vXI_n41",   # filename with page # removed
            "date":     "1885-01-16",         # ISO-formatted date string
            "volume":   "XI",
            "pages": [                        # one entry per page TIFF,
                {"filename": "...0001.tif", "page_number": 1,
                 "digital_file": "/opt/ingest_data/uploads/3/tiff/...0001.tif"},
                ...
            ]
        }

    Files that don't match the expected naming pattern are collected
    separately and returned too, so the calling code can report them.
    """
    issues_by_paper_no = {}
    unrecognized_files = []

    for filename in sorted(os.listdir(tiff_dir)):
        # Only look at .tif / .tiff files - skip everything else
        # (this also naturally skips subfolders, .DS_Store, etc.)
        if not filename.lower().endswith((".tif", ".tiff")):
            continue

        parsed = parse_tiff_filename(filename)
        if parsed is None:
            unrecognized_files.append(filename)
            continue

        issue_id, date_iso, volume, paper_no, page_number = parsed

        # First time we've seen this paper number? Start a new entry.
        if paper_no not in issues_by_paper_no:
            issues_by_paper_no[paper_no] = {
                "issue_id": issue_id,
                "date": date_iso,
                "volume": volume,
                "pages": [],
            }

        issues_by_paper_no[paper_no]["pages"].append({
            "filename": filename,
            "page_number": page_number,
            # We're scanning a real local folder here, so we don't know
            # the eventual server-side path - build it ourselves using
            # the standard prefix, same as always.
            "digital_file": DIGITAL_FILE_PREFIX + filename,
        })

    return issues_by_paper_no, unrecognized_files


def read_tiff_list_file(list_file_path):
    """
    Read TIFF filenames out of a plain CSV or text "listing" file instead
    of scanning an actual folder on disk. Handles TWO kinds of listing
    files automatically - you don't need to tell us which one you have:

        FORMAT 1 - one full path per line, e.g.:
            /opt/ingest_data/uploads/3/1885/18850102_vXI_n39_0001.tif

        FORMAT 2 - a Windows "dir" command listing, e.g.:
            06/24/2025  08:05 AM     9,082,646  18850612_vXII_n10_0005.tif

    For every line, we just look for a TIFF filename matching our naming
    pattern ANYWHERE in the line (see TIFF_NAME_SEARCH_PATTERN) and pull
    it out - everything else on the line (a directory path, a date/time/
    size) is ignored, except to figure out the "digital_file" value:

        - If a "/" appears immediately before the filename, the line
          already contains a full path (Format 1) - we use that whole
          path as digital_file, since it's more accurate than anything
          we could build ourselves.
        - Otherwise (Format 2, just a bare filename) we build
          digital_file the normal way, using DIGITAL_FILE_PREFIX.

    Returns the exact same shape as scan_tiff_directory(): a dictionary
    of issues, plus a list of any lines we couldn't make sense of.
    """
    issues_by_paper_no = {}
    unrecognized_lines = []

    # "utf-8-sig" quietly strips a byte-order-mark if the file has one
    # (common in files saved from Windows tools). Universal newline
    # handling (the default in text mode) takes care of \r\n line
    # endings automatically, so we don't need to worry about those.
    with open(list_file_path, "r", encoding="utf-8-sig") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue  # skip blank lines

            match = TIFF_NAME_SEARCH_PATTERN.search(line)
            if not match:
                unrecognized_lines.append(line)
                continue

            filename = match.group(1)

            # Was there a full path in front of the filename? Check for
            # a "/" character immediately before where the match starts.
            starts_at = match.start()
            if starts_at > 0 and line[starts_at - 1] == "/":
                digital_file = line[:match.end()]
            else:
                digital_file = DIGITAL_FILE_PREFIX + filename

            parsed = parse_tiff_filename(filename)
            if parsed is None:
                # Shouldn't normally happen (the search pattern is a
                # looser version of the same rule), but just in case:
                unrecognized_lines.append(line)
                continue

            issue_id, date_iso, volume, paper_no, page_number = parsed

            if paper_no not in issues_by_paper_no:
                issues_by_paper_no[paper_no] = {
                    "issue_id": issue_id,
                    "date": date_iso,
                    "volume": volume,
                    "pages": [],
                }

            issues_by_paper_no[paper_no]["pages"].append({
                "filename": filename,
                "page_number": page_number,
                "digital_file": digital_file,
            })

    return issues_by_paper_no, unrecognized_lines


# =============================================================================
# STEP 4 - TURN A TOWN LIST INTO subject / geographic_subject TEXT
# =============================================================================

def build_subject_and_geo(towns):
    """
    Turn a list of town names into the two formatted strings that go into
    the "subject" and "geographic_subject" columns.

        towns = ["Chester", "Essex"]

        subject_val            -> "Newspaper -- Chester, CT^^Newspaper -- Essex, CT"
        geographic_subject_val -> "Chester (Conn.)^^Essex (Conn.)"

    If towns is an empty list (no Town List match for this issue), both
    returned strings are just "" - left blank for a volunteer to fill in.
    """
    subject_val = MULTI_SEP.join(f"Newspaper -- {town}, CT" for town in towns)
    geographic_subject_val = MULTI_SEP.join(f"{town} (Conn.)" for town in towns)
    return subject_val, geographic_subject_val


def format_date_long(date_iso):
    """
    Turn an ISO date string ("1885-01-16") into the long display format
    used in titles ("Jan 16, 1885") - month abbreviation, day WITHOUT a
    leading zero, four-digit year.
    """
    date_obj = datetime.strptime(date_iso, "%Y-%m-%d")
    # strftime's %-d (no leading zero) isn't reliably cross-platform, so
    # we build the day number ourselves with plain str() instead.
    return f"{date_obj.strftime('%b')} {date_obj.day}, {date_obj.year}"


# =============================================================================
# STEP 5 - BUILD THE FULL, 64-COLUMN INGEST ROWS
# =============================================================================

def build_ingest_rows(tiff_issues, town_lists):
    """
    Build the complete list of CSV rows (as dictionaries keyed by column
    name) for every issue found in the TIFF directory: one "Publication
    Issue" parent row followed by one "Page" row per TIFF page.

    Every issue found in the TIFF scan gets a row here, even if it has no
    matching Town List entry - in that case subject/geographic_subject
    are simply left blank (see build_subject_and_geo above).
    """
    rows = []

    # A single counter shared by parent AND page rows, since the "ID"
    # column has to count up continuously across the whole file.
    next_id = 1

    # Process issues in chronological order so the CSV reads top-to-bottom
    # the way the newspaper was actually published.
    ordered_paper_nos = sorted(
        tiff_issues.keys(),
        key=lambda paper_no: tiff_issues[paper_no]["date"],
    )

    for paper_no in ordered_paper_nos:
        issue = tiff_issues[paper_no]

        # town_lists.get(...) returns [] (not an error) if this issue has
        # no Town List entry - build_subject_and_geo then just returns
        # two blank strings, which is exactly what we want.
        towns = town_lists.get(paper_no, [])
        subject_val, geo_val = build_subject_and_geo(towns)

        issue_num_padded = f"{paper_no:02d}"
        date_long = format_date_long(issue["date"])
        parent_title = (
            f"{NEWSPAPER_NAME} - {date_long}; "
            f"Vol. {issue['volume']} No. {issue_num_padded}"
        )

        # ---- Build the "Publication Issue" parent row -------------------
        parent_id = next_id
        next_id += 1

        # Start every row as entirely blank, then only fill in the
        # columns that actually apply. This means we never forget to
        # blank out a column that shouldn't have a value.
        parent_row = {column: "" for column in COLUMNS}
        parent_row.update({
            "ID": parent_id,
            "member_of_existing_entity_id": MEMBER_OF_EXISTING_ENTITY_ID,
            "publish": PUBLISH,
            "model": "Publication Issue",
            "held_by": HELD_BY,
            "title": parent_title,
            "rights_statement": RIGHTS_STATEMENT,
            "resource_type": RESOURCE_TYPE,
            "description": DESCRIPTION,
            "persons": PERSONS,
            "origin_information": ORIGIN_INFORMATION,
            "genre": GENRE,
            "subject": subject_val,
            "geographic_subject": geo_val,
            "notes": NOTES,
        })
        rows.append(parent_row)

        # ---- Build one "Page" child row per TIFF page --------------------
        sorted_pages = sorted(issue["pages"], key=lambda p: p["page_number"])

        for page in sorted_pages:
            page_id = next_id
            next_id += 1

            page_row = {column: "" for column in COLUMNS}
            page_row.update({
                "ID": page_id,
                "member_of": parent_id,   # links this page back to its issue
                "publish": PUBLISH,
                "model": "Page",
                "held_by": HELD_BY,
                "title": f"{parent_title} Page {page['page_number']}",
                "rights_statement": RIGHTS_STATEMENT,
                "weight": page["page_number"],
                "digital_file": page["digital_file"],
                "media_use": "Original File",
                "digital_origin": "reformatted digital",
                "resource_type": RESOURCE_TYPE,
            })
            rows.append(page_row)

    return rows


# =============================================================================
# STEP 6 - WRITE BOTH OUTPUT FILES
# =============================================================================

def build_and_write_csvs(output_dir, base_name, source_description,
                          town_lists, tiff_issues, unrecognized_items):
    """
    Combine the town-list lookup with the TIFF issues, then write:
        <base_name>_metadata.csv  - the full 64-column ingest CSV
        <base_name>_errors.csv    - every mismatch / problem we found

    output_dir      - folder the two output files get written into
    base_name       - used to build both output filenames
    source_description - a short human-readable phrase describing where
                          the TIFF info came from (a directory path, or
                          a listing file path) - only used in wording
                          inside the errors CSV
    """
    metadata_path = os.path.join(output_dir, f"{base_name}_metadata.csv")
    errors_path = os.path.join(output_dir, f"{base_name}_errors.csv")

    # -------------------------------------------------------------------
    # Figure out which paper numbers matched, and which didn't, on
    # EITHER side.
    # -------------------------------------------------------------------
    town_list_paper_nos = set(town_lists.keys())
    tiff_paper_nos = set(tiff_issues.keys())

    only_in_town_list = town_list_paper_nos - tiff_paper_nos  # missing scans
    only_in_tiffs = tiff_paper_nos - town_list_paper_nos      # missing towns

    # -------------------------------------------------------------------
    # Write the main, full-format metadata CSV.
    # -------------------------------------------------------------------
    ingest_rows = build_ingest_rows(tiff_issues, town_lists)

    with open(metadata_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(ingest_rows)

    # -------------------------------------------------------------------
    # Write the errors CSV - every mismatch, so it's easy to go fix things.
    # -------------------------------------------------------------------
    error_rows = []

    for paper_no in sorted(only_in_town_list):
        error_rows.append({
            "paper_no": paper_no,
            "problem": "missing_tiffs",
            "details": (
                f"Town List has paper #{paper_no} with towns "
                f"({MULTI_SEP.join(town_lists[paper_no])}), but no TIFF "
                f"for that paper number was found in {source_description}. "
                f"This issue does NOT appear in the metadata CSV."
            ),
        })

    for paper_no in sorted(only_in_tiffs):
        issue = tiff_issues[paper_no]
        error_rows.append({
            "paper_no": paper_no,
            "problem": "missing_town_list",
            "details": (
                f"Found {len(issue['pages'])} TIFF page(s) for paper "
                f"#{paper_no} (issue_id: {issue['issue_id']}), but the "
                f"Town List has no entry for that paper number. This "
                f"issue WAS included in the metadata CSV, with blank "
                f"subject / geographic_subject."
            ),
        })

    for item in unrecognized_items:
        error_rows.append({
            "paper_no": "",
            "problem": "unrecognized_filename",
            "details": (
                f"'{item}' does not match the expected pattern "
                f"YYYYMMDD_vVOL_nNN_PPPP.tif and was skipped entirely."
            ),
        })

    with open(errors_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["paper_no", "problem", "details"])
        writer.writeheader()
        writer.writerows(error_rows)

    # -------------------------------------------------------------------
    # Print a friendly summary to the terminal so you know what happened
    # without having to open either file.
    # -------------------------------------------------------------------
    issue_count = len(tiff_issues)
    page_count = sum(len(issue["pages"]) for issue in tiff_issues.values())

    print("Done!")
    print(f"  Issues written to metadata CSV:       {issue_count}")
    print(f"  Page rows written to metadata CSV:    {page_count}")
    print(f"  Problems written to errors CSV:       {len(error_rows)}")
    print(f"    - paper numbers with no TIFFs:      {len(only_in_town_list)}")
    print(f"    - TIFFs with no Town List entry:    {len(only_in_tiffs)}")
    print(f"    - unrecognized filenames skipped:   {len(unrecognized_items)}")
    print()
    print(f"  Metadata CSV: {metadata_path}")
    print(f"  Errors CSV:   {errors_path}")


# =============================================================================
# MAIN - this is what runs when you type "python build_issue_csv.py ..."
# =============================================================================

def main():
    # sys.argv is the list of things typed on the command line.
    # sys.argv[0] is always the script name itself, so real arguments
    # start at sys.argv[1].
    if len(sys.argv) != 3:
        print("Usage: python build_issue_csv.py <tiff_directory_or_listing_file> <townlist_file_or_google_sheet_url>")
        print()
        print("The first argument can be EITHER:")
        print("  - a real folder full of .tif files, OR")
        print("  - a .csv or .txt file that just LISTS the TIFF filenames")
        print("    (one full path per line, or a Windows 'dir' listing)")
        sys.exit(1)

    tiff_source = sys.argv[1]
    townlist_file = sys.argv[2]

    # Only check "does this file exist on disk" for LOCAL Town List
    # files - a Google Sheets URL obviously isn't a path on this
    # computer, so that check would always (wrongly) fail for it.
    if not is_google_sheets_url(townlist_file) and not os.path.isfile(townlist_file):
        print(f"ERROR: Town List file not found: {townlist_file}")
        sys.exit(1)

    print(f"Reading Town List: {townlist_file}")
    grid = read_grid(townlist_file)
    town_lists = parse_town_list(grid)
    print(f"  Found {len(town_lists)} issue(s) in the Town List.")

    # ---- Figure out what kind of thing tiff_source is, and read it ----
    if os.path.isdir(tiff_source):
        # A real folder - scan it for .tif files the old way.
        print(f"Scanning TIFF directory: {tiff_source}")
        tiff_issues, unrecognized_items = scan_tiff_directory(tiff_source)

        # Output files go INTO that same folder, named after it.
        output_dir = tiff_source
        base_name = os.path.basename(tiff_source.rstrip(os.sep)) or "output"
        source_description = f"the '{tiff_source}' directory"

    elif os.path.isfile(tiff_source):
        # A listing file (.csv or .txt) - read filenames out of it
        # instead of browsing an actual folder.
        print(f"Reading TIFF filenames from listing file: {tiff_source}")
        tiff_issues, unrecognized_items = read_tiff_list_file(tiff_source)

        # Output files go into the SAME FOLDER AS THE LISTING FILE
        # (since that's the only local location we actually have),
        # named after the listing file itself rather than a directory.
        output_dir = os.path.dirname(os.path.abspath(tiff_source)) or "."
        base_name = os.path.splitext(os.path.basename(tiff_source))[0]
        source_description = f"the '{tiff_source}' listing file"

    else:
        print(f"ERROR: '{tiff_source}' is not a directory or a file.")
        sys.exit(1)

    print(f"  Found {len(tiff_issues)} issue(s) worth of TIFF pages.")
    if unrecognized_items:
        noun = "entry" if len(unrecognized_items) == 1 else "entries"
        print(f"  ({len(unrecognized_items)} {noun} didn't match the expected "
              f"naming pattern and will be skipped - see the errors CSV.)")

    print("Combining and writing output files...")
    build_and_write_csvs(
        output_dir, base_name, source_description,
        town_lists, tiff_issues, unrecognized_items,
    )


if __name__ == "__main__":
    main()
