"""
The four managed folders under the root: making sure they exist, and moving
fully-used input files from DataWaiting to DataFilesCompleted.
"""

import os
import shutil

from .config import DATA_COMPLETED_SUBDIR
from .runlog import append_run_log


def ensure_subdir(directory, name):
    """Create <directory>/<name> if needed and return its path."""
    path = os.path.join(directory, name)
    os.makedirs(path, exist_ok=True)
    return path


def move_processed_input_files(waiting_dir, completed_dir, filenames,
                                file_usable_counts, file_pending, log_root):
    """
    Move every input file that contributed at least one usable record and has
    nothing still pending from DataWaiting into DataFilesCompleted.

    A file that contributed nothing stays in DataWaiting, so it stays visible
    as needing attention. A file with any pending entry also stays, so it can
    be retried on a later run. The problems are recorded in the merge report
    and _Logs either way.
    """
    for filename in filenames:
        if file_usable_counts.get(filename, 0) <= 0:
            continue  # whole-file failure - leave it in DataWaiting
        if filename in file_pending:
            continue  # still has unmatched entries - leave it in DataWaiting

        src = os.path.join(waiting_dir, filename)
        if not os.path.isfile(src):
            continue

        dest_name = filename
        dest = os.path.join(completed_dir, dest_name)
        if os.path.exists(dest):
            # Never overwrite or silently lose a file.
            base, ext = os.path.splitext(filename)
            counter = 2
            while os.path.exists(dest):
                dest_name = f"{base}_dup{counter}{ext}"
                dest = os.path.join(completed_dir, dest_name)
                counter += 1

        shutil.move(src, dest)
        append_run_log(
            log_root,
            f"moved '{filename}' to {DATA_COMPLETED_SUBDIR}/{dest_name} "
            f"after processing"
        )
