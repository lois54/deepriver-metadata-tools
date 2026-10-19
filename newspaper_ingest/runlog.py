"""
The _Logs folder: the running one-line-per-run log, and the set of problems
from the previous run (used to decide whether anything changed).
"""

import os

from .config import LAST_PROBLEMS_FILENAME, LOGS_SUBDIR_NAME, RUN_LOG_FILENAME
from .timeutil import format_eastern_timestamp


def logs_dir_path(directory):
    """
    The _Logs subfolder under `directory`, created if needed. It's a real
    subfolder so the bookkeeping files stay out of the main listing.
    """
    path = os.path.join(directory, LOGS_SUBDIR_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def append_run_log(directory, message):
    """Append one timestamped line to _Logs/run_log.txt."""
    log_path = os.path.join(logs_dir_path(directory), RUN_LOG_FILENAME)
    timestamp = format_eastern_timestamp()
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"{timestamp}  {message}\n")


def read_last_problems(directory):
    """The set of problem strings recorded at the end of the previous run."""
    path = os.path.join(logs_dir_path(directory), LAST_PROBLEMS_FILENAME)
    if not os.path.isfile(path):
        return set()
    with open(path, "r", encoding="utf-8") as f:
        return {line.rstrip("\n") for line in f if line.strip()}


def write_last_problems(directory, problems):
    """Save this run's problem set for the next run to compare against."""
    path = os.path.join(logs_dir_path(directory), LAST_PROBLEMS_FILENAME)
    with open(path, "w", encoding="utf-8") as f:
        for p in sorted(problems):
            f.write(p + "\n")
