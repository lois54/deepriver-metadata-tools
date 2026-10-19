"""
The fixed credits block for the notes column, loaded from notes_config.txt.

The file lives next to build_issue_csv.py (the repository root, one level
above this package), so it can be edited directly without touching code.
"""

import os

from .config import MULTI_SEP, NOTES_CONFIG_FILENAME

_notes_cache = None  # filled the first time load_notes() is called


def get_notes_config_path():
    """
    Path to notes_config.txt: the folder that contains the newspaper_ingest
    package, which is the same folder as build_issue_csv.py.
    """
    package_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(package_dir)
    return os.path.join(repo_root, NOTES_CONFIG_FILENAME)


def load_notes():
    """
    Read the notes config file and build the notes field's value.

    One credit per line, as 'note_type: note text'. Blank lines and lines
    starting with '#' are ignored. The result is cached, so the file is read
    once per run.
    """
    global _notes_cache
    if _notes_cache is not None:
        return _notes_cache

    config_path = get_notes_config_path()
    if not os.path.isfile(config_path):
        raise FileNotFoundError(
            f"Notes config file not found: {config_path}\n"
            f"Create it with one 'note_type: note text' entry per line, e.g.:\n"
            f"  creation/production credits: Deep River Public Library -- Patrick McGlamery"
        )

    entries = []
    with open(config_path, "r", encoding="utf-8") as f:
        for line_number, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                print(f"WARNING: {config_path} line {line_number} has no "
                      f"':' separator, skipping: {line}")
                continue
            note_type, _, note = line.partition(":")
            entries.append(f"{note_type.strip()}|{note.strip()}")

    if not entries:
        raise ValueError(f"Notes config file has no valid entries: {config_path}")

    _notes_cache = MULTI_SEP.join(entries)
    return _notes_cache
