#!/usr/bin/env python3
# =============================================================================
# RUN FROM DRIVE
# =============================================================================
# Generated: 2026-07-27 04:45 PM EDT
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
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

SCOPES = ["https://www.googleapis.com/auth/drive"]

# Files we never want to touch during download/upload - they're not part
# of the actual data, just noise that can show up in a folder listing.
IGNORED_NAMES = {".DS_Store"}


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


def upload_new_file(service, folder_id, local_path, name):
    """Creates a brand-new file in the Drive folder."""
    media = MediaFileUpload(local_path, resumable=True)
    metadata = {"name": name, "parents": [folder_id]}
    service.files().create(body=metadata, media_body=media, fields="id").execute()
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
            upload_new_file(service, folder_id, local_path, filename)
        uploaded_count += 1

    print()
    print(f"Done. {uploaded_count} file(s) uploaded back to Drive.")


if __name__ == "__main__":
    main()
