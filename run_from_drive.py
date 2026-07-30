#!/usr/bin/env python3
# =============================================================================
# RUN FROM DRIVE
# =============================================================================
# Generated: 2026-07-30 11:35 AM EDT
#
# WHAT THIS SCRIPT DOES
# ----------------------------------------------------------------------------
# GitHub Actions has no Google Drive app installed, and no folder that's
# "synced" the way your Mac's Drive folder is. So this script fakes that,
# just for the length of one run:
#
#   1. DOWNLOAD  - pull every file in the target Drive folder down into a
#                  plain local temp folder on the GitHub runner.
#   2. RUN       - call build_issue_csv.py against that local temp folder,
#                  exactly the way you run it on your Mac. build_issue_csv.py
#                  itself is untouched - it has no idea it's not on your Mac.
#   3. UPLOAD    - look at what's new or changed in the temp folder after
#                  the run, and push just those files back up to Drive.
#
# This script is the ONLY part that knows about Google Drive. All of your
# actual metadata logic stays exactly where it already lives.
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
#
# HOW TO RUN IT LOCALLY (for testing before trusting it in GitHub Actions)
# ----------------------------------------------------------------------------
#   export GDRIVE_SA_KEY_FILE=/path/to/your/downloaded/key.json
#   export GDRIVE_FOLDER_ID=1xjrxZ-t65f4JAdh_5t-JP2EhRHdE8NPd
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
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

SCOPES = ["https://www.googleapis.com/auth/drive"]

# The service account's SCOPES above stays broad, since it only ever
# reads and updates files it's already been shared on as Editor - it
# never needs to create anything new.
#
# For CREATING new files, we use a separate OAuth credential instead,
# scoped narrowly to drive.file (see get_refresh_token.py). This is the
# workaround for a Google Drive quirk: service accounts have no storage
# quota of their own, so they can't own brand-new files sitting in a
# personal (non-Workspace) Google account's Drive - only a real person's
# credential can. Updates to EXISTING files don't have this problem,
# since ownership never changes on an update - only creation.
OAUTH_SCOPES = ["https://www.googleapis.com/auth/drive.file"]

# Files we never want to touch during download/upload - they're not part
# of the actual data, just noise that can show up in a folder listing.
IGNORED_NAMES = {".DS_Store"}

# Name of the subfolder build_issue_csv.py writes its run log and
# problem-comparison state into (see LOGS_SUBDIR_NAME in that script).
# This gets synced separately from the main folder's contents, since
# the main-folder sync deliberately skips ALL subfolders (see
# list_drive_files) - this one just gets its own small sync pass.
LOGS_SUBFOLDER_NAME = "_Logs"


def find_or_create_subfolder(oauth_service, parent_folder_id, name):
    """
    Finds a subfolder by name directly inside parent_folder_id,
    creating it if it doesn't exist yet. Creation goes through the
    OAuth credential, not the service account - creating a folder is
    still creating a new Drive object, which hits the same "service
    accounts have no storage quota" restriction as creating a new file
    (see the OAUTH_SCOPES comment above). Once created, the service
    account can read/write inside it normally, since Drive sharing
    permissions are inherited from the parent folder it's already been
    shared on.
    """
    query = (
        f"'{parent_folder_id}' in parents and trashed = false and "
        f"name = '{name}' and "
        f"mimeType = 'application/vnd.google-apps.folder'"
    )
    response = oauth_service.files().list(
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
    This is the credential used specifically for CREATING new files,
    since it acts as a real Google account with real storage quota,
    rather than a service account (which has none).

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
    Returns a list of {id, name, modifiedTime} dicts for every file
    directly inside the given folder (no subfolders, per how this
    project's Drive folder is organized).
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


def main():
    folder_id = os.environ.get("GDRIVE_FOLDER_ID")
    if not folder_id:
        print("ERROR: GDRIVE_FOLDER_ID environment variable is not set.")
        sys.exit(1)

    service = get_drive_service()
    oauth_service = get_oauth_drive_service()

    # ---- Step 1: DOWNLOAD ----
    print(f"Listing files in Drive folder {folder_id} ...")
    drive_files = list_drive_files(service, folder_id)
    print(f"  Found {len(drive_files)} file(s).")

    work_dir = tempfile.mkdtemp(prefix="drive_sync_")
    print(f"Downloading into local temp folder: {work_dir}")

    # name -> drive file id, so we know later whether a file we're
    # uploading is brand new or an update to something that already
    # existed in Drive.
    name_to_id = {}

    for f in drive_files:
        local_path = os.path.join(work_dir, f["name"])
        download_file(service, f["id"], local_path)
        name_to_id[f["name"]] = f["id"]
        print(f"  downloaded: {f['name']}")

    # ---- Step 1b: DOWNLOAD the _Logs subfolder's contents separately ----
    # build_issue_csv.py expects its bookkeeping files at
    # <work_dir>/_Logs/... - this pulls down whatever's already there
    # (the run log and last-run problem set from previous runs) so this
    # run can read and append to them, same as it would locally.
    logs_folder_id = find_or_create_subfolder(oauth_service, folder_id, LOGS_SUBFOLDER_NAME)
    logs_dir = os.path.join(work_dir, LOGS_SUBFOLDER_NAME)
    os.makedirs(logs_dir, exist_ok=True)

    logs_files = list_drive_files(service, logs_folder_id)
    logs_name_to_id = {}
    for f in logs_files:
        local_path = os.path.join(logs_dir, f["name"])
        download_file(service, f["id"], local_path)
        logs_name_to_id[f["name"]] = f["id"]
        print(f"  downloaded ({LOGS_SUBFOLDER_NAME}): {f['name']}")

    # ---- Step 2: RUN ----
    # Record the time right before running, so afterward we can tell
    # which files in work_dir are new or changed (anything with a
    # modification time at or after this moment).
    run_started_at = time.time()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    build_script = os.path.join(script_dir, "build_issue_csv.py")

    print()
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

    # ---- Step 3: UPLOAD ----
    print("Checking for new or changed files to upload back to Drive...")
    uploaded_count = 0

    for filename in sorted(os.listdir(work_dir)):
        if filename in IGNORED_NAMES:
            continue
        local_path = os.path.join(work_dir, filename)
        if not os.path.isfile(local_path):
            continue

        mtime = os.path.getmtime(local_path)
        if mtime < run_started_at:
            # Unchanged since before the run - one of the original
            # downloaded inputs that build_issue_csv.py didn't touch.
            continue

        if filename in name_to_id:
            update_existing_file(service, name_to_id[filename], local_path, filename)
        else:
            upload_new_file(oauth_service, folder_id, local_path, filename)
        uploaded_count += 1

    # ---- Step 3b: UPLOAD anything new/changed in _Logs, separately ----
    for filename in sorted(os.listdir(logs_dir)):
        local_path = os.path.join(logs_dir, filename)
        if not os.path.isfile(local_path):
            continue

        mtime = os.path.getmtime(local_path)
        if mtime < run_started_at:
            continue  # unchanged since before the run

        if filename in logs_name_to_id:
            update_existing_file(service, logs_name_to_id[filename], local_path, filename)
        else:
            upload_new_file(oauth_service, logs_folder_id, local_path, filename)
        uploaded_count += 1

    print()
    print(f"Done. {uploaded_count} file(s) uploaded back to Drive.")


if __name__ == "__main__":
    main()
