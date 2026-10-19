"""
Fixed project values: the credits and rights text that go into every
issue row, the publisher timeline, folder names, and the column layout
the repository ingest expects. Edit values here, not in the other modules.
"""

# ---- Fixed values for every "Publication Issue" row -----------------------
HELD_BY = "Deep River Public Library"
RIGHTS_STATEMENT = "NO COPYRIGHT - UNITED STATES"
PUBLISH = "Y"
RESOURCE_TYPE = "Text"
NEWSPAPER_NAME = "Deep River New Era"
DESCRIPTION = ("Contact the Deep River Historical Society at "
               "860-526-1449 or info@deepriverhistoricalsociety.org.")

# The parent collection ID in the repository.
MEMBER_OF_EXISTING_ENTITY_ID = 61106

GENRE = "newspapers"

# language field (column W) - every row, same value.
LANGUAGE = "English"

# ---- Alert email -----------------------------------------------------------
# Uses Gmail SMTP with an app password. The password itself is read from
# the EMAIL_APP_PASSWORD environment variable in alerts.py, never stored here.
EMAIL_SENDER = "loisbb@gmail.com"
EMAIL_RECIPIENTS = ["loisbb@gmail.com"]  # add Patrick's address here later

# persons field (column T) - the publisher's name is inserted in front of
# this suffix based on the issue's year (see build_persons in records.py).
PERSONS_STATIC_SUFFIX = (
    "Deep River Historical Society|relators:ctb^^"
    "Webb, Robert; Charter Oak Scanning and Digitization|relators:ctb"
)

# notes field (column AB) is loaded from this plain text file, which sits
# next to the entry script (build_issue_csv.py), not in the data folders.
NOTES_CONFIG_FILENAME = "notes_config.txt"

# origin_information - the parts that are the same on every issue.
ORIGIN_PLACE = "Deep River (Conn.)"
ORIGIN_ISSUANCE = "serial"
ORIGIN_FREQUENCY = "weekly"

# The publisher listed in the persons field is looked up by the issue's
# date. Names are stored "Last, First Middle".
#
# ASSUMPTION: where two ranges share a year (e.g. Kirtland's "...1903" and
# Prann's "1903..."), the LATER publisher is treated as starting Jan 1 of
# that shared year, since there's no exact transition date. Flag this if
# the actual changeover dates are ever found.
PUBLISHER_BY_DATE = [
    ("1874-01-01", "Sheldon, Francis"),
    ("1885-01-01", "Kirtland, Charles A."),
    ("1903-01-01", "Prann, Ernest L."),
    ("1946-01-01", "Johnson, Curtiss S."),
]

# The server-side path BASE that digital_file values are built from. The
# subfolder is always the issue's YEAR, even if a listing file shows an
# older volume-based path.
DIGITAL_FILE_BASE = "/opt/ingest_data/uploads/3/"

# The character(s) used to glue multiple values into one CSV cell.
MULTI_SEP = "^^"

# Ingest CSVs stay well under the repository's hard limit of 1000 lines.
# A file rolls over once the next issue would push it past this target.
# An issue's parent + page rows always stay together in one file.
TARGET_LINES_PER_FILE = 800

# When issues are more than this many years apart, force a new output file.
# A gap of 1 is normal (a volume straddling New Year's).
MAX_CONTIGUOUS_YEAR_GAP = 1

# How far apart the two neighboring issues' dates can be before we stop
# trusting a midpoint guess between them (see attempt_date_correction).
MAX_DATE_CORRECTION_GAP_DAYS = 60

# All 64 column names, in the exact order the repository ingest expects.
COLUMNS = [
    "ID", "member_of", "member_of_existing_entity_id", "publish",
    "model", "held_by", "title", "rights_statement", "weight",
    "digital_file", "media_use", "digital_origin", "creative_commons",
    "use_and_reproduction", "restriction_on_access", "resource_type",
    "description", "local_identifier", "family_name", "persons",
    "organizations", "origin_information", "language", "genre",
    "subject", "temporal_subject", "geographic_subject", "notes",
    "scale", "physical_form", "reformatting_quality",
    "physical_description_note", "access_restriction_term",
    "related_items", "table_of_contents", "handle", "isbn",
    "oclc_number", "loc_classification", "coordinates",
    "geographic_code", "west_bounding_coordinate",
    "east_bounding_coordinate", "north_bounding_coordinate",
    "south_bounding_coordinate", "extent", "physical_location",
    "sublocation", "shelf_locator", "location_url",
    "record_information", "degree_name", "degree_level",
    "degree_discipline", "kingdom_dwr", "phylum_dwr", "class_dwr",
    "order_dwr", "family_dwr", "genus_dwr", "sci_name_auth_dwr",
    "locality_dwr", "location_remarks_dwr", "recorded_by_dwr",
]

# ---- Folder layout (see the module header in the original script) ---------
DATA_WAITING_SUBDIR = "DataWaiting"
DATA_COMPLETED_SUBDIR = "DataFilesCompleted"
INGEST_FILES_SUBDIR = "IngestFiles"
MERGE_REPORTS_SUBDIR = "MergeReports"
LOGS_SUBDIR_NAME = "_Logs"
RUN_LOG_FILENAME = "run_log.txt"
LAST_PROBLEMS_FILENAME = "last_problems.txt"
LAST_CORRECTIONS_FILENAME = "last_corrections.txt"

# A person creates an (empty) file with one of these names in a year folder to
# say "this year's ingest is complete and has been given to the repository".
# The pipeline then never modifies that year's existing ingest files.
INGEST_COMPLETE_MARKER_NAMES = ("ingest_complete", "ingest_complete.txt")
