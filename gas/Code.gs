/**
 * Tableau Public Stats - Google Apps Script version
 *
 * Setup:
 *   1. Create a new Google Spreadsheet
 *   2. Extensions > Apps Script
 *   3. Paste this code
 *   4. Set Script Property: TABLEAU_USERNAME (Project Settings > Script Properties)
 *   5. Set project timezone to Asia/Tokyo (Project Settings > General)
 *   6. Run main() manually or set a daily trigger
 */

// ===================
// Configuration
// ===================

const BASE_URL_PROFILE = 'https://public.tableau.com/profile/api';
const BASE_URL_PUBLIC = 'https://public.tableau.com/public/apis';
const BASE_URL_BFF = 'https://public.tableau.com/public/apis/bff/v2';

const WORKBOOKS_PAGE_SIZE = 50;
const CATEGORIES_PAGE_SIZE = 500;
const REQUEST_DELAY_MS = 500;
const MAX_RETRIES = 3;

const MASTER_SHEET_NAME = 'workbooks_master';

const MASTER_HEADERS = [
  'workbookRepoUrl', 'title', 'description', 'vizUrl',
  'authorProfileName', 'firstPublishDate', 'lastPublishDate',
  'lastUpdateDate', 'defaultViewName', 'defaultViewRepoUrl',
  'showTabs', 'showInProfile', 'revision', 'size', 'category',
];

const DAILY_HEADERS = [
  'fetchDate', 'workbookRepoUrl', 'title', 'viewCount',
  'numberOfFavorites', 'reaction_INSIGHTFUL', 'reaction_SAD',
  'reaction_FAVORITE', 'reaction_LOVE', 'reaction_NOMINATE',
  'lastPublishDate', 'lastUpdateDate', 'revision',
];

const REACTION_TYPES = ['INSIGHTFUL', 'SAD', 'FAVORITE', 'LOVE', 'NOMINATE'];

// ===================
// HTTP Helper
// ===================

function getJson_(url, params) {
  if (params) {
    const query = Object.entries(params)
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
      .join('&');
    url = `${url}?${query}`;
  }

  for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
    try {
      const response = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
      const code = response.getResponseCode();
      if (code >= 200 && code < 300) {
        return JSON.parse(response.getContentText());
      }
      throw new Error(`HTTP ${code}: ${response.getContentText().substring(0, 200)}`);
    } catch (e) {
      if (attempt < MAX_RETRIES - 1) {
        const wait = Math.pow(2, attempt + 1) * 1000;
        console.warn(`Request failed (${e.message}), retrying in ${wait / 1000}s...`);
        Utilities.sleep(wait);
      } else {
        throw e;
      }
    }
  }
}

// ===================
// Tableau API
// ===================

function fetchWorkbookList_(username) {
  const allWorkbooks = [];
  let start = 0;

  while (true) {
    const params = {
      profileName: username,
      start: start,
      count: WORKBOOKS_PAGE_SIZE,
      visibility: 'NON_HIDDEN',
    };
    const data = getJson_(`${BASE_URL_PUBLIC}/workbooks`, params);

    if (!data) break;

    const workbooks = Array.isArray(data) ? data : (data.contents || []);
    if (workbooks.length === 0) break;

    allWorkbooks.push(...workbooks);
    console.log(`Fetched ${workbooks.length} workbooks (total: ${allWorkbooks.length})`);

    if (workbooks.length < WORKBOOKS_PAGE_SIZE) break;

    start += WORKBOOKS_PAGE_SIZE;
    Utilities.sleep(REQUEST_DELAY_MS);
  }

  return allWorkbooks;
}

function fetchWorkbookDetail_(repoUrl) {
  const data = getJson_(`${BASE_URL_PROFILE}/single_workbook/${repoUrl}`);
  Utilities.sleep(REQUEST_DELAY_MS);
  return data;
}

function fetchAllWorkbookDetails_(username) {
  const workbooks = fetchWorkbookList_(username);
  console.log(`Found ${workbooks.length} workbooks for user '${username}'`);

  const detailed = [];
  for (let i = 0; i < workbooks.length; i++) {
    const repoUrl = workbooks[i].workbookRepoUrl || '';
    if (!repoUrl) {
      console.warn(`Skipping workbook with no repoUrl: ${workbooks[i].title || 'unknown'}`);
      continue;
    }

    try {
      const detail = fetchWorkbookDetail_(repoUrl);
      detailed.push(detail);
    } catch (e) {
      console.error(`Failed to fetch detail for '${repoUrl}': ${e.message}`);
    }

    if ((i + 1) % 50 === 0) {
      console.log(`Progress: ${i + 1} / ${workbooks.length} workbooks fetched`);
    }
  }

  console.log(`Successfully fetched details for ${detailed.length} workbooks`);
  return detailed;
}

function fetchCategories_(username) {
  const allItems = [];
  let start = 0;

  while (true) {
    const params = { startIndex: start, pageSize: CATEGORIES_PAGE_SIZE };
    const data = getJson_(`${BASE_URL_BFF}/author/${username}/categories`, params);

    if (!data) break;

    const items = data.workbooksWithCategories || [];
    if (items.length === 0) break;

    allItems.push(...items);
    console.log(`Fetched ${items.length} category items (total: ${allItems.length})`);

    if (items.length < CATEGORIES_PAGE_SIZE) break;

    start += CATEGORIES_PAGE_SIZE;
    Utilities.sleep(REQUEST_DELAY_MS);
  }

  return allItems;
}

function buildReactionMap_(categoryItems) {
  const reactionMap = {};
  for (const item of categoryItems) {
    const wb = item.workbook || {};
    const repoUrl = wb.workbookRepoUrl || '';
    if (repoUrl && !(repoUrl in reactionMap)) {
      reactionMap[repoUrl] = wb.reactionCounts || {};
    }
  }
  return reactionMap;
}

// ===================
// Data Extraction
// ===================

function extractMasterRow_(wb) {
  const defaultView = wb.defaultViewRepoUrl || '';
  const repoUrl = wb.workbookRepoUrl || '';
  let vizUrl = '';
  if (repoUrl && defaultView) {
    vizUrl = `https://public.tableau.com/views/${repoUrl}/${defaultView}`;
  }

  return {
    workbookRepoUrl: repoUrl,
    title: wb.title || '',
    description: wb.description || '',
    vizUrl: vizUrl,
    authorProfileName: wb.authorProfileName || '',
    firstPublishDate: wb.firstPublishDate || '',
    lastPublishDate: wb.lastPublishDate || '',
    lastUpdateDate: wb.lastUpdateDate || '',
    defaultViewName: wb.defaultViewName || '',
    defaultViewRepoUrl: defaultView,
    showTabs: wb.showTabs != null ? String(wb.showTabs) : '',
    showInProfile: wb.showInProfile != null ? String(wb.showInProfile) : '',
    revision: wb.revision != null ? String(wb.revision) : '',
    size: wb.size != null ? String(wb.size) : '',
    category: wb.category || '',
  };
}

function extractDailyRow_(wb, fetchDate, reactionMap) {
  const repoUrl = wb.workbookRepoUrl || '';
  const reactions = (reactionMap || {})[repoUrl] || {};

  const row = {
    fetchDate: fetchDate,
    workbookRepoUrl: repoUrl,
    title: wb.title || '',
    viewCount: wb.viewCount || 0,
    numberOfFavorites: wb.numberOfFavorites || 0,
    lastPublishDate: wb.lastPublishDate || '',
    lastUpdateDate: wb.lastUpdateDate || '',
    revision: wb.revision != null ? String(wb.revision) : '',
  };

  for (const rtype of REACTION_TYPES) {
    row[`reaction_${rtype}`] = reactions[rtype] || 0;
  }

  return row;
}

// ===================
// Sheets Writer
// ===================

function getOrCreateSheet_(spreadsheet, sheetName, headers) {
  let sheet = spreadsheet.getSheetByName(sheetName);
  if (!sheet) {
    sheet = spreadsheet.insertSheet(sheetName);
    sheet.appendRow(headers);
    console.log(`Created new sheet: ${sheetName}`);
  }
  return sheet;
}

function writeMasterSheet_(spreadsheet, masterRows) {
  const sheet = getOrCreateSheet_(spreadsheet, MASTER_SHEET_NAME, MASTER_HEADERS);

  sheet.clear();

  const rows = [MASTER_HEADERS];
  for (const rowDict of masterRows) {
    rows.push(MASTER_HEADERS.map(h => (rowDict[h] != null ? String(rowDict[h]) : '')));
  }

  if (sheet.getMaxRows() < rows.length) {
    sheet.insertRowsAfter(sheet.getMaxRows(), rows.length - sheet.getMaxRows());
  }

  sheet.getRange(1, 1, rows.length, MASTER_HEADERS.length).setValues(rows);
  console.log(`Updated master sheet with ${masterRows.length} workbooks`);
}

function writeDailySheet_(spreadsheet, yearMonth, dailyRows, fetchDate) {
  const sheetName = `daily_${yearMonth}`;
  const sheet = getOrCreateSheet_(spreadsheet, sheetName, DAILY_HEADERS);

  // Duplicate check
  const existing = sheet.getDataRange().getValues();
  const dateColIdx = DAILY_HEADERS.indexOf('fetchDate');
  const existingDates = new Set(
    existing.slice(1)
      .filter(row => row.length > dateColIdx)
      .map(row => String(row[dateColIdx]))
  );

  if (existingDates.has(fetchDate)) {
    console.log(`Data for ${fetchDate} already exists in ${sheetName}, skipping`);
    return;
  }

  const newRows = dailyRows.map(rowDict =>
    DAILY_HEADERS.map(h => (rowDict[h] != null ? rowDict[h] : ''))
  );

  // Expand if needed
  const neededRows = existing.length + newRows.length;
  if (sheet.getMaxRows() < neededRows) {
    sheet.insertRowsAfter(sheet.getMaxRows(), neededRows - sheet.getMaxRows() + 100);
  }

  // Append via setValues (batch write)
  const startRow = existing.length + 1;
  sheet.getRange(startRow, 1, newRows.length, DAILY_HEADERS.length).setValues(newRows);
  console.log(`Appended ${newRows.length} rows to ${sheetName} for date ${fetchDate}`);
}

// ===================
// Entry Point
// ===================

function main() {
  const username = PropertiesService.getScriptProperties().getProperty('TABLEAU_USERNAME');
  if (!username) {
    throw new Error('TABLEAU_USERNAME is required. Set it in Project Settings > Script Properties.');
  }

  // JST date
  const now = new Date();
  const fetchDate = Utilities.formatDate(now, 'Asia/Tokyo', 'yyyy-MM-dd');
  const yearMonth = Utilities.formatDate(now, 'Asia/Tokyo', 'yyyyMM');
  console.log(`Fetch date: ${fetchDate} (JST)`);

  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();

  // Fetch workbook data
  console.log(`Fetching workbook data for user: ${username}`);
  const workbooks = fetchAllWorkbookDetails_(username);

  if (workbooks.length === 0) {
    console.warn(`No workbooks found for user: ${username}`);
    return;
  }
  console.log(`Fetched ${workbooks.length} workbooks`);

  // Fetch reaction counts
  console.log('Fetching reaction counts from Categories API...');
  const categoryItems = fetchCategories_(username);
  const reactionMap = buildReactionMap_(categoryItems);
  console.log(`Built reaction map for ${Object.keys(reactionMap).length} workbooks`);

  // Prepare data
  const masterRows = workbooks.map(wb => extractMasterRow_(wb));
  const dailyRows = workbooks.map(wb => extractDailyRow_(wb, fetchDate, reactionMap));

  // Write to sheets
  writeMasterSheet_(spreadsheet, masterRows);
  writeDailySheet_(spreadsheet, yearMonth, dailyRows, fetchDate);

  console.log(`Done! Updated master sheet and appended daily stats for ${fetchDate}`);
}
