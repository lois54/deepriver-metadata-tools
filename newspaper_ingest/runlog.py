"""
The _Logs folder: the running one-line-per-run log, and the set of problems
from the previous run (used to decide whether anything changed).
"""

import os

from .config import (
    LAST_CORRECTIONS_FILENAME,
    LAST_PROBLEMS_FILENAME,
    LOGS_SUBDIR_NAME,
    RUN_LOG_FILENAME,
)
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


def _state_path(directory, filename):
    return os.path.join(logs_dir_path(directory), filename)


def _read_state_set(directory, filename):
    """The lines of a _Logs state file as a set, or None if it does not exist."""
    path = _state_path(directory, filename)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return {line.rstrip("\n") for line in f if line.strip()}


def _write_state_set(directory, filename, items):
    with open(_state_path(directory, filename), "w", encoding="utf-8") as f:
        for item in sorted(items):
            f.write(item + "\n")


def last_problems_file_exists(directory):
    """True if a previous run has already saved its problem set."""
    return os.path.isfile(_state_path(directory, LAST_PROBLEMS_FILENAME))


def read_last_problems(directory):
    """The set of problem strings recorded at the end of the previous run."""
    return _read_state_set(directory, LAST_PROBLEMS_FILENAME) or set()


def write_last_problems(directory, problems):
    """Save this run's problem set for the next run to compare against."""
    _write_state_set(directory, LAST_PROBLEMS_FILENAME, problems)


def read_last_corrections(directory):
    """
    The auto-corrected-date notes reported by the previous run, or None if no
    run has saved them yet (a folder last run by an older version).
    """
    return _read_state_set(directory, LAST_CORRECTIONS_FILENAME)


def write_last_corrections(directory, corrections):
    """Save this run's correction notes so they are announced only once."""
    _write_state_set(directory, LAST_CORRECTIONS_FILENAME, corrections)
