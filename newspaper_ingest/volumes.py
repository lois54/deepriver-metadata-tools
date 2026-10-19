"""
Volume and issue-identity helpers: roman numerals, normalizing volume
labels, and pulling (date, volume, paper number) out of issue filenames.
"""

import os
import re
from datetime import datetime

from .patterns import ISSUE_PREFIX_PATTERN, TOWNLIST_KEYWORD_PATTERN


def int_to_roman(n):
    """1 -> 'I', 14 -> 'XIV'. Volume numbers are small."""
    value_symbols = [
        (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
        (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
        (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
    ]
    result = []
    for value, symbol in value_symbols:
        while n >= value:
            result.append(symbol)
            n -= value
    return "".join(result)


def normalize_volume(volume_text):
    """Makes '1' and 'I' the same volume, so they don't count as two."""
    if volume_text.isdigit():
        return int_to_roman(int(volume_text))
    return volume_text.upper()


def extract_volume_token(prefix):
    """
    Given the text before a 'tifflist' / 'Town List' keyword in a filename
    (e.g. 'Vol_09_', 'vI_', ''), strip a 'Vol'/'v' label and return just
    the volume identifier.
    """
    prefix = prefix.strip(" _-")
    if not prefix:
        return ""

    match = re.match(r'(?i)^vol[_ -]?', prefix)
    if match:
        return prefix[match.end():].strip(" _-")

    # A bare lowercase 'v' followed by all-uppercase letters is a roman
    # numeral label ('vI', 'vIX'). Checking case avoids misreading a
    # roman numeral that starts with V ('VI') as having a label.
    if prefix[0] == "v" and len(prefix) > 1 and prefix[1:].isalpha() and prefix[1:] == prefix[1:].upper():
        return prefix[1:]

    return prefix


def parse_issue_prefix(text):
    """
    Pull (date_iso, volume, paper_no) from the START of a reference string
    like '18850102_vXI_n39.pdf'. Returns None if it doesn't match.

    date_iso is 'YYYY-MM-DD' for a real calendar date, or the raw 8-digit
    text otherwise.
    """
    match = ISSUE_PREFIX_PATTERN.match(text.strip())
    if not match:
        return None
    date_text, volume_raw, paper_no_text = match.groups()
    try:
        date_iso = datetime.strptime(date_text, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError:
        date_iso = date_text
    return date_iso, normalize_volume(volume_raw), int(paper_no_text)


def volume_from_town_list_filename(filename):
    """
    'Vol_1_Town_List.xlsx' -> 'I'. Returns None if the filename has no
    recognizable volume label.
    """
    name = os.path.splitext(filename)[0]
    prefix = TOWNLIST_KEYWORD_PATTERN.sub("", name)
    token = extract_volume_token(prefix)
    return normalize_volume(token) if token else None
