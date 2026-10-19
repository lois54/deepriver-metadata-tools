"""
Issue records: turning TIFF issues and Town List towns into the per-issue
content (title, subject, publisher, origin), auto-correcting obviously
mistyped dates, and gathering everything in DataWaiting into one pool.
"""

import os
from datetime import datetime, timedelta

from .config import (
    MAX_DATE_CORRECTION_GAP_DAYS,
    MULTI_SEP,
    NEWSPAPER_NAME,
    ORIGIN_FREQUENCY,
    ORIGIN_ISSUANCE,
    ORIGIN_PLACE,
    PERSONS_STATIC_SUFFIX,
    PUBLISHER_BY_DATE,
)
from .timeutil import format_date_long, parse_iso_date_or_none
from .tiffs import find_tiff_source_files, read_tiff_list_file
from .townlist import (
    find_town_list_source_files,
    parse_town_list,
    read_grid,
    resolve_town_list_volumes,
)


# =============================================================================
# ORIGIN, PUBLISHER, AND SUBJECT FIELDS
# =============================================================================

def build_origin_information(date_created, publisher):
    """
    One issue's origin_information value: 13 pipe-delimited subfields.

    date_captured is always today's date (when this script ran), not a
    fixed value.
    """
    date_captured = datetime.now().strftime("%Y-%m-%d")
    fields = [
        "",                 # event_type
        ORIGIN_PLACE,       # place
        date_created,       # date_created
        "",                 # date_issued
        date_captured,      # date_captured
        "",                 # date_valid
        "",                 # date_modified
        "",                 # other_date
        "",                 # copyright_date
        publisher,          # publisher
        "",                 # edition
        ORIGIN_ISSUANCE,    # issuance
        ORIGIN_FREQUENCY,   # frequency
    ]
    return "|".join(fields)


def get_publisher(date_created):
    """
    The publisher in charge on a given date_created ('YYYY-MM-DD').
    Dates compare correctly as plain strings in that format.
    """
    publisher = PUBLISHER_BY_DATE[0][1]
    for effective_date, name in PUBLISHER_BY_DATE:
        if date_created >= effective_date:
            publisher = name
        else:
            break
    return publisher


def build_persons(date_created):
    """The era-appropriate publisher (relators:pbl), then the fixed credits."""
    publisher = get_publisher(date_created)
    return f"{publisher}|relators:pbl^^{PERSONS_STATIC_SUFFIX}"


def build_subject_and_geo(towns):
    """
    Turn a list of town names into the subject and geographic_subject strings.

        ["Chester", "Essex"] ->
            subject:            "Newspaper -- Chester, CT^^Newspaper -- Essex, CT"
            geographic_subject: "Chester (Conn.)^^Essex (Conn.)"

    An empty list gives two empty strings.
    """
    subject_val = MULTI_SEP.join(f"Newspaper -- {town}, CT" for town in towns)
    geographic_subject_val = MULTI_SEP.join(f"{town} (Conn.)" for town in towns)
    return subject_val, geographic_subject_val


# =============================================================================
# ISSUE RECORDS
# =============================================================================

def compute_issue_record(key, issue, town_lists):
    """
    Everything needed to describe one issue (title, subject, geo, persons,
    origin), without assigning any ID numbers yet.

    key - (volume, paper_no), matching tiff_issues and town_lists.
    Raises ValueError if issue["date"] isn't a real calendar date.
    """
    volume, paper_no = key
    towns = town_lists.get(key, [])
    subject_val, geo_val = build_subject_and_geo(towns)

    issue_num_padded = f"{paper_no:02d}"
    date_long = format_date_long(issue["date"])
    title = (
        f"{NEWSPAPER_NAME} - {date_long} - "
        f"Vol. {issue['volume']} No. {issue_num_padded}"
    )

    return {
        "issue_id": issue["issue_id"],
        "date": issue["date"],
        "year": issue["date"][:4],
        "volume": issue["volume"],
        "paper_no": paper_no,
        "pages": sorted(issue["pages"], key=lambda p: p["page_number"]),
        "title": title,
        "subject": subject_val,
        "geographic_subject": geo_val,
        "persons": build_persons(issue["date"]),
        "origin_information": build_origin_information(issue["date"], NEWSPAPER_NAME),
    }


# =============================================================================
# AUTO-CORRECTING AN INVALID TIFF-FILENAME DATE
# A date like "19110231" is almost always a typo. The two neighboring issues
# (paper_no - 1 and paper_no + 1) usually pin down the real date. Only two
# narrow, confident patterns are applied; anything else stays an invalid_date
# problem for a person to look at.
# =============================================================================

def attempt_date_correction(key, issue, tiff_issues):
    """
    Try to work out the real date behind an issue whose TIFF date didn't
    parse. Looks at paper_no - 1 and paper_no + 1 in the same volume.

      1. Weekly midpoint: if the gap between neighbors is even, the bad date
         is their midpoint.
      2. Transposed month/day: swapping the month and day digits gives a
         valid date strictly between the neighbors.

    Returns (corrected_date_iso, method_label), or (None, None) if neither
    applies.
    """
    volume, paper_no = key
    prev_issue = tiff_issues.get((volume, paper_no - 1))
    next_issue = tiff_issues.get((volume, paper_no + 1))
    if not prev_issue or not next_issue:
        return None, None

    prev_date = parse_iso_date_or_none(prev_issue["date"])
    next_date = parse_iso_date_or_none(next_issue["date"])
    if not prev_date or not next_date or next_date <= prev_date:
        return None, None

    gap_days = (next_date - prev_date).days
    if gap_days > MAX_DATE_CORRECTION_GAP_DAYS:
        return None, None

    # Pattern 1: weekly midpoint.
    if gap_days % 2 == 0:
        midpoint = prev_date + timedelta(days=gap_days // 2)
        return midpoint.strftime("%Y-%m-%d"), "weekly midpoint"

    # Pattern 2: transposed month/day digits.
    bad_text = issue["date"]
    if len(bad_text) == 8 and bad_text.isdigit():
        year_text, month_text, day_text = bad_text[:4], bad_text[4:6], bad_text[6:8]
        swapped_text = f"{year_text}{day_text}{month_text}"
        try:
            swapped_date = datetime.strptime(swapped_text, "%Y%m%d")
        except ValueError:
            swapped_date = None
        if swapped_date and prev_date < swapped_date < next_date:
            return swapped_date.strftime("%Y-%m-%d"), "transposed month/day"

    return None, None


def records_from_single_source(tiff_issues, town_lists, unrecognized_items,
                                source_label, problem_prefix="", town_dates=None,
                                already_ingested_keys=None):
    """
    Turn one (tiff_issues, town_lists) pair into issue records plus problem
    descriptions.

    An issue is written only if it has BOTH a TIFF match and a Town List
    match. Missing either side produces a problem and a pending key, not a
    record, so an incomplete issue waits for a later run.

    already_ingested_keys - (volume, paper_no) keys already written in an
    earlier run. A Town List entry matching one of these is skipped, so a
    fully-used tifflist that has moved out of DataWaiting isn't re-reported
    as missing forever.

    Returns (records, problems, pending_tiff_keys, pending_town_keys,
    corrections).
    """
    records = []
    problems = []
    corrections = []
    pending_tiff_keys = set()
    pending_town_keys = set()
    town_dates = town_dates or {}
    already_ingested_keys = already_ingested_keys or set()

    town_keys = set(town_lists.keys())
    tiff_keys = set(tiff_issues.keys())
    only_in_town_list = town_keys - tiff_keys
    only_in_tiffs = tiff_keys - town_keys

    for key in sorted(only_in_town_list):
        if key in already_ingested_keys:
            continue

        volume, paper_no = key
        # The raw YYYYMMDD digits are what extract_year_from_problem looks
        # for, so the digits go in; the readable date goes alongside for a
        # person reading the report.
        date_iso = town_dates.get(key)
        if date_iso and parse_iso_date_or_none(date_iso):
            raw_digits = date_iso.replace("-", "")
            dated = f" dated {raw_digits} ({format_date_long(date_iso)})"
        elif date_iso:
            dated = f" dated '{date_iso}'"
        else:
            dated = ""
        problems.append(
            f"{problem_prefix}[missing_tiffs] Town List has Vol_{volume} "
            f"paper #{paper_no}{dated} with towns "
            f"({MULTI_SEP.join(town_lists[key])}), but no matching TIFF "
            f"has been found in {source_label} yet - not added to the "
            f"ingest file; will be picked up automatically once a "
            f"matching TIFF shows up."
        )
        pending_town_keys.add(key)

    for item in unrecognized_items:
        problems.append(
            f"{problem_prefix}[unrecognized_filename] '{item}' does not "
            f"match the expected pattern and was skipped."
        )

    for key, issue in tiff_issues.items():
        try:
            record = compute_issue_record(key, issue, town_lists)
        except ValueError:
            original_date = issue["date"]
            corrected_date, method = attempt_date_correction(key, issue, tiff_issues)
            if corrected_date is None:
                problems.append(
                    f"{problem_prefix}[invalid_date] Issue {issue['issue_id']} "
                    f"has an invalid date ('{original_date}') and was "
                    f"skipped - check the source TIFF filename(s) for a typo."
                )
                pending_tiff_keys.add(key)
                continue

            corrected_issue = dict(issue, date=corrected_date)
            try:
                record = compute_issue_record(key, corrected_issue, town_lists)
            except ValueError:
                # Shouldn't happen, but never let it crash the run.
                problems.append(
                    f"{problem_prefix}[invalid_date] Issue {issue['issue_id']} "
                    f"has an invalid date ('{original_date}') and was "
                    f"skipped - check the source TIFF filename(s) for a typo."
                )
                pending_tiff_keys.add(key)
                continue

            corrections.append(
                f"{problem_prefix}Issue {issue['issue_id']} had an invalid "
                f"date ('{original_date}') - corrected to {corrected_date} "
                f"based on the surrounding issues ({method}) and written "
                f"normally."
            )

        if key in only_in_tiffs:
            problems.append(
                f"{problem_prefix}[missing_town_list] Issue "
                f"{record['issue_id']} has no Town List entry yet - not "
                f"added to the ingest file; will be picked up "
                f"automatically once a matching Town List entry shows up."
            )
            pending_tiff_keys.add(key)
            continue

        record["source_volume"] = f"Vol_{key[0]}"
        record["_join_key"] = key  # internal use only
        records.append(record)

    return records, problems, pending_tiff_keys, pending_town_keys, corrections


def gather_all_records(waiting_dir, already_ingested_keys=None):
    """
    Read every tifflist and every Town List in `waiting_dir`, and combine
    them into one pool joined by (volume, paper_no), regardless of which
    file each entry came from.

    Returns (records, problems, tiff_filenames, townlist_filenames,
    file_usable_counts, file_pending, year_to_filenames, corrections).

    file_usable_counts - filename -> number of entries it contributed.
    file_pending       - filenames with at least one entry still waiting on
                         a match (or needing a manual date fix). These stay
                         in DataWaiting for a later run.
    year_to_filenames  - year -> filenames that contributed its records, so
                         a held-back year can keep its sources in DataWaiting.
    corrections        - auto-corrected dates written normally this run.
    """
    tiff_filenames = find_tiff_source_files(waiting_dir)
    townlist_filenames = find_town_list_source_files(waiting_dir)

    all_problems = []
    file_usable_counts = {}

    tiff_key_source = {}
    town_key_source = {}

    # ---- Read every tifflist into one combined pool ----------------------
    all_tiff_issues = {}
    for filename in tiff_filenames:
        path = os.path.join(waiting_dir, filename)
        print(f"Reading tifflist: {filename}")
        try:
            issues, unrecognized = read_tiff_list_file(path)
        except (UnicodeDecodeError, OSError) as e:
            all_problems.append(
                f"[{filename}] [file_read_error] Couldn't read this file "
                f"({e}) - left in DataWaiting for review."
            )
            file_usable_counts[filename] = 0
            continue

        file_usable_counts[filename] = len(issues)

        for key, issue in issues.items():
            if key in all_tiff_issues:
                all_problems.append(
                    f"[{filename}] [duplicate_tiff_entry] Vol_{key[0]} "
                    f"paper #{key[1]} was already read from another "
                    f"tifflist file - keeping the first one seen."
                )
                continue
            all_tiff_issues[key] = issue
            tiff_key_source[key] = filename

        for item in unrecognized:
            all_problems.append(
                f"[{filename}] [unrecognized_filename] '{item}' does not "
                f"match the expected pattern and was skipped."
            )

    # ---- Read every Town List into one combined pool ---------------------
    all_town_lists = {}
    all_town_dates = {}
    for filename in townlist_filenames:
        path = os.path.join(waiting_dir, filename)
        print(f"Reading Town List: {filename}")
        try:
            grid = read_grid(path)
            raw_town_list, raw_town_dates = parse_town_list(grid)
            resolved, resolve_problems = resolve_town_list_volumes(
                raw_town_list, all_tiff_issues, filename_hint=filename
            )
        except (ValueError, OSError, UnicodeDecodeError) as e:
            all_problems.append(
                f"[{filename}] [file_read_error] Couldn't read this file "
                f"({e}) - left in DataWaiting for review."
            )
            file_usable_counts[filename] = 0
            continue

        all_problems.extend(f"[{filename}] {p}" for p in resolve_problems)
        file_usable_counts[filename] = len(resolved)

        for key, towns in resolved.items():
            if key in all_town_lists:
                all_problems.append(
                    f"[{filename}] [duplicate_town_list_entry] "
                    f"Vol_{key[0]} paper #{key[1]} was already read from "
                    f"another Town List file - keeping the first one seen."
                )
                continue
            all_town_lists[key] = towns
            town_key_source[key] = filename
            if key in raw_town_dates:
                all_town_dates[key] = raw_town_dates[key]

    source_label = (
        f"{len(tiff_filenames)} tifflist file(s)" if tiff_filenames
        else "no tifflist files found"
    )
    records, join_problems, pending_tiff_keys, pending_town_keys, corrections = (
        records_from_single_source(
            all_tiff_issues, all_town_lists, [], source_label=source_label,
            town_dates=all_town_dates, already_ingested_keys=already_ingested_keys,
        )
    )
    all_problems.extend(join_problems)

    file_pending = set()
    for key in pending_tiff_keys:
        if key in tiff_key_source:
            file_pending.add(tiff_key_source[key])
    for key in pending_town_keys:
        if key in town_key_source:
            file_pending.add(town_key_source[key])

    year_to_filenames = {}
    for record in records:
        key = record["_join_key"]
        for src in (tiff_key_source.get(key), town_key_source.get(key)):
            if src:
                year_to_filenames.setdefault(record["year"], set()).add(src)

    return (records, all_problems, tiff_filenames, townlist_filenames,
            file_usable_counts, file_pending, year_to_filenames, corrections)
