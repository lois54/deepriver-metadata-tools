#!/usr/bin/env python3
# =============================================================================
# RUN FROM DRIVE
# =============================================================================
# Generated: 2026-08-26 10:20 AM EDT
#
# WHAT THIS SCRIPT DOES
# ----------------------------------------------------------------------------
# GitHub Actions has no Google Drive app installed, and no folder that's
# "synced" the way your Mac's Drive folder used to be. So this script
# fakes that, just for the length of one run:
#
#   1. DOWNLOAD  - pull every file from each of the five managed Drive
#                  subfolders (DataWaiting, DataFilesCompleted,
#                  IngestFiles, MergeReports, _Logs) down into a
#                  matching local temp folder on the GitHub runner, so
#                  it looks exactly like the real Drive folder does.
#   2. RUN       - call check_duplicates.py, then build_issue_csv.py,
#                  against that local temp folder, exactly the way
#                  they'd run against a real folder. Neither script
#                  itself knows or needs to know it's not on a Drive-
#                  synced folder - see their own headers for what each
#                  one does.
#   3. RECONCILE - for a file that vanished from DataWaiting locally
#                  because it was successfully processed and moved to
#                  DataFilesCompleted under the same name, move the
#                  SAME Drive file into DataFilesCompleted (changing
#                  its folder) rather than deleting the original and
#                  uploading a fresh copy. This preserves the file's
#                  original owner and Drive history, and - importantly
#                  - doesn't require any delete permission on a file a
#                  contributor uploaded themselves, since moving a
#                  shared file between folders is an ordinary edit.
#   4. UPLOAD    - look at what's new or changed in each local
#                  subfolder after the run, and push just those changes
#                  back up to Drive. A file that still needs removing
#                  from DataWaiting after step 3 (rare - see
#                  reconcile_moved_files()) falls back to a real
#                  delete, but that's now the exception, not the rule.
#
# This script is the ONLY part that knows about Google Drive. All of the
# actual metadata logic, and all of the folder-layout logic (what goes
# where, when a file counts as "done"), stays exactly where it already
# lives - in check_duplicates.py and build_issue_csv.py.
#
# Two folders this script deliberately never touches: Archive/ (manual
# use only) and Patrick's "On Deck!" folder (his own staging area,
# unrelated to any of this) - neither is in the SUBFOLDERS list below,
# so neither is ever listed, downloaded, or uploaded to.
#
# WHAT IT NEEDS TO RUN
# ----------------------------------------------------------------------------
#   - A service account JSON key file. Locally, set the environment
#     variable GDRIVE_SA_KEY_FILE to the path of that file. In GitHub
#     Actions, the workflow writes the GDRIVE_SA_KEY secret out to a file
#     and points this same environment variable at it.
#
#   - The Drive folder's ID. Set the environment variable GDRIVE_FOLDER_ID.
#     This is the long string of letters/numbers in the folder's URL:
#         https://drive.google.com/drive/folders/THIS_PART_HERE
#     This should be the ROOT folder - the one DataWaiting,
#     DataFilesCompleted, IngestFiles, MergeReports, _Logs, Archive, and
#     On Deck! all live inside of - not one of those subfolders itself.
#
#   - OAuth credentials for creating brand-new Drive files/folders (see
#     the OAUTH_SCOPES comment below): GDRIVE_OAUTH_CLIENT_ID,
#     GDRIVE_OAUTH_CLIENT_SECRET, GDRIVE_OAUTH_REFRESH_TOKEN.
#
# HOW TO RUN IT LOCALLY (for testing before trusting it in GitHub Actions)
# ----------------------------------------------------------------------------
#   export GDRIVE_SA_KEY_FILE=/path/to/your/downloaded/key.json
#   export GDRIVE_FOLDER_ID=1xjrxZ-t65f4JAdh_5t-JP2EhRHdE8NPd
#   export GDRIVE_OAUTH_CLIENT_ID=...
#   export GDRIVE_OAUTH_CLIENT_SECRET=...
#   export GDRIVE_OAUTH_REFRESH_TOKEN=...
#   python run_from_drive.py
# =============================================================================

import os
import sys
import io
import tempfile
import subprocess
import time

from google.oauth2 import service_account
from google.oauth2.credentials import Credentials as OAuthCredentials
from google.auth.transport.requests import Request as OAuthRequest
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

SCOPES = ["https://www.googleapis.com/auth/drive"]

# The service account's SCOPES above stays broad, since it only ever
# reads and updates files it's already been shared on as Editor - it
# never needs to create anything new.
#
# For CREATING new files and folders, we use a separate OAuth
# credential instead, scoped narrowly to drive.file (see
# get_refresh_token.py). This is the workaround for a Google Drive
# quirk: service accounts have no storage quota of their own, so they
# can't own brand-new files/folders sitting in a personal
# (non-Workspace) Google account's Drive - only a real person's
# credential can. Updates to EXISTING files/deletions don't have this
# problem, since ownership never changes - only creation does.
OAUTH_SCOPES = ["https://www.googleapis.com/auth/drive.file"]

# Files we never want to touch during download/upload - they're not part
# of the actual data, just noise that can show up in a folder listing.
IGNORED_NAMES = {".DS_Store"}

# The five subfolders this script manages, each synced independently.
# See build_issue_csv.py's module header for what each one is for.
# Archive/ and Patrick's "On Deck!" folder are deliberately NOT in this
# list - see the module comment above.
SUBFOLDERS = [
    "DataWaiting",
    "DataFilesCompleted",
    "IngestFiles",
    "MergeReports",
    "_Logs",
]

# Only DataWaiting needs delete-on-move handling - see
# upload_subfolder_changes() below. Nothing else in this pipeline ever
# removes a file from Drive once it's there.
SUBFOLDER_HANDLES_DELETIONS = {"DataWaiting"}


def find_or_create_subfolder(service, oauth_service, parent_folder_id, name):
    """
    Finds a subfolder by name directly inside parent_folder_id,
    creating it if it doesn't exist yet.

    The SEARCH uses the service account (`service`), not the OAuth
    credential - the service account already has full read access to
    everything under the shared parent folder, including folders a
    person created by hand in the Drive web UI. The OAuth credential
    is deliberately narrow (drive.file scope - see OAUTH_SCOPES above),
    which Google restricts to files/folders the OAuth app itself
    created or that a person explicitly opened with a picker; it
    CANNOT see a folder someone just made in their browser, no matter
    how the parent is shared. Searching with it would silently miss
    every manually-created folder and create a duplicate on top of it.

    CREATION still goes through the OAuth credential - creating a
    folder is still creating a new Drive object, which hits the same
    "service accounts have no storage quota" restriction as creating a
    new file (see the OAUTH_SCOPES comment above). Once created, the
    service account can read/write inside it normally, since Drive
    sharing permissions are inherited from the parent folder it's
    already been shared on.
    """
    query = (
        f"'{parent_folder_id}' in parents and trashed = false and "
        f"name = '{name}' and "
        f"mimeType = 'application/vnd.google-apps.folder'"
    )
    response = service.files().list(
        q=query, spaces="drive", fields="files(id, name)"
    ).execute()
    matches = response.get("files", [])
    if matches:
        return matches[0]["id"]

    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_folder_id],
    }
    folder = oauth_service.files().create(body=metadata, fields="id").execute()
    print(f"  (created '{name}' subfolder in Drive - didn't exist yet)")
    return folder["id"]


def get_drive_service():
    """
    Builds an authenticated connection to the Drive API, using the
    service account key file pointed to by GDRIVE_SA_KEY_FILE.
    """
    key_path = os.environ.get("GDRIVE_SA_KEY_FILE")
    if not key_path:
        print("ERROR: GDRIVE_SA_KEY_FILE environment variable is not set.")
        sys.exit(1)
    if not os.path.isfile(key_path):
        print(f"ERROR: Service account key file not found: {key_path}")
        sys.exit(1)

    creds = service_account.Credentials.from_service_account_file(
        key_path, scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds)


def get_oauth_drive_service():
    """
    Builds an authenticated connection to the Drive API using the OAuth
    refresh token (drive.file scope) instead of the service account.
    This is the credential used specifically for CREATING new
    files/folders, since it acts as a real Google account with real
    storage quota, rather than a service account (which has none).

    Reads three environment variables, set by get_refresh_token.py's
    one-time output and stored as GitHub secrets:
        GDRIVE_OAUTH_CLIENT_ID
        GDRIVE_OAUTH_CLIENT_SECRET
        GDRIVE_OAUTH_REFRESH_TOKEN
    """
    client_id = os.environ.get("GDRIVE_OAUTH_CLIENT_ID")
    client_secret = os.environ.get("GDRIVE_OAUTH_CLIENT_SECRET")
    refresh_token = os.environ.get("GDRIVE_OAUTH_REFRESH_TOKEN")

    missing = [
        name for name, value in [
            ("GDRIVE_OAUTH_CLIENT_ID", client_id),
            ("GDRIVE_OAUTH_CLIENT_SECRET", client_secret),
            ("GDRIVE_OAUTH_REFRESH_TOKEN", refresh_token),
        ] if not value
    ]
    if missing:
        print(f"ERROR: missing environment variable(s): {', '.join(missing)}")
        sys.exit(1)

    creds = OAuthCredentials(
        token=None,  # no access token yet - refreshed immediately below
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=OAUTH_SCOPES,
    )
    # The refresh token doesn't expire, but the short-lived access token
    # it produces does - this exchanges it for a fresh one right away,
    # the same thing that would happen automatically on first API use.
    creds.refresh(OAuthRequest())

    return build("drive", "v3", credentials=creds)


def list_drive_files(service, folder_id):
    """
    Returns a list of {id, name, modifiedTime} dicts for every plain
    file directly inside the given folder (no sub-subfolders expected
    in any of the five managed folders).
    """
    files = []
    page_token = None
    query = f"'{folder_id}' in parents and trashed = false"

    while True:
        response = service.files().list(
            q=query,
            spaces="drive",
            fields="nextPageToken, files(id, name, modifiedTime, mimeType)",
            pageToken=page_token,
        ).execute()

        for f in response.get("files", []):
            if f["name"] in IGNORED_NAMES:
                continue
            # Skip Google Docs/Sheets/Slides native files - we only want
            # plain files (csv, txt, xlsx) that can be downloaded as-is.
            if f.get("mimeType", "").startswith("application/vnd.google-apps"):
                print(f"  (skipping Google-native file, not a plain download: {f['name']})")
                continue
            files.append(f)

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return files


def download_file(service, file_id, destination_path):
    """Downloads a single Drive file's bytes to a local path."""
    request = service.files().get_media(fileId=file_id)
    with io.FileIO(destination_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()


def upload_new_file(oauth_service, folder_id, local_path, name):
    """
    Creates a brand-new file in the Drive folder. Takes the OAUTH
    service specifically, not the service account service - service
    accounts can't own new files in a personal Drive (see the SCOPES
    comment near the top of this file).
    """
    media = MediaFileUpload(local_path, resumable=True)
    metadata = {"name": name, "parents": [folder_id]}
    oauth_service.files().create(body=metadata, media_body=media, fields="id").execute()
    print(f"  uploaded (new): {name}")


def update_existing_file(service, file_id, local_path, name):
    """Overwrites an existing Drive file's contents with a local file's."""
    media = MediaFileUpload(local_path, resumable=True)
    service.files().update(fileId=file_id, media_body=media).execute()
    print(f"  uploaded (updated): {name}")


def move_file_between_folders(service, file_id, name, source_folder_id, dest_folder_id):
    """
    Moves a Drive file from one folder to another by changing which
    folder(s) it's filed under (Drive's "parents" field) - NOT by
    deleting the original and uploading a fresh copy. This is the
    correct, Drive-native way to move a file, and deliberately used
    instead of trash_file() + upload_new_file() for the common case of
    a file build_issue_csv.py successfully processed and moved from
    DataWaiting into DataFilesCompleted under the same name.

    This matters specifically for files someone else owns (the normal
    case here - contributors drop their own files into DataWaiting):
    changing a file's folder is an ordinary EDIT, which an Editor has
    on anything shared with them, regardless of ownership. Trashing a
    file is a separate, more restrictive permission Drive can withhold
    independently of edit access - see trash_file() below, which is
    kept only as a fallback for the rare case this can't be used.

    Returns True on success, False if Drive refused the request (kept
    non-fatal, same as trash_file() - a permissions surprise here
    should never cost you the rest of a successful run's upload).
    """
    try:
        service.files().update(
            fileId=file_id,
            addParents=dest_folder_id,
            removeParents=source_folder_id,
            fields="id, parents",
        ).execute()
    except HttpError as e:
        print(f"  WARNING: couldn't move '{name}' to its new folder on Drive "
              f"({e}). Leaving it where it was for now - you may need to "
              f"move it by hand.")
        return False
    print(f"  moved on Drive: {name}")
    return True


def reconcile_moved_files(service, waiting_folder_id, waiting_dir, waiting_name_to_id,
                           completed_folder_id, completed_dir, completed_name_to_id):
    """
    Finds every file that was downloaded from DataWaiting but no longer
    exists there locally, and - for the common case where a file of the
    SAME name has appeared in DataFilesCompleted (build_issue_csv.py's
    normal "processed successfully" move) - performs a real Drive move
    (see move_file_between_folders) rather than a delete+recreate, so
    the file's original owner and Drive history are preserved and no
    delete permission is ever needed for this, the everyday case.

    On success, updates completed_name_to_id (so the later upload pass
    for DataFilesCompleted treats it as an existing file, not a fresh
    one to create) and removes the entry from waiting_name_to_id (so
    the later upload pass for DataWaiting doesn't also try to trash a
    file that's already been moved). If a file vanished from
    DataWaiting with no same-named match in DataFilesCompleted (a rarer
    case - e.g. check_duplicates.py's tagged/renamed original), or if
    the move itself fails, this leaves name_to_id untouched, and the
    existing trash-based fallback in upload_subfolder_changes handles
    it exactly as before - safely, just with a warning if that also
    hits a permissions wall.
    """
    current_waiting_names = {
        f for f in os.listdir(waiting_dir)
        if f not in IGNORED_NAMES and os.path.isfile(os.path.join(waiting_dir, f))
    }
    vanished_names = [n for n in waiting_name_to_id if n not in current_waiting_names]

    for name in sorted(vanished_names):
        if not os.path.isfile(os.path.join(completed_dir, name)):
            continue  # no same-named match in DataFilesCompleted - leave to the trash fallback

        moved = move_file_between_folders(
            service, waiting_name_to_id[name], name, waiting_folder_id, completed_folder_id
        )
        if moved:
            completed_name_to_id[name] = waiting_name_to_id[name]
            del waiting_name_to_id[name]


def trash_file(service, file_id, name):
    """
    Moves a Drive file to the trash - the fallback for a file that
    vanished from DataWaiting locally but has no same-named match in
    DataFilesCompleted for reconcile_moved_files() above to reuse (so
    there's nothing sensible to "move" it into), or for the rare case
    a real move itself fails.

    Returns True on success, False if Drive refused the request (e.g. a
    permissions error - see the try/except in upload_subfolder_changes,
    which treats a failed trash as a warning rather than a fatal error).
    """
    try:
        service.files().update(fileId=file_id, body={"trashed": True}).execute()
    except HttpError as e:
        print(f"  WARNING: couldn't remove '{name}' from Drive automatically "
              f"({e}). It was already correctly handled locally - you'll "
              f"just see this file left behind in DataWaiting too, and may "
              f"need to delete it there by hand. Check who owns this file "
              f"in Drive (right-click -> Details) if this keeps happening.")
        return False
    print(f"  removed from Drive (moved locally): {name}")
    return True


def download_subfolder(service, oauth_service, parent_folder_id, name, work_dir):
    """
    Finds/creates the Drive subfolder called `name` directly inside
    parent_folder_id, downloads every plain file in it into
    work_dir/name, and returns (drive_folder_id, local_dir, name_to_id)
    - name_to_id is used later both to tell "new" from "updated" files
    on upload, and (for DataWaiting only) to detect files that were
    moved out locally and need deleting from Drive.
    """
    drive_folder_id = find_or_create_subfolder(service, oauth_service, parent_folder_id, name)
    local_dir = os.path.join(work_dir, name)
    os.makedirs(local_dir, exist_ok=True)

    files = list_drive_files(service, drive_folder_id)
    name_to_id = {}
    for f in files:
        local_path = os.path.join(local_dir, f["name"])
        download_file(service, f["id"], local_path)
        name_to_id[f["name"]] = f["id"]
        print(f"  downloaded ({name}): {f['name']}")

    return drive_folder_id, local_dir, name_to_id


def upload_subfolder_changes(service, oauth_service, drive_folder_id, local_dir,
                              name_to_id, run_started_at, handle_deletions=False):
    """
    Uploads every new/changed file in local_dir back to the matching
    Drive folder. If handle_deletions is True, also trashes any Drive
    file whose name was originally downloaded from this folder but no
    longer exists locally afterward - see trash_file() above. Returns
    the number of files uploaded (not counting deletions).

    A file NOT already in name_to_id (Drive has nothing under this name
    in this folder) is ALWAYS uploaded, regardless of its local mtime.
    This matters specifically for a file that arrived here via
    os.rename()/shutil.move() rather than being freshly written -
    check_duplicates.py's tag-and-move for a duplicate-flagged original,
    for instance. A pure filesystem rename/move does NOT update a
    file's modification time; it keeps the mtime from whenever its
    content was first written, which for a file that started out
    downloaded from Drive is from BEFORE this run even began. So mtime
    can only be trusted to answer "did an already-known file change" -
    for anything Drive doesn't have yet under this name, upload it
    unconditionally.
    """
    uploaded_count = 0
    current_names = set()

    for filename in sorted(os.listdir(local_dir)):
        if filename in IGNORED_NAMES:
            continue
        local_path = os.path.join(local_dir, filename)
        if not os.path.isfile(local_path):
            continue
        current_names.add(filename)

        if filename in name_to_id:
            mtime = os.path.getmtime(local_path)
            if mtime < run_started_at:
                # Unchanged since before the run - one of the original
                # downloaded inputs that nothing touched.
                continue
            update_existing_file(service, name_to_id[filename], local_path, filename)
        else:
            # Nothing Drive has under this name in this folder yet -
            # always upload, mtime notwithstanding (see docstring).
            upload_new_file(oauth_service, drive_folder_id, local_path, filename)
        uploaded_count += 1

    if handle_deletions:
        for filename, file_id in name_to_id.items():
            if filename not in current_names:
                trash_file(service, file_id, filename)

    return uploaded_count


def main():
    folder_id = os.environ.get("GDRIVE_FOLDER_ID")
    if not folder_id:
        print("ERROR: GDRIVE_FOLDER_ID environment variable is not set.")
        sys.exit(1)

    service = get_drive_service()
    oauth_service = get_oauth_drive_service()

    work_dir = tempfile.mkdtemp(prefix="drive_sync_")
    print(f"Working in local temp folder: {work_dir}")
    print()

    # ---- Step 1: DOWNLOAD every managed subfolder ----
    subfolder_info = {}  # name -> (drive_folder_id, local_dir, name_to_id)
    for name in SUBFOLDERS:
        print(f"Syncing {name} ...")
        drive_folder_id, local_dir, name_to_id = download_subfolder(
            service, oauth_service, folder_id, name, work_dir
        )
        subfolder_info[name] = (drive_folder_id, local_dir, name_to_id)
        print(f"  {len(name_to_id)} file(s) found in {name}.")

    waiting_dir = subfolder_info["DataWaiting"][1]
    completed_dir = subfolder_info["DataFilesCompleted"][1]

    # ---- Step 2: RUN ----
    # Record the time right before running, so afterward we can tell
    # which files in each local subfolder are new or changed (anything
    # with a modification time at or after this moment).
    run_started_at = time.time()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    dedup_script = os.path.join(script_dir, "check_duplicates.py")
    build_script = os.path.join(script_dir, "build_issue_csv.py")

    print()
    print(f"Running check_duplicates.py against {waiting_dir} ...")
    result = subprocess.run(
        [sys.executable, dedup_script, waiting_dir, completed_dir],
        cwd=script_dir,
    )
    print()

    if result.returncode != 0:
        print("ERROR: check_duplicates.py exited with an error - stopping "
              "before build_issue_csv.py runs. Nothing will be uploaded "
              "back to Drive, so nothing partial gets pushed up.")
        sys.exit(result.returncode)

    print(f"Running build_issue_csv.py against {work_dir} ...")
    result = subprocess.run(
        [sys.executable, build_script, work_dir],
        cwd=script_dir,
    )
    print()

    if result.returncode != 0:
        print("ERROR: build_issue_csv.py exited with an error - nothing will "
              "be uploaded back to Drive, so nothing partial gets pushed up.")
        sys.exit(result.returncode)

    # ---- Step 3: reconcile files MOVED between DataWaiting and
    # DataFilesCompleted using a real Drive move, before the general
    # upload pass - see reconcile_moved_files() for why this matters
    # for files owned by someone other than this script's credentials.
    waiting_folder_id, waiting_dir, waiting_name_to_id = subfolder_info["DataWaiting"]
    completed_folder_id, completed_dir, completed_name_to_id = subfolder_info["DataFilesCompleted"]
    reconcile_moved_files(
        service, waiting_folder_id, waiting_dir, waiting_name_to_id,
        completed_folder_id, completed_dir, completed_name_to_id,
    )

    # ---- Step 4: UPLOAD every managed subfolder's remaining changes ----
    # DataWaiting is synced LAST, deliberately - it's the only folder
    # where a deletion happens (see SUBFOLDER_HANDLES_DELETIONS), and a
    # deletion is inherently riskier than a plain upload (e.g. a Drive
    # permissions error on one file - see trash_file()). Syncing the
    # other four folders first means the actual valuable output of the
    # run (the new/updated ingest CSV, the report, the completed-file
    # moves, the log) is safely on Drive BEFORE anything involving a
    # deletion is even attempted - so a problem with DataWaiting's
    # cleanup can never cost you a correctly-computed run's output.
    print("Checking for new, changed, or moved files to sync back to Drive...")
    upload_order = [n for n in SUBFOLDERS if n != "DataWaiting"] + ["DataWaiting"]
    total_uploaded = 0
    for name in upload_order:
        drive_folder_id, local_dir, name_to_id = subfolder_info[name]
        total_uploaded += upload_subfolder_changes(
            service, oauth_service, drive_folder_id, local_dir, name_to_id,
            run_started_at, handle_deletions=(name in SUBFOLDER_HANDLES_DELETIONS),
        )

    print()
    print(f"Done. {total_uploaded} file(s) uploaded back to Drive.")


if __name__ == "__main__":
    main()
