"""
Problem-message helpers: which year a problem belongs to, how problems are
labelled and grouped for the report and alert email, and which categories
are allowed to hold back a year.
"""

import os

from .patterns import (
    INVALID_DATE_VALUE_PATTERN,
    PROBLEM_CATEGORY_PATTERN,
    PROBLEM_SOURCE_FILE_PATTERN,
    PROBLEM_YEAR_PATTERN,
    SOURCE_LABEL_IN_PROBLEM_PATTERN,
    UNRECOGNIZED_ITEM_PATTERN,
)

# Human-readable labels for the alert email. Unlisted categories print their
# raw [bracket_name].
PROBLEM_CATEGORY_LABELS = {
    "missing_town_list": "missing town list",
    "missing_tiffs": "missing tiffs",
    "invalid_date": "invalid date",
    "duplicate_town_list_entry": "duplicate town list entries",
    "duplicate_tiff_entry": "duplicate tiff entries",
    "unrecognized_filename": "unrecognized filenames",
    "file_read_error": "unreadable files",
    "unresolved_volume": "town list rows with no volume",
}

# Categories listed under "Needs a look" in the alert email, rather than
# folded into a count. These are one-off problems where the exact detail
# matters. A category with only a few problems is printed in full; one with
# more than VERBATIM_FULL_LIMIT is summarized (a count, grouped by type, with
# an example), so one bad tifflist cannot fill the email with hundreds of
# lines. The merge report always keeps the full list.
PROBLEM_CATEGORY_VERBATIM = {"file_read_error", "unrecognized_filename"}

# Most problems of one verbatim category that are still printed line by line.
VERBATIM_FULL_LIMIT = 3

# Most lines shown in any per-year section of the email before the rest are
# collapsed into one "and N more" line.
EMAIL_SECTION_LINE_LIMIT = 10

# Most bad dates listed in parentheses after an "invalid date" count.
INVALID_DATE_LIST_LIMIT = 3

# Categories that may show a year for grouping, but never hold that year
# back. "Waiting for a match that hasn't arrived yet" is a normal state while
# contributor files trickle in, not an error.
PROBLEM_CATEGORIES_NEVER_BLOCK = {"missing_tiffs", "unrecognized_filename"}


def extract_year_from_problem(problem_text):
    """
    The 4-digit year from a TIFF-derived date in a problem message, or None
    if the message has no such date (e.g. a missing Town List entry with no
    TIFF yet).
    """
    match = PROBLEM_YEAR_PATTERN.search(problem_text)
    return match.group(1) if match else None


def problem_category(problem_text):
    """The [category] tag of a problem message, or 'other' if none."""
    match = PROBLEM_CATEGORY_PATTERN.search(problem_text)
    return match.group(1) if match else "other"


def normalize_problem_for_compare(problem_text):
    """
    The form of a problem message used to decide whether the problem is the
    SAME one as last run's. Everything that identifies the problem (category,
    issue, file, date) is kept. The one volatile part is dropped: a
    'missing tiffs' message says how many tifflist files were searched, and
    that number changes whenever a finished tifflist moves to
    DataFilesCompleted. Without this, every missing-tiffs problem would look
    resolved-and-new on the next run and trigger an email.
    """
    return SOURCE_LABEL_IN_PROBLEM_PATTERN.sub("has been found yet", problem_text)


def group_problems(problems):
    """
    Sort problem strings into the buckets the alert email summarizes from.

    Returns (by_year_category, invalid_dates_by_year, aggregate_by_category,
    verbatim_counts):
        by_year_category      - year -> {category: count}
        invalid_dates_by_year - year -> [bad date strings]
        aggregate_by_category - category -> count, for problems with no year
        verbatim_counts       - category -> count, for PROBLEM_CATEGORY_VERBATIM
    """
    by_year_category = {}
    invalid_dates_by_year = {}
    aggregate_by_category = {}
    verbatim_counts = {}

    for p in problems:
        category = problem_category(p)

        if category in PROBLEM_CATEGORY_VERBATIM:
            verbatim_counts[category] = verbatim_counts.get(category, 0) + 1
            continue

        year = extract_year_from_problem(p)
        if year:
            year_counts = by_year_category.setdefault(year, {})
            year_counts[category] = year_counts.get(category, 0) + 1
            if category == "invalid_date":
                date_match = INVALID_DATE_VALUE_PATTERN.search(p)
                if date_match:
                    invalid_dates_by_year.setdefault(year, []).append(date_match.group(1))
        else:
            aggregate_by_category[category] = aggregate_by_category.get(category, 0) + 1

    return by_year_category, invalid_dates_by_year, aggregate_by_category, verbatim_counts


def format_date_list(dates, limit=INVALID_DATE_LIST_LIMIT):
    """
    "'19110231', '19110230', '19110229'" for a few dates, or the first few
    followed by "and 4 more" when there are many.
    """
    dates = sorted(set(dates))
    shown = ", ".join(f"'{d}'" for d in dates[:limit])
    if len(dates) > limit:
        shown += f" and {len(dates) - limit} more"
    return shown


def format_year_problem_line(year, category_counts, invalid_dates=()):
    """
    One line summarizing a year's problems:
        '  1911: 2 invalid date ('19110231', '19110230'); 1 missing town list'
    """
    parts = []
    for category in sorted(category_counts):
        count = category_counts[category]
        label = PROBLEM_CATEGORY_LABELS.get(category, category)
        if category == "invalid_date" and invalid_dates:
            parts.append(f"{count} {label} ({format_date_list(invalid_dates)})")
        else:
            parts.append(f"{count} {label}")
    return f"  {year}: " + "; ".join(parts)


def cap_lines(lines, limit=EMAIL_SECTION_LINE_LIMIT, noun="more",
              pointer=" (see the full report)"):
    """
    Keep a section from running to dozens of lines: show the first `limit`
    and replace the rest with one '... and N more <noun>' line, followed by
    `pointer` (pass '' where the full report does not list the items).
    Returns the list unchanged when it is short enough.
    """
    if len(lines) <= limit:
        return list(lines)
    hidden = len(lines) - limit
    return list(lines[:limit]) + [f"  ... and {hidden} more {noun}{pointer}"]


def _unrecognized_name_and_source(problem_text):
    """(skipped name, source file or None) from an unrecognized_filename message."""
    name_match = UNRECOGNIZED_ITEM_PATTERN.search(problem_text)
    source_match = PROBLEM_SOURCE_FILE_PATTERN.match(problem_text)
    name = name_match.group(1) if name_match else None
    source = source_match.group(1) if source_match else None
    return name, source


def _summarize_unrecognized(problems):
    """
    Summary lines for a long run of unrecognized_filename problems: the total,
    then one line per file type (.pdf, .txt, ...) with its count and one
    example, so a tifflist full of PDF names becomes two or three lines.
    """
    groups = {}  # extension -> list of (name, source)
    for p in sorted(problems):
        name, source = _unrecognized_name_and_source(p)
        if name is None:
            ext = "(unreadable message)"
        else:
            ext = os.path.splitext(name)[1].lower() or "(no extension)"
        groups.setdefault(ext, []).append((name, source))

    sources = {s for items in groups.values() for _, s in items if s}
    lines = [f"  {len(problems)} skipped names did not match the expected pattern, by type:"]
    for ext in sorted(groups, key=lambda e: (-len(groups[e]), e)):
        items = groups[ext]
        name, source = items[0]
        if name is None:
            example = ""
        elif source:
            example = f"  (for example '{name}' in {source})"
        else:
            example = f"  (for example '{name}')"
        # A listing made by dumping a folder often includes its own filename.
        # Say so, since those are harmless and easy to mistake for a real problem.
        self_listed = sum(1 for n, s in items if n and s and n.lower() == s.lower())
        if self_listed == len(items):
            example += "  - each is the listing file's own name"
        elif self_listed:
            example += f"  - {self_listed} of these are a listing file's own name"
        lines.append(f"    {ext}: {len(items)}{example}")
    if len(sources) > 1:
        lines.append(f"    spread across {len(sources)} files")
    return lines


def summarize_verbatim_problems(problems, full_limit=VERBATIM_FULL_LIMIT):
    """
    The 'Needs a look' lines for the alert email.

    A category with up to `full_limit` problems is printed line by line, in
    full. A longer one is summarized: unrecognized filenames are grouped by
    file type with a count and an example each; any other verbatim category
    gets a count and its first message as an example. Returns a list of lines,
    empty when there is nothing in a verbatim category.
    """
    by_category = {}
    for p in problems:
        category = problem_category(p)
        if category in PROBLEM_CATEGORY_VERBATIM:
            by_category.setdefault(category, []).append(p)

    lines = []
    for category in sorted(by_category):
        items = sorted(by_category[category])
        if len(items) <= full_limit:
            lines.extend(f"  - {p}" for p in items)
        elif category == "unrecognized_filename":
            lines.extend(_summarize_unrecognized(items))
        else:
            label = PROBLEM_CATEGORY_LABELS.get(category, category)
            lines.append(f"  {len(items)} {label} problems. For example:")
            lines.append(f"    {items[0]}")
    return lines


def format_problem_summary_lines(problems, verbatim_as_lines=False):
    """
    The per-year 'N category; M category' summary lines, used for the
    resolved-problems section of the alert email. Returns a list of lines
    (empty if there is nothing to report). A long per-year list is capped.

    verbatim_as_lines - True to list verbatim-category problems the way
    'Needs a look' does (in full when few, summarized when many); False to
    fold them into a count.
    """
    by_year_category, invalid_dates_by_year, aggregate_by_category, verbatim_counts = (
        group_problems(problems)
    )

    year_lines = [
        format_year_problem_line(year, by_year_category[year],
                                 invalid_dates_by_year.get(year, ()))
        for year in sorted(by_year_category)
    ]
    lines = cap_lines(year_lines, noun="years", pointer="")

    for category in sorted(aggregate_by_category):
        label = PROBLEM_CATEGORY_LABELS.get(category, category)
        lines.append(f"  {aggregate_by_category[category]} {label} (no year yet)")

    if verbatim_as_lines:
        lines.extend(summarize_verbatim_problems(problems))
    elif verbatim_counts:
        for category in sorted(verbatim_counts):
            label = PROBLEM_CATEGORY_LABELS.get(category, category)
            lines.append(f"  {verbatim_counts[category]} {label}")

    return lines
