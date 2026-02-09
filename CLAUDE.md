# CLAUDE.md - Tableau Public Stats

## Project Overview

Tableau Public APIを使って特定ユーザーのワークブック統計情報を日次で取得し、Google Spreadsheetsに蓄積するツール。

## Architecture

```
src/
├── __init__.py
├── tableau_api.py    # Tableau Public API client (fetch, pagination, data extraction)
├── sheets_writer.py  # Google Sheets read/write (gspread)
└── main.py           # Orchestration: fetch → transform → write
.github/workflows/
└── daily_fetch.yml   # GitHub Actions daily cron (06:00 UTC / 15:00 JST)
```

## Key Design Decisions

### Google Sheets Row Limit Strategy
- **`workbooks_master` sheet**: One row per workbook, overwritten daily (static info)
- **`daily_YYYYMM` sheets**: Monthly sheets for daily transaction metrics (viewCount, favorites, etc.)
- 500 workbooks × 31 days = ~15,500 rows/month — well within limits
- Duplicate prevention: skips if `fetchDate` already exists in the monthly sheet

### Tableau Public API
- Unofficial API at `public.tableau.com` — no auth required
- Workbook list: paginated at 50/page via `/public/apis/workbooks`
- Workbook detail: `/profile/api/single_workbook/{repoUrl}`
- 0.5s delay between requests to avoid rate limiting
- Retry with exponential backoff (3 attempts)

## Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run locally
export TABLEAU_USERNAME=your_username
export GOOGLE_SPREADSHEET_ID=your_sheet_id
export GOOGLE_CREDENTIALS_PATH=credentials.json
python -m src.main
```

## Environment Variables

| Variable | Description | Required |
|---|---|---|
| `TABLEAU_USERNAME` | Tableau Public profile name | Yes |
| `GOOGLE_SPREADSHEET_ID` | Target spreadsheet ID | Yes |
| `GOOGLE_CREDENTIALS_JSON` | Service account JSON (for CI) | One of these |
| `GOOGLE_CREDENTIALS_PATH` | Path to credentials file (for local) | required |

## GitHub Actions Secrets

Set these in repo Settings → Secrets:
- `TABLEAU_USERNAME`
- `GOOGLE_SPREADSHEET_ID`
- `GOOGLE_CREDENTIALS_JSON` (entire service account JSON)

## Conventions

- Python 3.12+, type hints used
- Logging via `logging` module (no print statements)
- All dates in JST (UTC+9)
- Environment-based configuration (no config files committed)
