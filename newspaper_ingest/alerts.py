"""
The alert email: the short summary sent whenever this run's problem picture
changed, and the SMTP sender that delivers it.
"""

import os
import smtplib
from email.mime.text import MIMEText

from .config import EMAIL_RECIPIENTS, EMAIL_SENDER
from .problems import (
    EMAIL_SECTION_LINE_LIMIT,
    PROBLEM_CATEGORY_LABELS,
    cap_lines,
    format_problem_summary_lines,
    format_year_problem_line,
    group_problems,
    summarize_verbatim_problems,
)
from .timeutil import format_date_long, format_eastern_timestamp


def build_alert_email(current_problems, resolved_problems, blocked_years,
                       new_summary_by_year, report_path, waiting_subdir,
                       ingest_dir_label, source_line, corrections=(),
                       complete_year_notices=()):
    """
    Build (subject, body) for the alert email.

    Short by design. Every section that could run to many lines is capped:
      - one line per year (new issues, problems), first 10 shown, the rest
        folded into one "and N more years" line
      - one-off problems under "Needs a look": printed in full when there
        are 3 or fewer of a kind, otherwise summarized as a count per file
        type with an example
      - auto-corrected dates: first 5 shown, the rest folded into a count
    Resolved problems get counts only. The merge report named at the bottom
    always has the full detail.

    new_summary_by_year - {year: {count, pages, min_date, max_date}} for the
    issues actually written this run.
    corrections - notes on dates that were auto-corrected this run.
    complete_year_notices - one note per year marked ingest_complete that had
    new issues found this run (written to a new numbered file).
    """
    lines = [
        f"Run at: {format_eastern_timestamp()}",
        f"Input files read from: {waiting_subdir}/",
        f"Ingest files written to: {ingest_dir_label}",
        source_line,
        "",
    ]

    if new_summary_by_year:
        lines.append("New issues added:")
        year_lines = []
        for year in sorted(new_summary_by_year):
            s = new_summary_by_year[year]
            noun = "issue" if s["count"] == 1 else "issues"
            date_range = (
                f"{format_date_long(s['min_date'])} thru {format_date_long(s['max_date'])}"
            )
            year_lines.append(f"  {year}: {s['count']} {noun} ({s['pages']} pages), {date_range}")
        lines.extend(cap_lines(year_lines, noun="years"))
    else:
        lines.append("No issues added this run")
    lines.append("")

    by_year_category, invalid_dates_by_year, aggregate_by_category, verbatim_counts = (
        group_problems(current_problems)
    )

    if by_year_category:
        lines.append("Problems by year:")
        year_lines = [
            format_year_problem_line(year, by_year_category[year],
                                     invalid_dates_by_year.get(year, ()))
            for year in sorted(by_year_category)
        ]
        lines.extend(cap_lines(year_lines, noun="years"))
        lines.append("")

    if aggregate_by_category:
        lines.append("Problems not tied to a specific year yet:")
        for category in sorted(aggregate_by_category):
            label = PROBLEM_CATEGORY_LABELS.get(category, category)
            lines.append(f"  {aggregate_by_category[category]} {label}")
        lines.append("")

    if verbatim_counts:
        lines.append("Needs a look:")
        lines.extend(summarize_verbatim_problems(current_problems))
        lines.append("")

    if blocked_years:
        noun = "year" if len(blocked_years) == 1 else "years"
        lines.append(
            f"{len(blocked_years)} {noun} held back until fixed: "
            f"{', '.join(sorted(blocked_years))}"
        )
        lines.append("")

    resolved_summary = format_problem_summary_lines(resolved_problems, verbatim_as_lines=False)
    if resolved_summary:
        lines.append(f"RESOLVED since the last run ({len(resolved_problems)} total):")
        lines.extend(resolved_summary)
        lines.append("")

    if corrections:
        noun = "date" if len(corrections) == 1 else "dates"
        lines.append(f"Auto-corrected {noun} this run:")
        lines.extend(cap_lines([f"  - {c}" for c in corrections], limit=5, noun="corrections"))
        lines.append("")

    if complete_year_notices:
        lines.append("NEW DATA FOUND FOR YEARS MARKED ingest_complete:")
        lines.extend(cap_lines([f"  - {n}" for n in complete_year_notices],
                               limit=EMAIL_SECTION_LINE_LIMIT, noun="more years"))
        lines.append("")

    if report_path:
        lines.append(f"Full report: {report_path}")

    if blocked_years:
        noun = "year" if len(blocked_years) == 1 else "years"
        subject = f"Newspaper pipeline: {len(blocked_years)} {noun} held back"
    elif complete_year_notices:
        subject = "Newspaper pipeline: new data found for a year marked ingest_complete"
    elif current_problems:
        subject = "Newspaper pipeline: problems to review (nothing held back)"
    elif corrections:
        noun = "date" if len(corrections) == 1 else "dates"
        subject = f"Newspaper pipeline: all clear ({len(corrections)} {noun} auto-corrected)"
    else:
        subject = "Newspaper pipeline: all clear"

    return subject, "\n".join(lines) + "\n"


def send_error_email(subject, body):
    """
    Email EMAIL_RECIPIENTS via Gmail SMTP, using the app password in the
    EMAIL_APP_PASSWORD environment variable.

    Never raises. If the password is missing or sending fails, a warning is
    printed and the run continues.
    """
    app_password = os.environ.get("EMAIL_APP_PASSWORD")
    if not app_password:
        print("  (EMAIL_APP_PASSWORD not set - skipping alert email)")
        return

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = EMAIL_SENDER
    msg["To"] = ", ".join(EMAIL_RECIPIENTS)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_SENDER, app_password)
            server.sendmail(EMAIL_SENDER, EMAIL_RECIPIENTS, msg.as_string())
        print(f"  alert email sent to {', '.join(EMAIL_RECIPIENTS)}")
    except Exception as e:
        print(f"  WARNING: couldn't send alert email ({e}) - continuing anyway.")
