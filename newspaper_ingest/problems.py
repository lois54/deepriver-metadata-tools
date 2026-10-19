"""
Problem-message helpers: which year a problem belongs to, how problems are
labelled and grouped for the report and alert email, and which categories
are allowed to hold back a year.
"""

from .patterns import (
    INVALID_DATE_VALUE_PATTERN,
    PROBLEM_CATEGORY_PATTERN,
    PROBLEM_YEAR_PATTERN,
)

# Human-readable labels for the alert email. Unlisted categories print their
# raw [bracket_name].
PROBLEM_CATEGORY_LABELS = {
    "missing_town_list": "missing town list",
    "missing_tiffs": "missing tiffs",
    "invalid_date": "invalid date",
    "duplicate_town_list_entry": "duplicate town list entries",
    "duplicate_tiff_entry": "duplicate tiff entries",
}

# Categories printed in full under "Needs a look" in the alert email, rather
# than folded into a count. These are rare one-off problems where the exact
# detail matters more than a tally.
PROBLEM_CATEGORY_VERBATIM = {"file_read_error", "unrecognized_filename"}

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


def format_problem_summary_lines(problems, verbatim_as_lines=False):
    """
    The per-year 'N category; M category' summary lines, used for the
    resolved-problems section of the alert email. Returns a list of lines
    (empty if there is nothing to report).

    verbatim_as_lines - True to print verbatim-category problems in full;
    False to fold them into a count.
    """
    by_year_category, invalid_dates_by_year, aggregate_by_category, verbatim_counts = (
        group_problems(problems)
    )
    lines = []

    for year in sorted(by_year_category):
        parts = []
        for category in sorted(by_year_category[year]):
            count = by_year_category[year][category]
            label = PROBLEM_CATEGORY_LABELS.get(category, category)
            if category == "invalid_date" and invalid_dates_by_year.get(year):
                dates_str = ", ".join(f"'{d}'" for d in invalid_dates_by_year[year])
                parts.append(f"{count} {label} ({dates_str})")
            else:
                parts.append(f"{count} {label}")
        lines.append(f"  {year}: " + "; ".join(parts))

    for category in sorted(aggregate_by_category):
        label = PROBLEM_CATEGORY_LABELS.get(category, category)
        lines.append(f"  {aggregate_by_category[category]} {label} (no year yet)")

    if verbatim_as_lines:
        for p in sorted(problems):
            if problem_category(p) in PROBLEM_CATEGORY_VERBATIM:
                lines.append(f"  - {p}")
    elif verbatim_counts:
        for category in sorted(verbatim_counts):
            label = PROBLEM_CATEGORY_LABELS.get(category, category)
            lines.append(f"  {verbatim_counts[category]} {label}")

    return lines
