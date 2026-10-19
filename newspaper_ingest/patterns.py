"""
Every compiled regular expression used by the pipeline, in one place.
"""

import re

# A TIFF filename, e.g. 18850116_vXI_n41_0001.tif
#   (\d{8})            - 8 digit date
#   _v([A-Za-z0-9]+)   - volume, roman numerals or a plain number
#   _n(\d+)            - issue/paper number
#   (?:[_-](\d+))?     - OPTIONAL page number, "_0001" or "-000001"
#   \.tiff?            - .tif or .tiff, case-insensitive
TIFF_NAME_PATTERN = re.compile(
    r'^(\d{8})_v([A-Za-z0-9]+)_n(\d+)(?:[_-](\d+))?\.tiff?$',
    re.IGNORECASE,
)

# Same as TIFF_NAME_PATTERN but unanchored, so it finds a TIFF filename
# anywhere in a longer line (a full path, or a Windows "dir" listing line).
TIFF_NAME_SEARCH_PATTERN = re.compile(
    r'(\d{8}_v[A-Za-z0-9]+_n\d+(?:[_-]\d+)?\.tiff?)',
    re.IGNORECASE,
)

# Pulls the sheet ID out of a Google Sheets URL.
GOOGLE_SHEETS_URL_PATTERN = re.compile(
    r'docs\.google\.com/spreadsheets/d/([a-zA-Z0-9_-]+)'
)

# Pulls the tab ID (gid) out of a Google Sheets URL, if present.
GOOGLE_SHEETS_GID_PATTERN = re.compile(r'[#&?]gid=(\d+)')

# "...tifflist.txt" or ".csv", keyword anywhere in the name.
TIFFLIST_FILENAME_PATTERN = re.compile(
    r'^(.*?)_?(?i:tifflist)\.(?i:txt|csv)$'
)

# "town list" keyword, with _, - or space (or nothing) as the separator.
TOWNLIST_KEYWORD_PATTERN = re.compile(r'(?i:town[_ -]?list)')

# An existing merged file from the older range-based layout, e.g. "1885-1886-ingest.csv".
INGEST_FILENAME_PATTERN = re.compile(
    r'^(\d{4})-(\d{4})-ingest(?:_part(\d+))?\.csv$', re.IGNORECASE
)

# A per-year ingest file, e.g. "1883-ingest.csv" or "1883-ingest_part2.csv".
YEAR_INGEST_FILENAME_PATTERN = re.compile(
    r'^(\d{4})-ingest(?:_part(\d+))?\.csv$', re.IGNORECASE
)

# An issue prefix at the START of a string, e.g. "18850102_vXI_n39.pdf".
ISSUE_PREFIX_PATTERN = re.compile(r'^(\d{8})_v([A-Za-z0-9]+)_n(\d+)')

# One entry in a Slim-format Subject cell: "Newspaper -- Deep River, CT".
SUBJECT_ENTRY_PATTERN = re.compile(r'^Newspaper -- (.+), CT$')

# An 8-digit YYYYMMDD date, used to pull a year out of a problem message.
# Loose enough to accept an invalid calendar date like Feb 31.
PROBLEM_YEAR_PATTERN = re.compile(
    r'(1[89]\d\d|20\d\d)(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])'
)

# A "[category]" tag at the start of a problem message.
PROBLEM_CATEGORY_PATTERN = re.compile(r'\[(\w+)\]')

# The bad date value inside an invalid_date problem message.
INVALID_DATE_VALUE_PATTERN = re.compile(r"invalid date \('([^']+)'\)")
