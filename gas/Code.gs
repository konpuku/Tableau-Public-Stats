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
 *
 * Parallel fetch:
 *   Uses UrlFetchApp.fetchAll() to batch detail API requests.
 *   400 workbooks complete in ~30s instead of ~5min.
 *
 * Continuation:
 *   If execution nears the time limit, progress is saved and a one-off
 *   trigger resumes automatically within 1 minute.
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

/** Number of detail requests sent in one fetchAll() call. */
const DETAIL_BATCH_SIZE = 50;

/** Stop fetching details when remaining time drops below this (ms). */
const TIME_LIMIT_BUFFER_MS = 60 * 1000; // 60s safety margin

/** GAS execution limit (ms). Free: 6min, Workspace: 30min. */
const EXECUTION_LIMIT_MS = 6 * 60 * 1000;

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

/** Script Properties key for continuation state. */
const STATE_KEY = 'CONTINUATION_STATE';

// ===================
// HTTP Helpers
// ===================

/**
 * Single GET request with retry.
 */
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

/**
 * Parallel GET requests via UrlFetchApp.fetchAll().
 * Returns an array of parsed JSON (null for failed requests).
 */
function getJsonBatch_(urls) {
  const requests = urls.map(url => ({
    url: url,
    muteHttpExceptions: true,
  }));

  const responses = UrlFetchApp.fetchAll(requests);

  return responses.map((resp, i) => {
    try {
      const code = resp.getResponseCode();
      if (code >= 200 && code < 300) {
        return JSON.parse(resp.getContentText());
      }
      console.warn(`Batch request failed for ${urls[i]}: HTTP ${code}`);
      return null;
    } catch (e) {
      console.warn(`Failed to parse response for ${urls[i]}: ${e.message}`);
      return null;
    }
  });
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

/**
 * Fetch workbook details in parallel batches using fetchAll().
 *
 * @param {string[]} repoUrls - List of workbookRepoUrl to fetch.
 * @param {number}   startIdx - Index to resume from (for continuation).
 * @param {Date}     deadline - Stop before this time and save state.
 * @returns {{ detailed: object[], nextIdx: number|null }}
 *   nextIdx is null if all done, otherwise the index to resume from.
 */
function fetchWorkbookDetailsBatch_(repoUrls, startIdx, deadline) {
  const detailed = [];
  let i = startIdx;

  while (i < repoUrls.length) {
    // Check time budget before starting a new batch
    if (new Date() >= deadline) {
      console.warn(`Approaching time limit at index ${i}/${repoUrls.length}, saving state...`);
      return { detailed, nextIdx: i };
    }

    const batchEnd = Math.min(i + DETAIL_BATCH_SIZE, repoUrls.length);
    const batchUrls = repoUrls.slice(i, batchEnd).map(
      repoUrl => `${BASE_URL_PROFILE}/single_workbook/${repoUrl}`
    );

    const results = getJsonBatch_(batchUrls);

    for (let j = 0; j < results.length; j++) {
      if (results[j]) {
        detailed.push(results[j]);
      } else {
        console.warn(`Failed to fetch detail for '${repoUrls[i + j]}'`);
      }
    }

    console.log(`Detail batch done: ${batchEnd} / ${repoUrls.length}`);
    i = batchEnd;

    // Brief pause between batches to avoid rate limiting
    if (i < repoUrls.length) {
      Utilities.sleep(REQUEST_DELAY_MS);
    }
  }

  return { detailed, nextIdx: null };
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
// Continuation State
// ===================

function saveState_(state) {
  PropertiesService.getScriptProperties().setProperty(STATE_KEY, JSON.stringify(state));
}

function loadState_() {
  const raw = PropertiesService.getScriptProperties().getProperty(STATE_KEY);
  return raw ? JSON.parse(raw) : null;
}

function clearState_() {
  PropertiesService.getScriptProperties().deleteProperty(STATE_KEY);
}

/**
 * Schedule a one-off trigger to call main() in ~1 minute.
 */
function scheduleResume_() {
  ScriptApp.newTrigger('main')
    .timeBased()
    .after(1 * 60 * 1000)
    .create();
  console.log('Scheduled continuation trigger (1 min)');
}

/**
 * Delete any one-off triggers for main() created by continuation.
 * Called at the end of a successful complete run.
 */
function cleanupTriggers_() {
  const triggers = ScriptApp.getProjectTriggers();
  for (const trigger of triggers) {
    if (trigger.getHandlerFunction() === 'main'
        && trigger.getTriggerSource() === ScriptApp.TriggerSource.CLOCK
        && trigger.getEventType() === ScriptApp.EventType.CLOCK) {
      // Only delete after-style triggers (one-off), not daily recurring ones.
      // after() triggers appear as CLOCK / CLOCK and don't have a specific hour.
      try {
        ScriptApp.deleteTrigger(trigger);
      } catch (e) {
        // Ignore - might be the daily trigger
      }
    }
  }
}

// ===================
// Entry Point
// ===================

function main() {
  const startTime = new Date();
  const deadline = new Date(startTime.getTime() + EXECUTION_LIMIT_MS - TIME_LIMIT_BUFFER_MS);

  const username = PropertiesService.getScriptProperties().getProperty('TABLEAU_USERNAME');
  if (!username) {
    throw new Error('TABLEAU_USERNAME is required. Set it in Project Settings > Script Properties.');
  }

  const now = new Date();
  const fetchDate = Utilities.formatDate(now, 'Asia/Tokyo', 'yyyy-MM-dd');
  const yearMonth = Utilities.formatDate(now, 'Asia/Tokyo', 'yyyyMM');

  // --- Check for continuation state ---
  const saved = loadState_();

  let repoUrls;
  let detailedSoFar;
  let resumeIdx;

  if (saved && saved.fetchDate === fetchDate) {
    // Resuming a previous run
    repoUrls = saved.repoUrls;
    detailedSoFar = saved.detailed;
    resumeIdx = saved.nextIdx;
    console.log(`Resuming from index ${resumeIdx}/${repoUrls.length} (${detailedSoFar.length} already fetched)`);
  } else {
    // Fresh run
    if (saved) {
      console.log('Stale continuation state found, discarding');
      clearState_();
    }

    console.log(`Fetch date: ${fetchDate} (JST)`);
    console.log(`Fetching workbook list for user: ${username}`);

    const workbooks = fetchWorkbookList_(username);
    if (workbooks.length === 0) {
      console.warn(`No workbooks found for user: ${username}`);
      return;
    }

    repoUrls = workbooks
      .map(wb => wb.workbookRepoUrl || '')
      .filter(url => url !== '');
    console.log(`Found ${repoUrls.length} workbooks to fetch details for`);

    detailedSoFar = [];
    resumeIdx = 0;
  }

  // --- Fetch workbook details in parallel batches ---
  const { detailed: newDetailed, nextIdx } = fetchWorkbookDetailsBatch_(
    repoUrls, resumeIdx, deadline
  );
  const allDetailed = detailedSoFar.concat(newDetailed);

  if (nextIdx !== null) {
    // Time ran out — save state and schedule continuation
    console.warn(`Time limit approaching. Fetched ${allDetailed.length}/${repoUrls.length}. Saving state...`);
    saveState_({
      fetchDate: fetchDate,
      repoUrls: repoUrls,
      detailed: allDetailed,
      nextIdx: nextIdx,
    });
    scheduleResume_();
    return;
  }

  // --- All details fetched — continue to categories + write ---
  clearState_();
  console.log(`Fetched all ${allDetailed.length} workbook details`);

  // Fetch reaction counts
  console.log('Fetching reaction counts from Categories API...');
  const categoryItems = fetchCategories_(username);
  const reactionMap = buildReactionMap_(categoryItems);
  console.log(`Built reaction map for ${Object.keys(reactionMap).length} workbooks`);

  // Prepare data
  const masterRows = allDetailed.map(wb => extractMasterRow_(wb));
  const dailyRows = allDetailed.map(wb => extractDailyRow_(wb, fetchDate, reactionMap));

  // Write to sheets
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  writeMasterSheet_(spreadsheet, masterRows);
  writeDailySheet_(spreadsheet, yearMonth, dailyRows, fetchDate);

  cleanupTriggers_();

  const elapsed = ((new Date() - startTime) / 1000).toFixed(1);
  console.log(`Done! ${allDetailed.length} workbooks processed in ${elapsed}s`);
}
