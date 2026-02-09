"""Main script: fetch Tableau Public stats and write to Google Sheets."""

import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta

from src.tableau_api import (
    build_reaction_map,
    extract_daily_row,
    extract_master_row,
    fetch_all_workbook_details,
    fetch_categories,
)
from src.sheets_writer import open_spreadsheet, write_daily_sheet, write_master_sheet

JST = timezone(timedelta(hours=9))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    # --- Configuration from environment variables ---
    username = os.environ.get("TABLEAU_USERNAME")
    spreadsheet_id = os.environ.get("GOOGLE_SPREADSHEET_ID")
    credentials_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    credentials_path = os.environ.get("GOOGLE_CREDENTIALS_PATH")

    if not username:
        logger.error("TABLEAU_USERNAME is required")
        sys.exit(1)

    if not spreadsheet_id:
        logger.error("GOOGLE_SPREADSHEET_ID is required")
        sys.exit(1)

    if not credentials_json and not credentials_path:
        logger.error("GOOGLE_CREDENTIALS_JSON or GOOGLE_CREDENTIALS_PATH is required")
        sys.exit(1)

    # --- Parse credentials ---
    credentials_dict = None
    if credentials_json:
        credentials_dict = json.loads(credentials_json)

    # --- Determine dates ---
    now = datetime.now(JST)
    fetch_date = now.strftime("%Y-%m-%d")
    year_month = now.strftime("%Y%m")
    logger.info("Fetch date: %s (JST)", fetch_date)

    # --- Fetch workbook data from Tableau Public API ---
    logger.info("Fetching workbook data for user: %s", username)
    workbooks = fetch_all_workbook_details(username)

    if not workbooks:
        logger.warning("No workbooks found for user: %s", username)
        sys.exit(0)

    logger.info("Fetched %d workbooks", len(workbooks))

    # --- Fetch reaction counts from Categories API ---
    logger.info("Fetching reaction counts from Categories API...")
    category_items = fetch_categories(username)
    reaction_map = build_reaction_map(category_items)
    logger.info("Built reaction map for %d workbooks", len(reaction_map))

    # --- Prepare data ---
    master_rows = [extract_master_row(wb) for wb in workbooks]
    daily_rows = [extract_daily_row(wb, fetch_date, reaction_map) for wb in workbooks]

    # --- Write to Google Sheets ---
    logger.info("Opening spreadsheet: %s", spreadsheet_id)
    spreadsheet = open_spreadsheet(
        spreadsheet_id=spreadsheet_id,
        credentials_path=credentials_path,
        credentials_dict=credentials_dict,
    )

    write_master_sheet(spreadsheet, master_rows)
    write_daily_sheet(spreadsheet, year_month, daily_rows, fetch_date)

    logger.info("Done! Updated master sheet and appended daily stats for %s", fetch_date)


if __name__ == "__main__":
    main()
