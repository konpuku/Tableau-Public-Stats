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
