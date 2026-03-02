"""Google Sheets writer for Tableau Public stats data."""

import logging

import gspread
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

MASTER_SHEET_NAME = "workbooks_master"

MASTER_HEADERS = [
    "workbookRepoUrl",
    "title",
    "description",
    "vizUrl",
    "thumbnailUrl",
    "authorProfileName",
    "firstPublishDate",
    "lastPublishDate",
    "lastUpdateDate",
    "defaultViewName",
    "defaultViewRepoUrl",
    "showTabs",
    "showInProfile",
    "revision",
    "size",
    "category",
]

DAILY_HEADERS = [
    "fetchDate",
    "workbookRepoUrl",
    "title",
    "viewCount",
    "numberOfFavorites",
    "reaction_INSIGHTFUL",
    "reaction_SAD",
    "reaction_FAVORITE",
    "reaction_LOVE",
    "reaction_NOMINATE",
    "lastPublishDate",
    "lastUpdateDate",
    "revision",
]

FOLLOW_MASTER_HEADERS = [
    "profileName",
    "name",
    "address",
    "avatarUrl",
    "visibleWorkbookCount",
    "totalNumberOfFollowing",
    "totalNumberOfFollowers",
    "pronouns",
    "firstSeenDate",
    "lastSeenDate",
]

PROFILE_DAILY_HEADERS = [
    "fetchDate",
    "followersCount",
    "followingCount",
]


def _authorize(credentials_path: str) -> gspread.Client:
    """Authorize gspread client with service account credentials."""
    creds = Credentials.from_service_account_file(credentials_path, scopes=SCOPES)
    return gspread.authorize(creds)


def _authorize_from_dict(credentials_dict: dict) -> gspread.Client:
    """Authorize gspread client with service account credentials dict."""
    creds = Credentials.from_service_account_info(credentials_dict, scopes=SCOPES)
    return gspread.authorize(creds)


def _get_or_create_sheet(
    spreadsheet: gspread.Spreadsheet, sheet_name: str, headers: list[str]
) -> gspread.Worksheet:
    """Get existing sheet or create a new one with headers."""
    try:
        worksheet = spreadsheet.worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(
            title=sheet_name, rows=1000, cols=len(headers)
        )
        worksheet.append_row(headers, value_input_option="RAW")
        logger.info("Created new sheet: %s", sheet_name)
    return worksheet


def write_master_sheet(
    spreadsheet: gspread.Spreadsheet, master_rows: list[dict]
) -> None:
    """Write or replace the master workbook list sheet.

    This overwrites all data each time (one row per workbook).
    """
    sheet = _get_or_create_sheet(spreadsheet, MASTER_SHEET_NAME, MASTER_HEADERS)

    # Clear existing data (keep header row)
    sheet.clear()

    # Write header + all rows
    rows = [MASTER_HEADERS]
    for row_dict in master_rows:
        rows.append([str(row_dict.get(h, "")) for h in MASTER_HEADERS])

    # Resize sheet if needed
    if sheet.row_count < len(rows):
        sheet.resize(rows=len(rows))

    sheet.update(rows, value_input_option="RAW")
    logger.info("Updated master sheet with %d workbooks", len(master_rows))


def write_daily_sheet(
    spreadsheet: gspread.Spreadsheet,
    year_month: str,
    daily_rows: list[dict],
    fetch_date: str,
) -> None:
    """Append daily metrics to the monthly sheet.

    Sheet name format: daily_YYYYMM (e.g., daily_202602)
    Each day's data is appended as new rows.
    Duplicate check: if data for fetch_date already exists, skip.
    """
    sheet_name = f"daily_{year_month}"
    sheet = _get_or_create_sheet(spreadsheet, sheet_name, DAILY_HEADERS)

    # Check for existing data on this date to avoid duplicates
    existing = sheet.get_all_values()
    date_col_idx = DAILY_HEADERS.index("fetchDate")
    existing_dates = {row[date_col_idx] for row in existing[1:] if len(row) > date_col_idx}

    if fetch_date in existing_dates:
        logger.info("Data for %s already exists in %s, skipping", fetch_date, sheet_name)
        return

    # Prepare rows to append
    new_rows = []
    for row_dict in daily_rows:
        new_rows.append([str(row_dict.get(h, "")) for h in DAILY_HEADERS])

    # Expand sheet if needed
    current_rows = sheet.row_count
    needed_rows = len(existing) + len(new_rows)
    if current_rows < needed_rows:
        sheet.resize(rows=needed_rows + 100)

    # Append all rows at once
    sheet.append_rows(new_rows, value_input_option="RAW")
    logger.info(
        "Appended %d rows to %s for date %s", len(new_rows), sheet_name, fetch_date
    )


def write_follow_master_sheet(
    spreadsheet: gspread.Spreadsheet,
    sheet_name: str,
    users: list[dict],
    fetch_date: str,
) -> None:
    """Merge-update a follow master sheet (followers_master or following_master).

    Existing users: update all fields but preserve firstSeenDate.
    New users: set firstSeenDate = fetch_date.
    Users no longer in the API response are removed.
    """
    sheet = _get_or_create_sheet(spreadsheet, sheet_name, FOLLOW_MASTER_HEADERS)

    # Read existing data to preserve firstSeenDate
    existing = sheet.get_all_values()
    profile_idx = FOLLOW_MASTER_HEADERS.index("profileName")
    first_seen_idx = FOLLOW_MASTER_HEADERS.index("firstSeenDate")

    existing_first_seen: dict[str, str] = {}
    for row in existing[1:]:
        if len(row) > profile_idx and row[profile_idx]:
            fs = row[first_seen_idx] if len(row) > first_seen_idx else ""
            existing_first_seen[row[profile_idx]] = fs or fetch_date

    # Build rows from current API data
    rows = [FOLLOW_MASTER_HEADERS]
    for user in users:
        profile_name = user.get("profileName", "")
        first_seen = existing_first_seen.get(profile_name, fetch_date)

        row = []
        for h in FOLLOW_MASTER_HEADERS:
            if h == "firstSeenDate":
                row.append(first_seen)
            elif h == "lastSeenDate":
                row.append(fetch_date)
            else:
                val = user.get(h)
                row.append(str(val) if val is not None else "")
        rows.append(row)

    # Clear and rewrite
    sheet.clear()
    if sheet.row_count < len(rows):
        sheet.resize(rows=len(rows))
    sheet.update(rows, value_input_option="RAW")
    logger.info("Updated %s with %d users", sheet_name, len(users))


def write_profile_daily_sheet(
    spreadsheet: gspread.Spreadsheet,
    year_month: str,
    followers_count: int,
    following_count: int,
    fetch_date: str,
) -> None:
    """Append a daily profile row (followers/following counts).

    One row per day in a monthly sheet (daily_profile_YYYYMM).
    """
    sheet_name = f"daily_profile_{year_month}"
    sheet = _get_or_create_sheet(spreadsheet, sheet_name, PROFILE_DAILY_HEADERS)

    # Duplicate check
    existing = sheet.get_all_values()
    date_col_idx = PROFILE_DAILY_HEADERS.index("fetchDate")
    existing_dates = {row[date_col_idx] for row in existing[1:] if len(row) > date_col_idx}

    if fetch_date in existing_dates:
        logger.info(
            "Profile data for %s already exists in %s, skipping", fetch_date, sheet_name
        )
        return

    new_row = [fetch_date, str(followers_count), str(following_count)]

    current_rows = sheet.row_count
    if current_rows < len(existing) + 1:
        sheet.resize(rows=current_rows + 100)

    sheet.append_row(new_row, value_input_option="RAW")
    logger.info(
        "Appended profile daily row to %s: followers=%d, following=%d",
        sheet_name,
        followers_count,
        following_count,
    )


def open_spreadsheet(
    spreadsheet_id: str,
    credentials_path: str | None = None,
    credentials_dict: dict | None = None,
) -> gspread.Spreadsheet:
    """Open a Google Spreadsheet by its ID."""
    if credentials_dict:
        client = _authorize_from_dict(credentials_dict)
    elif credentials_path:
        client = _authorize(credentials_path)
    else:
        raise ValueError("Either credentials_path or credentials_dict must be provided")

    return client.open_by_key(spreadsheet_id)
