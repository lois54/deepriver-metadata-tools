"""
Command-line entry point logic.

    python build_issue_csv.py <root_folder>
        Default: the four-folder layout (DataWaiting, DataFilesCompleted,
        IngestFiles, MergeReports, plus _Logs at the root). Reads everything
        in DataWaiting and merges it into IngestFiles/<year>/.

    python build_issue_csv.py --by-year <root_folder>
        The same as the default.

    python build_issue_csv.py <tiff_dir_or_listing_file> <townlist_file_or_sheet_url>
        Manual single-pair mode, for one-off files that don't follow the
        DataWaiting naming convention. Output goes into the same folder.

Requires openpyxl only if a Town List is an .xlsx file.
"""

import os
import sys

from .config import (
    DATA_COMPLETED_SUBDIR,
    DATA_WAITING_SUBDIR,
    INGEST_FILES_SUBDIR,
    MERGE_REPORTS_SUBDIR,
)
from .folders import ensure_subdir, move_processed_input_files
from .ingest_files import scan_existing_issue_keys
from .merge import merge_and_write_records
from .notes import load_notes
from .records import gather_all_records, records_from_single_source
from .runlog import append_run_log
from .tiffs import read_tiff_list_file, scan_tiff_directory
from .townlist import is_google_sheets_url, parse_town_list, read_grid, resolve_town_list_volumes


def run_by_year(directory):
    """
    Default mode: read every tifflist and Town List in DataWaiting/ and merge
    them. See the package docstring and merge_and_write_records for the rules.
    """
    waiting_dir = ensure_subdir(directory, DATA_WAITING_SUBDIR)
    completed_dir = ensure_subdir(directory, DATA_COMPLETED_SUBDIR)
    ingest_dir = ensure_subdir(directory, INGEST_FILES_SUBDIR)
    reports_dir = ensure_subdir(directory, MERGE_REPORTS_SUBDIR)

    already_ingested_keys = scan_existing_issue_keys(ingest_dir)

    print(f"Scanning {waiting_dir} for tifflist and Town List files...")
    (all_records, problems, tiff_filenames, townlist_filenames,
     file_usable_counts, file_pending, year_to_filenames, corrections) = (
        gather_all_records(waiting_dir, already_ingested_keys=already_ingested_keys)
    )

    if not tiff_filenames and not townlist_filenames:
        print("No tifflist or Town List files found.")
        append_run_log(directory, "no tifflist or Town List files found in this run")
        return

    print(f"Found {len(tiff_filenames)} tifflist file(s) and "
          f"{len(townlist_filenames)} Town List file(s).")
    print()

    source_line = (
        f"Tifflist files read: {', '.join(tiff_filenames) or '(none)'}\n"
        f"Town List files read: {', '.join(townlist_filenames) or '(none)'}"
    )
    blocked_years = merge_and_write_records(
        directory, ingest_dir, reports_dir, all_records, problems, source_line,
        corrections,
    )

    # A file whose year was held back this run stays in DataWaiting too,
    # since its data wasn't actually written.
    for year in blocked_years:
        file_pending.update(year_to_filenames.get(year, set()))

    move_processed_input_files(
        waiting_dir, completed_dir, tiff_filenames + townlist_filenames,
        file_usable_counts, file_pending, directory,
    )


def run_manual(tiff_source, townlist_file):
    """Manual single-pair mode: one TIFF source and one Town List."""
    if os.path.isdir(tiff_source):
        print(f"Scanning TIFF directory: {tiff_source}")
        tiff_issues, unrecognized_items = scan_tiff_directory(tiff_source)
        output_dir = tiff_source
        source_label = f"the '{tiff_source}' directory"

    elif os.path.isfile(tiff_source):
        print(f"Reading TIFF filenames from listing file: {tiff_source}")
        tiff_issues, unrecognized_items = read_tiff_list_file(tiff_source)
        output_dir = os.path.dirname(os.path.abspath(tiff_source)) or "."
        source_label = f"the '{tiff_source}' listing file"

    else:
        print(f"ERROR: '{tiff_source}' is not a directory or a file.")
        sys.exit(1)

    print(f"  Found {len(tiff_issues)} issue(s) worth of TIFF pages.")
    if unrecognized_items:
        noun = "entry" if len(unrecognized_items) == 1 else "entries"
        print(f"  ({len(unrecognized_items)} {noun} didn't match the expected "
              f"naming pattern and will be skipped - see the process report.)")

    print(f"Reading Town List: {townlist_file}")
    grid = read_grid(townlist_file)
    raw_town_lists, town_dates = parse_town_list(grid)
    town_lists, resolve_problems = resolve_town_list_volumes(
        raw_town_lists, tiff_issues, filename_hint=os.path.basename(townlist_file)
    )
    print(f"  Found {len(town_lists)} issue(s) in the Town List.")

    print("Merging into output files...")
    records, problems, _pending_tiff, _pending_town, corrections = (
        records_from_single_source(
            tiff_issues, town_lists, unrecognized_items, source_label=source_label,
            town_dates=town_dates,
            already_ingested_keys=scan_existing_issue_keys(output_dir),
        )
    )
    problems.extend(f"[{townlist_file}] {p}" for p in resolve_problems)
    source_line = f"Source: {tiff_source} + {townlist_file}"
    # Manual mode has no folder split: everything goes in output_dir.
    merge_and_write_records(output_dir, output_dir, output_dir, records,
                             problems, source_line, corrections)


def main(argv=None):
    args = sys.argv[1:] if argv is None else list(argv)

    try:
        load_notes()
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    directory = None
    if len(args) == 1 and os.path.isdir(args[0]):
        directory = args[0]
    elif len(args) == 2 and args[0] == "--by-year":
        directory = args[1]
        if not os.path.isdir(directory):
            print(f"ERROR: '{directory}' is not a directory.")
            sys.exit(1)

    if directory is not None:
        run_by_year(directory)
        return

    if len(args) != 2:
        print("Usage:")
        print("  python build_issue_csv.py <directory>")
        print("      (default: read every tifflist and Town List in <directory> and merge them)")
        print("  python build_issue_csv.py <tiff_directory_or_listing_file> <townlist_file_or_google_sheet_url>")
        print("      (manual mode, for one-off files that don't follow the naming convention)")
        sys.exit(1)

    tiff_source, townlist_file = args

    # A Google Sheets URL isn't a path on disk, so only check local files.
    if not is_google_sheets_url(townlist_file) and not os.path.isfile(townlist_file):
        print(f"ERROR: Town List file not found: {townlist_file}")
        sys.exit(1)

    run_manual(tiff_source, townlist_file)
