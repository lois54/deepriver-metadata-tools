#!/usr/bin/env python3
# =============================================================================
# BUILD ISSUE CSV
# =============================================================================
# Generated: 2026-10-17 10:07 PM EDT
# Last modified: 2026-10-19 04:40 PM EDT (years marked ingest_complete are never changed; new data goes to a new part file)
#
# Entry point for the newspaper ingest pipeline. The code lives in the
# newspaper_ingest/ package beside this file. See newspaper_ingest/cli.py for
# the usage modes, README.md for setup, and docs/ for how it behaves.
#
#     python build_issue_csv.py <root_folder>
#     python build_issue_csv.py --by-year <root_folder>
#     python build_issue_csv.py <tiff_dir_or_listing> <townlist_or_sheet_url>
#
# run_from_drive.py calls this file by name, so keep it in the repository root.
# =============================================================================

from newspaper_ingest.cli import main

if __name__ == "__main__":
    main()
