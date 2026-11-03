/**
 * Pivotal Property Analysis: "Analyze" button.
 *
 * Reads the King County parcel number (APN) from Inputs!B4, or the street address from B3, asks the
 * property agent service to analyze it with the rules in the "Rules" tab, and writes the answers into
 * the agreed input cells of the Inputs tab only.
 * - Formulas are never overwritten: a cell holding a formula is skipped and reported.
 * - Cells the agent is unsure of ("check") or could not fill ("missing") turn red with a note.
 * - Every written cell gets a note with its source link.
 * - The master template is never written to: make a copy first.
 *
 * Setup (once): Extensions > Apps Script > Project Settings > Script Properties:
 *   SERVICE_URL    e.g. https://pivotal-agent.up.railway.app
 *   SERVICE_TOKEN  the same secret as PIVOTAL_SERVICE_TOKEN on Railway
 * or use the menu Pivotal > Set up connection.
 */

var INPUTS_SHEET = 'Inputs';
var APN_CELL = 'B4';
var ADDRESS_CELL = 'B3';
var RULES_SHEET = 'Rules';
// The only cells the agent may write. Everything else (formulas, other tabs) is left alone.
var INPUT_CELLS = ['B3', 'B6', 'B7', 'B11', 'B12', 'B13', 'B14', 'B16', 'B21', 'B23', 'B25', 'B26',
                   'B39', 'B40', 'B41', 'B42', 'B43', 'B44', 'B45', 'B50', 'B51'];
var NUMBER_CELLS = ['B6', 'B7', 'B14', 'B40', 'B41', 'B42', 'B43', 'B44', 'B45', 'B50', 'B51'];
var FLAG_COLOR = '#f4cccc';   // red: a person should look at this cell
var INPUT_COLOR = '#fff2cc';  // the template's normal input-cell yellow
var POLL_EVERY_MS = 5000;
var GIVE_UP_AFTER_MS = 5 * 60 * 1000;  // Apps Script stops any run at 6 minutes
var MAX_POLL_ERRORS = 4;

function onOpen() {
  SpreadsheetApp.getUi().createMenu('Pivotal')
    .addItem('Analyze property (APN in B4 or address in B3)', 'analyzeProperty')
    .addSeparator()
    .addItem('Create Rules tab', 'createRulesTab')
    .addItem('Set up connection', 'setUpConnection')
    .addToUi();
}

/** Assign this function to the Analyze button (Insert > Drawing > ⋮ > Assign script). */
function analyzeProperty() {
  var ui = SpreadsheetApp.getUi();
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  if (/\(Template\)/i.test(ss.getName())) {
    ui.alert('This is the master template. Make a copy (File > Make a copy) and analyze in the copy.');
    return;
  }
  var sheet = ss.getSheetByName(INPUTS_SHEET);
  if (!sheet) {
    ui.alert('No "' + INPUTS_SHEET + '" tab in this file.');
    return;
  }
  var target = readTarget_(sheet);
  if (!target) {
    var answer = ui.prompt('Analyze property', 'King County parcel number or street address:',
                           ui.ButtonSet.OK_CANCEL);
    if (answer.getSelectedButton() !== ui.Button.OK) return;
    target = toTarget_(answer.getResponseText());
    if (!target) return;
  }
  var settings = getSettings_();
  if (!settings) return;

  var rules = readRules_(ss);
  ss.toast('Analyzing ' + (target.apn || target.address) + '… this takes about a minute.', 'Pivotal', 120);
  var result;
  try {
    var jobId = startJob_(settings, target, rules);
    result = waitForJob_(settings, jobId);
  } catch (err) {
    ui.alert('Analysis failed', String(err.message || err), ui.ButtonSet.OK);
    return;
  }
  var report = writeCells_(sheet, result);
  ss.toast('Done.', 'Pivotal', 3);
  ui.alert('Analysis finished',
    report.written + ' cells written, ' + report.flagged + ' flagged red for a check.\n' +
    (report.skipped.length ? 'Skipped (formula in cell): ' + report.skipped.join(', ') + '\n' : '') +
    'Rules used: ' + (result.rules_source || 'built-in rules') + '.\n' +
    'Run time ' + result.seconds + ' s, cost about $' + result.cost_usd + '.',
    ui.ButtonSet.OK);
}

function setUpConnection() {
  var ui = SpreadsheetApp.getUi();
  var props = PropertiesService.getScriptProperties();
  var url = ui.prompt('Service URL', 'e.g. https://pivotal-agent.up.railway.app', ui.ButtonSet.OK_CANCEL);
  if (url.getSelectedButton() !== ui.Button.OK) return;
  var token = ui.prompt('Service token', 'The PIVOTAL_SERVICE_TOKEN set on Railway', ui.ButtonSet.OK_CANCEL);
  if (token.getSelectedButton() !== ui.Button.OK) return;
  props.setProperties({
    SERVICE_URL: url.getResponseText().trim().replace(/\/+$/, ''),
    SERVICE_TOKEN: token.getResponseText().trim()
  });
  ui.alert('Saved. Use Pivotal > Analyze property.');
}

// ---------- helpers ----------

/** B4: the APN or the county Parcel Viewer link (…ParcelNbr=XXXXXXXXXX). Otherwise B3: an address. */
function readTarget_(sheet) {
  var raw = String(sheet.getRange(APN_CELL).getValue() || '').trim();
  var fromLink = raw.match(/ParcelNbr=(\d{9,10})/i);
  if (fromLink) return { apn: fromLink[1] };
  var digits = raw.replace(/[\s-]/g, '');
  if (/^\d{9,10}$/.test(digits)) return { apn: digits };
  var address = String(sheet.getRange(ADDRESS_CELL).getValue() || '').trim();
  return /^\d+\s+\S/.test(address) ? { address: address } : null;
}

/** Typed text: 10 digits = parcel number; anything starting with a house number = address. */
function toTarget_(text) {
  var value = String(text || '').trim();
  var digits = value.replace(/[\s-]/g, '');
  if (/^\d{9,10}$/.test(digits)) return { apn: digits };
  if (/^\d+\s+\S/.test(value)) return { address: value };
  SpreadsheetApp.getUi().alert('"' + value + '" is not a parcel number (10 digits) or a street address.');
  return null;
}

/** The Rules tab's text (one rule per row, any column), or '' to use the service's built-in rules. */
function readRules_(ss) {
  var rulesSheet = ss.getSheetByName(RULES_SHEET);
  if (!rulesSheet) return '';
  return rulesSheet.getDataRange().getDisplayValues()
    .map(function (row) { return row.filter(String).join(' '); })
    .join('\n').trim();
}

/** Menu: make a Rules tab filled with the built-in rules, ready to edit. Run it in the master template. */
function createRulesTab() {
  var ui = SpreadsheetApp.getUi();
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  if (ss.getSheetByName(RULES_SHEET)) {
    ui.alert('There is already a "' + RULES_SHEET + '" tab. Edit it directly.');
    return;
  }
  var settings = getSettings_();
  if (!settings) return;
  var rules;
  try {
    rules = callService_(settings, 'get', '/rules').rules;
  } catch (err) {
    ui.alert('Could not load the rules', String(err.message || err), ui.ButtonSet.OK);
    return;
  }
  var lines = rules.split('\n').map(function (line) { return [line]; });
  var rulesSheet = ss.insertSheet(RULES_SHEET);
  rulesSheet.getRange(1, 1, lines.length, 1).setNumberFormat('@').setValues(lines).setWrap(true);
  rulesSheet.setColumnWidth(1, 900);
  ui.alert('Rules tab created. Edit the text in plain English; the next Analyze uses it.');
}

function getSettings_() {
  var props = PropertiesService.getScriptProperties();
  var url = props.getProperty('SERVICE_URL');
  var token = props.getProperty('SERVICE_TOKEN');
  if (!url || !token) {
    SpreadsheetApp.getUi().alert('Not connected yet. Use Pivotal > Set up connection first.');
    return null;
  }
  return { url: url, token: token };
}

function callService_(settings, method, path, body) {
  var options = {
    method: method,
    contentType: 'application/json',
    headers: { 'X-Pivotal-Token': settings.token },
    muteHttpExceptions: true
  };
  if (body) options.payload = JSON.stringify(body);
  var response = UrlFetchApp.fetch(settings.url + path, options);
  var code = response.getResponseCode();
  var data = {};
  try { data = JSON.parse(response.getContentText()); } catch (e) { /* not JSON */ }
  if (code >= 400) {
    var why = data.detail || ('the service answered ' + code);
    if (code === 401) why = 'The service token is wrong. Use Pivotal > Set up connection.';
    throw new Error(typeof why === 'string' ? why : JSON.stringify(why));
  }
  return data;
}

function startJob_(settings, target, rules) {
  var body = { apn: target.apn || null, address: target.address || null, rules: rules || null };
  return callService_(settings, 'post', '/analyze', body).job_id;
}

function waitForJob_(settings, jobId) {
  var started = Date.now();
  var errorsInARow = 0;
  while (Date.now() - started < GIVE_UP_AFTER_MS) {
    Utilities.sleep(POLL_EVERY_MS);
    var job;
    try {
      job = callService_(settings, 'get', '/jobs/' + jobId);
      errorsInARow = 0;
    } catch (err) {   // a network blip or a restarting service: try a few more times
      errorsInARow += 1;
      if (errorsInARow >= MAX_POLL_ERRORS) throw err;
      continue;
    }
    if (job.status === 'done') return job.result;
    if (job.status === 'failed') throw new Error(job.error || 'The analysis failed.');
  }
  throw new Error('No answer after 5 minutes. Try again; if it repeats, check the service log on Railway.');
}

/** Write only the agreed input cells; never a formula. Returns counts for the summary. */
function writeCells_(sheet, result) {
  var report = { written: 0, flagged: 0, skipped: [] };
  var stamp = 'Agent ' + Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd HH:mm');

  var apnCell = sheet.getRange(APN_CELL);
  if (!apnCell.getFormula()) {
    apnCell.setValue(result.parcel_viewer_url);
  }

  result.cells.forEach(function (item) {
    if (INPUT_CELLS.indexOf(item.cell) === -1) return;   // never outside the agreed cells
    var range = sheet.getRange(item.cell);
    if (range.getFormula()) {
      report.skipped.push(item.cell);
      return;
    }
    var flagged = item.status === 'check' || item.status === 'missing';
    if (item.status !== 'missing') {
      range.setValue(toCellValue_(item.cell, item.value));
      report.written += 1;
    }
    var note = [stamp + ' · ' + item.status.toUpperCase()];
    if (item.status === 'missing' && range.getValue() !== '') {
      note.push('The value shown is left from before; the agent could not confirm it.');
    }
    if (item.note) note.push(item.note);
    if (item.source_url) note.push('Source: ' + item.source_url);
    range.setNote(note.join('\n'));
    if (flagged) {
      range.setBackground(FLAG_COLOR);
      report.flagged += 1;
    } else if (range.getBackground() === FLAG_COLOR) {
      range.setBackground(INPUT_COLOR);   // clear an old red flag, back to the template's yellow
    }
  });
  return report;
}

/** Numbers as numbers; any text that a sheet would read as a formula is kept as plain text. */
function toCellValue_(cell, value) {
  var text = String(value).trim();
  if (NUMBER_CELLS.indexOf(cell) !== -1) {
    var number = Number(text.replace(/,/g, ''));
    if (text !== '' && !isNaN(number)) return number;
  }
  return /^[=+\-@]/.test(text) ? "'" + text : text;
}
