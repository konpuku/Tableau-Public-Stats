"""Tableau Public API client for fetching workbook data."""

import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

BASE_URL_PROFILE = "https://public.tableau.com/profile/api"
BASE_URL_PUBLIC = "https://public.tableau.com/public/apis"
BASE_URL_BFF = "https://public.tableau.com/public/apis/bff/v2"

WORKBOOKS_PAGE_SIZE = 50
CATEGORIES_PAGE_SIZE = 500
FOLLOW_PAGE_SIZE = 500
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


def fetch_categories(username: str) -> list[dict]:
    """Fetch workbooks with categories (includes reactionCounts)."""
    all_items: list[dict] = []
    start = 0

    while True:
        url = f"{BASE_URL_BFF}/author/{username}/categories"
        params = {"startIndex": start, "pageSize": CATEGORIES_PAGE_SIZE}
        data = _get_json(url, params)

        if not data:
            break

        items = data.get("workbooksWithCategories", [])
        if not items:
            break

        all_items.extend(items)
        logger.info("Fetched %d category items (total: %d)", len(items), len(all_items))

        if len(items) < CATEGORIES_PAGE_SIZE:
            break

        start += CATEGORIES_PAGE_SIZE
        time.sleep(REQUEST_DELAY_SEC)

    return all_items


def fetch_follow_list(username: str, follow_type: str) -> list[dict]:
    """Fetch followers or following list with pagination.

    Args:
        username: Tableau Public profile name.
        follow_type: 'followers' or 'following'.
    """
    all_users: list[dict] = []
    index = 0

    while True:
        url = f"{BASE_URL_PROFILE}/{follow_type}/{username}"
        params = {"count": FOLLOW_PAGE_SIZE, "index": index}
        data = _get_json(url, params)

        if not data:
            break

        users = data.get("authorFeedInfos", [])
        if not users:
            break

        all_users.extend(users)
        logger.info("Fetched %d %s (total: %d)", len(users), follow_type, len(all_users))

        if len(users) < FOLLOW_PAGE_SIZE:
            break

        index += FOLLOW_PAGE_SIZE
        time.sleep(REQUEST_DELAY_SEC)

    return all_users


def build_reaction_map(category_items: list[dict]) -> dict[str, dict]:
    """Build a mapping of workbookRepoUrl -> reactionCounts from categories data.

    A workbook may appear in multiple categories; uses the first occurrence.
    """
    reaction_map: dict[str, dict] = {}
    for item in category_items:
        wb = item.get("workbook", {})
        repo_url = wb.get("workbookRepoUrl", "")
        if repo_url and repo_url not in reaction_map:
            reaction_map[repo_url] = wb.get("reactionCounts", {})
    return reaction_map


def build_category_map(category_items: list[dict]) -> dict[str, list[str]]:
    """Build a mapping of workbookRepoUrl -> list of categoryNames.

    A workbook may appear in multiple categories.
    """
    category_map: dict[str, list[str]] = {}
    for item in category_items:
        wb = item.get("workbook", {})
        repo_url = wb.get("workbookRepoUrl", "")
        category_name = item.get("categoryName", "")
        if repo_url and category_name:
            if repo_url in category_map:
                if category_name not in category_map[repo_url]:
                    category_map[repo_url].append(category_name)
            else:
                category_map[repo_url] = [category_name]
    return category_map


def extract_master_row(
    wb: dict, category_map: dict[str, list[str]] | None = None
) -> dict:
    """Extract static/semi-static fields for the master sheet."""
    default_view = wb.get("defaultViewRepoUrl", "")
    repo_url = wb.get("workbookRepoUrl", "")
    viz_url = ""
    thumbnail_url = ""
    if repo_url and default_view:
        viz_url = f"https://public.tableau.com/views/{repo_url}/{default_view}"
        prefix = repo_url[:2]
        thumbnail_url = f"https://public.tableau.com/static/images/{prefix}/{repo_url}/{default_view}/1.png"

    categories = (category_map or {}).get(repo_url, [])

    return {
        "workbookRepoUrl": repo_url,
        "title": wb.get("title", ""),
        "description": wb.get("description", ""),
        "vizUrl": viz_url,
        "thumbnailUrl": thumbnail_url,
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
        "category": ", ".join(categories),
    }


REACTION_TYPES = ["INSIGHTFUL", "SAD", "FAVORITE", "LOVE", "NOMINATE"]


def extract_daily_row(
    wb: dict, fetch_date: str, reaction_map: dict[str, dict] | None = None
) -> dict:
    """Extract daily transaction metrics including reaction counts."""
    repo_url = wb.get("workbookRepoUrl", "")
    reactions = (reaction_map or {}).get(repo_url, {})

    row = {
        "fetchDate": fetch_date,
        "workbookRepoUrl": repo_url,
        "title": wb.get("title", ""),
        "viewCount": wb.get("viewCount", 0),
        "numberOfFavorites": wb.get("numberOfFavorites", 0),
        "lastPublishDate": wb.get("lastPublishDate", ""),
        "lastUpdateDate": wb.get("lastUpdateDate", ""),
        "revision": wb.get("revision", ""),
    }
    for rtype in REACTION_TYPES:
        row[f"reaction_{rtype}"] = reactions.get(rtype, 0)

    return row
