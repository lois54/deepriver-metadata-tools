"""
Building the 64-column ingest rows: one parent "Publication Issue" row per
issue, one "Page" row per TIFF page, and splitting issues into file-sized
chunks.
"""

from .config import (
    COLUMNS,
    GENRE,
    HELD_BY,
    LANGUAGE,
    MAX_CONTIGUOUS_YEAR_GAP,
    MEMBER_OF_EXISTING_ENTITY_ID,
    PUBLISH,
    RESOURCE_TYPE,
    RIGHTS_STATEMENT,
    DESCRIPTION,
    TARGET_LINES_PER_FILE,
)
from .notes import load_notes


def build_parent_row_dict(record):
    """
    The 'Publication Issue' parent row's column values for one issue record.
    ID is assigned separately by rows_from_issue_record.

    local_identifier is the issue_id (e.g. '18850116_vXI_n41'), which lets a
    later run recognize that the issue is already in the file.
    """
    row = {column: "" for column in COLUMNS}
    row.update({
        "member_of_existing_entity_id": MEMBER_OF_EXISTING_ENTITY_ID,
        "publish": PUBLISH,
        "model": "Publication Issue",
        "held_by": HELD_BY,
        "title": record["title"],
        "rights_statement": RIGHTS_STATEMENT,
        "resource_type": RESOURCE_TYPE,
        "description": DESCRIPTION,
        "persons": record["persons"],
        "origin_information": record["origin_information"],
        "language": LANGUAGE,
        "genre": GENRE,
        "subject": record["subject"],
        "geographic_subject": record["geographic_subject"],
        "notes": load_notes(),
        "local_identifier": record["issue_id"],
    })
    return row


def rows_from_issue_record(record, start_id):
    """
    One issue's rows: a parent row, then one page row per TIFF page, with ID
    numbers starting at start_id.

    Returns (rows, next_id).
    """
    next_id = start_id
    parent_id = next_id
    next_id += 1

    parent_row = build_parent_row_dict(record)
    parent_row["ID"] = parent_id
    rows = [parent_row]

    for page in record["pages"]:
        page_id = next_id
        next_id += 1

        page_row = {column: "" for column in COLUMNS}
        page_row.update({
            "ID": page_id,
            "member_of": parent_id,
            "publish": PUBLISH,
            "model": "Page",
            "held_by": HELD_BY,
            "title": f"{record['title']} Page {page['page_number']}",
            "rights_statement": RIGHTS_STATEMENT,
            "weight": page["page_number"],
            "digital_file": page["digital_file"],
            "media_use": "Original File",
            "digital_origin": "reformatted digital",
            "resource_type": RESOURCE_TYPE,
            "language": LANGUAGE,
        })
        rows.append(page_row)

    return rows, next_id


def chunk_records_by_line_limit(records, start_line_count=1,
                                 target_lines=TARGET_LINES_PER_FILE):
    """
    Split an ordered list of issue records into chunks, each near target_lines
    rows. An issue's rows are never split across chunks. A chunk also ends
    when the next issue is more than MAX_CONTIGUOUS_YEAR_GAP years after the
    previous one.

    start_line_count - lines already used in the first chunk's file (1 for a
    new file, which is just the header).

    Returns a list of chunks, each a list of records.
    """
    chunks = []
    current_chunk = []
    current_lines = start_line_count
    current_chunk_end_year = None

    for record in records:
        issue_line_count = 1 + len(record["pages"])
        year_gap = (
            current_chunk_end_year is not None
            and int(record["year"]) - int(current_chunk_end_year) > MAX_CONTIGUOUS_YEAR_GAP
        )
        if current_chunk and (current_lines + issue_line_count > target_lines or year_gap):
            chunks.append(current_chunk)
            current_chunk = []
            current_lines = 1  # a new file, just the header so far

        current_chunk.append(record)
        current_lines += issue_line_count
        current_chunk_end_year = record["year"]

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def normalize_for_compare(row):
    """
    Prepare a parent row for an equality check against an existing copy of
    the same issue. Ignores ID and member_of (they depend on file position),
    and blanks date_captured (it is always today's date).
    """
    normalized = {
        k: str(v) for k, v in row.items() if k not in ("ID", "member_of")
    }
    parts = normalized.get("origin_information", "").split("|")
    if len(parts) == 13:
        parts[4] = ""
        normalized["origin_information"] = "|".join(parts)
    return normalized
