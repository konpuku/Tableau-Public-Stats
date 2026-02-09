"""Tableau Public API client for fetching workbook data."""

import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

BASE_URL_PROFILE = "https://public.tableau.com/profile/api"
BASE_URL_PUBLIC = "https://public.tableau.com/public/apis"

WORKBOOKS_PAGE_SIZE = 50
REQUEST_DELAY_SEC = 0.5
MAX_RETRIES = 3


def _get_json(url: str, params: dict | None = None) -> Any:
    """GET request with retry logic."""
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            if attempt < MAX_RETRIES - 1:
                wait = 2 ** (attempt + 1)
                logger.warning("Request failed (%s), retrying in %ds...", e, wait)
                time.sleep(wait)
            else:
                raise
    return None


def fetch_profile(username: str) -> dict:
    """Fetch user profile information."""
    url = f"{BASE_URL_PROFILE}/{username}"
    return _get_json(url)


def fetch_workbook_list(username: str) -> list[dict]:
    """Fetch all workbooks for a user with pagination."""
    all_workbooks = []
    start = 0

    while True:
        url = f"{BASE_URL_PUBLIC}/workbooks"
        params = {
            "profileName": username,
            "start": start,
            "count": WORKBOOKS_PAGE_SIZE,
            "visibility": "NON_HIDDEN",
        }
        data = _get_json(url, params)

        if not data:
            break

        # The response is a list of workbooks
        workbooks = data if isinstance(data, list) else data.get("contents", [])
        if not workbooks:
            break

        all_workbooks.extend(workbooks)
        logger.info("Fetched %d workbooks (total: %d)", len(workbooks), len(all_workbooks))

        if len(workbooks) < WORKBOOKS_PAGE_SIZE:
            break

        start += WORKBOOKS_PAGE_SIZE
        time.sleep(REQUEST_DELAY_SEC)

    return all_workbooks


def fetch_workbook_detail(workbook_repo_url: str) -> dict:
    """Fetch detailed information for a single workbook."""
    url = f"{BASE_URL_PROFILE}/single_workbook/{workbook_repo_url}"
    data = _get_json(url)
    time.sleep(REQUEST_DELAY_SEC)
    return data


def fetch_all_workbook_details(username: str) -> list[dict]:
    """Fetch the workbook list and detailed info for each workbook."""
    workbooks = fetch_workbook_list(username)
    logger.info("Found %d workbooks for user '%s'", len(workbooks), username)

    detailed = []
    for i, wb in enumerate(workbooks):
        repo_url = wb.get("workbookRepoUrl", "")
        if not repo_url:
            logger.warning("Skipping workbook with no repoUrl: %s", wb.get("title", "unknown"))
            continue

        try:
            detail = fetch_workbook_detail(repo_url)
            detailed.append(detail)
        except Exception:
            logger.exception("Failed to fetch detail for '%s'", repo_url)

        if (i + 1) % 50 == 0:
            logger.info("Progress: %d / %d workbooks fetched", i + 1, len(workbooks))

    logger.info("Successfully fetched details for %d workbooks", len(detailed))
    return detailed


def extract_master_row(wb: dict) -> dict:
    """Extract static/semi-static fields for the master sheet."""
    default_view = wb.get("defaultViewRepoUrl", "")
    repo_url = wb.get("workbookRepoUrl", "")
    viz_url = ""
    if repo_url and default_view:
        viz_url = f"https://public.tableau.com/views/{repo_url}/{default_view}"

    return {
        "workbookRepoUrl": repo_url,
        "title": wb.get("title", ""),
        "description": wb.get("description", ""),
        "vizUrl": viz_url,
        "authorProfileName": wb.get("authorProfileName", ""),
        "firstPublishDate": wb.get("firstPublishDate", ""),
        "lastPublishDate": wb.get("lastPublishDate", ""),
        "lastUpdateDate": wb.get("lastUpdateDate", ""),
        "defaultViewName": wb.get("defaultViewName", ""),
        "defaultViewRepoUrl": default_view,
        "showTabs": wb.get("showTabs", ""),
        "showInProfile": wb.get("showInProfile", ""),
        "revision": wb.get("revision", ""),
        "size": wb.get("size", ""),
        "category": wb.get("category", ""),
    }


def extract_daily_row(wb: dict, fetch_date: str) -> dict:
    """Extract daily transaction metrics."""
    return {
        "fetchDate": fetch_date,
        "workbookRepoUrl": wb.get("workbookRepoUrl", ""),
        "title": wb.get("title", ""),
        "viewCount": wb.get("viewCount", 0),
        "numberOfFavorites": wb.get("numberOfFavorites", 0),
        "lastPublishDate": wb.get("lastPublishDate", ""),
        "lastUpdateDate": wb.get("lastUpdateDate", ""),
        "revision": wb.get("revision", ""),
    }
