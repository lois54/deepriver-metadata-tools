"""
The merge engine: takes the issue records gathered from DataWaiting, merges
them into the per-year IngestFiles folders, writes the merge report when
anything is noteworthy, and sends the alert email when the problem set has
changed.
"""

import csv
import os

from .alerts import build_alert_email, send_error_email
from .config import (
    INGEST_FILES_SUBDIR,
    MERGE_REPORTS_SUBDIR,
    DATA_WAITING_SUBDIR,
    TARGET_LINES_PER_FILE,
    COLUMNS,
)
from .folders import ensure_subdir
from .ingest_files import find_year_ingest_files, make_year_ingest_filename, write_matching_xlsx
from .ingest_rows import (
    build_parent_row_dict,
    chunk_records_by_line_limit,
    normalize_for_compare,
    rows_from_issue_record,
)
from .problems import PROBLEM_CATEGORIES_NEVER_BLOCK, extract_year_from_problem, problem_category
from .runlog import append_run_log, read_last_problems, write_last_problems
from .timeutil import format_eastern_timestamp, now_eastern


def merge_and_write_records(log_root, ingest_dir, reports_dir, all_records,
                             volume_problems, source_line, corrections=()):
    """
    Merge issue records into ingest_dir/<year>/ and report on the run.

    ORGANIZED BY YEAR: records are grouped by calendar year, one folder per
    year under ingest_dir.

    HOLD-BACK: a year with a problem pinned to it (see
    extract_year_from_problem) is held back entirely this run. None of its
    new issues are written, even clean ones, so a year is only ever added to
    in complete batches. Problems in PROBLEM_CATEGORIES_NEVER_BLOCK never
    hold back a year.

    Nothing is lost by holding a year back. The records are recomputed from
    DataWaiting every run, so the held-back issues are retried next time.

    log_root    - root folder that _Logs lives under
    ingest_dir   - IngestFiles root; year subfolders go directly under it
    reports_dir  - where Ingest_merge_report_<timestamp>.txt is written
    all_records  - issue records from gather_all_records
    volume_problems - problem strings from gathering
    source_line  - a line describing the sources, for the report
    corrections  - auto-corrected dates, from gather_all_records

    Returns blocked_years, the set of years held back this run.
    """
    current_problems = set(volume_problems)
    blocked_years = set()
    for p in current_problems:
        if problem_category(p) in PROBLEM_CATEGORIES_NEVER_BLOCK:
            continue
        year = extract_year_from_problem(p)
        if year:
            blocked_years.add(year)

    records_by_year = {}
    for record in all_records:
        records_by_year.setdefault(record["year"], []).append(record)

    all_years = sorted(set(records_by_year) | blocked_years)

    # ---- Per-year merge loop ---------------------------------------------
    matched_count = 0
    mismatch_lines = []
    counts_by_source = {}
    held_back_counts = {}  # year -> count of matched-but-withheld issues
    written_files = []
    added_total = 0
    new_pages_total = 0
    matched_pages_total = 0
    mismatch_pages_total = 0
    new_summary_by_year = {}  # year -> {count, pages, min_date, max_date}

    def bump(source_volume, outcome, page_count):
        entry = counts_by_source.setdefault(
            source_volume,
            {"new": 0, "matched": 0, "mismatch": 0,
             "new_pages": 0, "matched_pages": 0, "mismatch_pages": 0},
        )
        entry[outcome] += 1
        entry[f"{outcome}_pages"] += page_count

    for year in all_years:
        is_blocked = year in blocked_years
        year_dir = os.path.join(ingest_dir, year)
        existing_files = find_year_ingest_files(year_dir) if os.path.isdir(year_dir) else []
        existing_by_id = {}
        for info in existing_files:
            for row in info["rows"]:
                if row.get("model") == "Publication Issue" and row.get("local_identifier"):
                    existing_by_id[row["local_identifier"]] = row

        year_new_records = []
        for record in sorted(records_by_year.get(year, []), key=lambda r: r["date"]):
            issue_id = record["issue_id"]
            page_count = len(record["pages"])

            if issue_id in existing_by_id:
                new_parent = normalize_for_compare(build_parent_row_dict(record))
                old_parent = normalize_for_compare(existing_by_id[issue_id])
                if new_parent == old_parent:
                    matched_count += 1
                    matched_pages_total += page_count
                    bump(record["source_volume"], "matched", page_count)
                else:
                    mismatch_lines.append(
                        f"  - {issue_id} ({record['source_volume']}) already "
                        f"exists but the new data differs. NOT overwritten - "
                        f"please review manually."
                    )
                    mismatch_pages_total += page_count
                    bump(record["source_volume"], "mismatch", page_count)
                continue

            if is_blocked:
                held_back_counts[year] = held_back_counts.get(year, 0) + 1
                continue  # not written this run

            year_new_records.append(record)
            bump(record["source_volume"], "new", page_count)
            new_pages_total += page_count

        if year_new_records:
            dates = [r["date"] for r in year_new_records]
            new_summary_by_year[year] = {
                "count": len(year_new_records),
                "pages": sum(len(r["pages"]) for r in year_new_records),
                "min_date": min(dates),
                "max_date": max(dates),
            }

        if not year_new_records:
            continue

        year_dir = ensure_subdir(ingest_dir, year)
        taken_names = {info["filename"] for info in existing_files}
        active_file = existing_files[-1] if existing_files else None
        can_continue = (
            active_file is not None
            and 1 + len(active_file["rows"]) < TARGET_LINES_PER_FILE
        )
        start_line_count = 1 + len(active_file["rows"]) if can_continue else 1
        chunks = chunk_records_by_line_limit(
            year_new_records, start_line_count=start_line_count
        )

        for i, chunk in enumerate(chunks):
            chunk_rows_out = []

            if i == 0 and can_continue:
                # Continue the existing active file in place.
                existing_rows = active_file["rows"]
                next_id = (
                    max(int(r["ID"]) for r in existing_rows if r.get("ID")) + 1
                    if existing_rows else 1
                )
                for record in chunk:
                    rows, next_id = rows_from_issue_record(record, next_id)
                    chunk_rows_out.extend(rows)

                with open(active_file["path"], "a", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=COLUMNS)
                    writer.writerows(chunk_rows_out)

                written_files.append(active_file["path"])
                taken_names.add(active_file["filename"])

            else:
                # A brand-new file for this year.
                next_id = 1
                for record in chunk:
                    rows, next_id = rows_from_issue_record(record, next_id)
                    chunk_rows_out.extend(rows)

                filename = make_year_ingest_filename(year_dir, year, taken_names)
                path = os.path.join(year_dir, filename)

                with open(path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=COLUMNS)
                    writer.writeheader()
                    writer.writerows(chunk_rows_out)

                taken_names.add(filename)
                written_files.append(path)

            added_total += len(chunk)

    for path in written_files:
        write_matching_xlsx(path)

    # ---- Decide whether this run is worth a full report -------------------
    previous_problems = read_last_problems(log_root)
    problems_changed = current_problems != previous_problems
    noteworthy = (
        bool(added_total) or bool(mismatch_lines) or problems_changed
        or bool(corrections)
    )

    report_path = None
    if noteworthy:
        run_moment = now_eastern()
        timestamp = run_moment.strftime("%Y%m%d_%H%M%S")
        report_path = os.path.join(reports_dir, f"Ingest_merge_report_{timestamp}.txt")

        lines = [
            "Ingest merge report",
            f"Run at: {format_eastern_timestamp(run_moment)}",
            f"Root directory: {log_root}",
            f"Input files read from: {DATA_WAITING_SUBDIR}/",
            f"Ingest files written to: {ingest_dir} (one subfolder per year)",
            source_line,
            "",
            f"New issues added: {added_total} ({new_pages_total} pages)",
            f"Already present (unchanged): {matched_count} ({matched_pages_total} pages)",
            f"Duplicates with differing data (needs review): {len(mismatch_lines)} ({mismatch_pages_total} pages)",
            "",
        ]

        if counts_by_source:
            lines.append("Breakdown by source:")
            for source in sorted(counts_by_source):
                c = counts_by_source[source]
                lines.append(
                    f"  - {source}: {c['new']} new ({c['new_pages']} pages), "
                    f"{c['matched']} already present ({c['matched_pages']} pages), "
                    f"{c['mismatch']} differing ({c['mismatch_pages']} pages)"
                )
            lines.append("")

        if written_files:
            lines.append("Files written/updated:")
            lines.extend(f"  - {path}" for path in written_files)
            lines.append("")

        if held_back_counts:
            lines.append(
                "YEARS HELD BACK THIS RUN (issue(s) matched but not written "
                "- see problems below):"
            )
            for year in sorted(held_back_counts):
                lines.append(f"  - {year}: {held_back_counts[year]} issue(s) waiting")
            lines.append("")

        if corrections:
            lines.append("DATES AUTO-CORRECTED THIS RUN:")
            lines.extend(f"  - {c}" for c in corrections)
            lines.append("")

        if mismatch_lines:
            lines.append("DUPLICATES WITH DIFFERING DATA:")
            lines.extend(mismatch_lines)
            lines.append("")

        if volume_problems:
            lines.append("OTHER PROBLEMS (from reading the source files):")
            lines.extend(f"  - {p}" for p in volume_problems)
            lines.append("")

        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    # Saved every run, so the next run has something current to compare against.
    write_last_problems(log_root, current_problems)

    # ---- Alert email, only when the problem picture changed ---------------
    if problems_changed or corrections:
        resolved_problems = previous_problems - current_problems
        report_label = (
            f"/{MERGE_REPORTS_SUBDIR}/{os.path.basename(report_path)}"
            if report_path else None
        )
        ingest_dir_label = (
            f"{os.path.basename(ingest_dir.rstrip(os.sep)) or INGEST_FILES_SUBDIR}/ "
            f"(one subfolder per year)"
        )
        subject, body = build_alert_email(
            current_problems, resolved_problems, blocked_years,
            new_summary_by_year, report_label, DATA_WAITING_SUBDIR,
            ingest_dir_label, source_line, corrections,
        )
        send_error_email(subject, body)

    summary = (
        f"new={added_total} matched={matched_count} "
        f"differing={len(mismatch_lines)} problems={len(current_problems)} "
        f"held_back_years={len(blocked_years)}"
    )
    if report_path:
        append_run_log(log_root, f"{summary} -> {os.path.basename(report_path)}")
    else:
        append_run_log(log_root, f"{summary} -> nothing new since last run, no report written")

    print()
    print("Done!")
    print(f"  New issues added: {added_total} ({new_pages_total} pages)")
    print(f"  Already present (unchanged): {matched_count} ({matched_pages_total} pages)")
    print(f"  Duplicates with differing data: {len(mismatch_lines)} ({mismatch_pages_total} pages)")
    if counts_by_source:
        print("  Breakdown by source:")
        for source in sorted(counts_by_source):
            c = counts_by_source[source]
            print(f"    - {source}: {c['new']} new ({c['new_pages']} pages), "
                  f"{c['matched']} already present ({c['matched_pages']} pages), "
                  f"{c['mismatch']} differing ({c['mismatch_pages']} pages)")
    print()
    if written_files:
        print("  Files written/updated:")
        for path in written_files:
            print(f"    - {path}")
    if held_back_counts:
        print("  Years held back this run (pending a fix):")
        for year in sorted(held_back_counts):
            print(f"    - {year}: {held_back_counts[year]} issue(s) waiting")
    if report_path:
        print(f"  Process report: {report_path}")
    else:
        print("  Nothing new since last run - no report file written "
              f"(see _Logs/run_log.txt for a record of this run).")

    return blocked_years
