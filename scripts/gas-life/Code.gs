/**
 * LifeLog — 予定・ToDo・メモ管理アシスタントのGASバックエンド
 *
 * OfflineBrief(scripts/gas/Code.gs)とは別のGASプロジェクトとしてデプロイする。
 * デプロイ手順は scripts/gas-life/DEPLOY.md を参照。
 *
 * アーキテクチャ:
 *  - 正本データはDriveの LifeLog/state.json (このスクリプトだけが更新する)
 *    { version, updatedAt, tasks:[...], memos:[...], log:[...] }
 *  - 書き込み経路は2つ:
 *      (1) PWA(public/life/)からの doPost({token, mutations:[...]})
 *      (2) Claude(Drive連携ツール。既存ファイルの上書きができないため
 *          create_fileのみ)が LifeLog/inbox/ に置くJSONファイル
 *          { "mutations": [...] } — doGet/doPostのたびに取り込み、
 *          処理済みファイルは LifeLog/processed/ へ移動する
 *    Claudeのサンドボックスからはscript.google.comへPOSTできない(プロキシ遮断)
 *    ため、(2)のinbox方式がClaude側の唯一の書き込み経路。
 *  - 読み取りは doGet(?token=...) が inbox取り込み後の最新stateと、
 *    Googleカレンダー(デフォルトカレンダー)の直近予定をまとめて返す。
 *    PWAはこのJSONをCache Storageに保存し、機内などオフラインでも閲覧できる。
 *
 * 認証:
 *  ToDo・メモは個人情報のため、OfflineBrief(公開ニュース)と違い共有トークンで保護する。
 *  スクリプトプロパティ LIFELOG_TOKEN に任意のランダム文字列を設定し、
 *  全リクエストに token パラメータ(GET)または token フィールド(POSTボディ)を要求する。
 */

// ==================== 設定 ====================

// LifeLogフォルダを名前で探す(マイドライブ直下)。IDで固定したい場合は
// ROOT_FOLDER_ID にフォルダIDを設定する(設定されていれば名前検索より優先)。
var ROOT_FOLDER_NAME = 'LifeLog';
var ROOT_FOLDER_ID = '1IKsH8GQw0JWCEjIAm3SMW2tl0eCqjc8B'; // マイドライブ直下のLifeLogフォルダ(2026-07-19作成)

var STATE_FILE_NAME = 'state.json';
var INBOX_FOLDER_NAME = 'inbox';
var PROCESSED_FOLDER_NAME = 'processed';

// カレンダーの取得範囲: 昨日0時 〜 14日後まで
var CALENDAR_PAST_DAYS = 1;
var CALENDAR_FUTURE_DAYS = 14;

// ==================== フォルダ・ファイル操作 ====================

// DriveApp.getFoldersByName()は検索インデックス経由で作成直後のフォルダを
// 取りこぼすことがある(OfflineBriefで2026-07-16に実際に発生)ため、
// 直接列挙+名前比較で探す。
function findChildFolderByName_(parent, name) {
  var it = parent.getFolders();
  while (it.hasNext()) {
    var f = it.next();
    if (f.getName() === name) return f;
  }
  return null;
}

function getOrCreateChildFolder_(parent, name) {
  return findChildFolderByName_(parent, name) || parent.createFolder(name);
}

function getRoot_() {
  if (ROOT_FOLDER_ID) return DriveApp.getFolderById(ROOT_FOLDER_ID);
  var root = DriveApp.getRootFolder();
  return getOrCreateChildFolder_(root, ROOT_FOLDER_NAME);
}

// state.jsonを探す。複数あれば最終更新が最新のものを採用。
function findStateFile_(root) {
  var it = root.getFiles();
  var best = null;
  while (it.hasNext()) {
    var f = it.next();
    if (f.getName() !== STATE_FILE_NAME) continue;
    if (!best || f.getLastUpdated() > best.getLastUpdated()) best = f;
  }
  return best;
}

function defaultState_() {
  return { version: 1, updatedAt: '', tasks: [], memos: [], log: [] };
}

function loadState_(root) {
  var file = findStateFile_(root);
  if (!file) return defaultState_();
  try {
    var state = JSON.parse(file.getBlob().getDataAsString('UTF-8'));
    if (!state || typeof state !== 'object') return defaultState_();
    state.tasks = state.tasks || [];
    state.memos = state.memos || [];
    state.log = state.log || [];
    return state;
  } catch (e) {
    // 壊れたstateは読み捨てて空から再開(inbox/processedに履歴は残る)
    return defaultState_();
  }
}

function saveState_(root, state) {
  state.updatedAt = new Date().toISOString();
  var json = JSON.stringify(state);
  var file = findStateFile_(root);
  if (file) {
    file.setContent(json);
  } else {
    root.createFile(STATE_FILE_NAME, json, 'application/json');
  }
}

// ==================== 認証 ====================

function checkToken_(token) {
  var stored = PropertiesService.getScriptProperties().getProperty('LIFELOG_TOKEN');
  if (!stored) throw new Error('LIFELOG_TOKEN is not set in Script Properties (see DEPLOY.md)');
  if (!token || String(token) !== stored) throw new Error('unauthorized');
}

// ==================== ミューテーション ====================

function nowIso_() {
  return new Date().toISOString();
}

function genId_(prefix) {
  return prefix + '-' + Date.now().toString(36) + '-' + Math.floor(Math.random() * 1e8).toString(36);
}

function findById_(arr, id) {
  for (var i = 0; i < arr.length; i++) {
    if (arr[i].id === id) return i;
  }
  return -1;
}

function logPush_(state, msg) {
  state.log.unshift({ t: nowIso_(), msg: String(msg) });
  if (state.log.length > 30) state.log.length = 30;
}

// 1件のミューテーションをstateに適用する。inboxファイルが二重に処理されても
// 破綻しないよう、idが既に存在するadd系は「置き換え」として扱う。
function applyMutation_(state, m) {
  if (!m || !m.op) return;
  var idx;
  switch (m.op) {
    case 'add_task': {
      var t = m.task || {};
      var title = String(t.title || '').trim();
      if (!title) return;
      var task = {
        id: t.id || genId_('t'),
        title: title,
        status: 'open',
        due: t.due || '',           // 'YYYY-MM-DD' or ''
        priority: t.priority || 'normal', // 'high' | 'normal' | 'low'
        project: t.project || '',
        tags: t.tags || [],
        notes: t.notes || '',
        createdAt: t.createdAt || nowIso_(),
        completedAt: ''
      };
      idx = findById_(state.tasks, task.id);
      if (idx >= 0) state.tasks[idx] = task; else state.tasks.push(task);
      break;
    }
    case 'update_task': {
      idx = findById_(state.tasks, m.id);
      if (idx < 0) return;
      var patch = m.patch || {};
      for (var k in patch) {
        if (k !== 'id') state.tasks[idx][k] = patch[k];
      }
      break;
    }
    case 'complete_task': {
      idx = findById_(state.tasks, m.id);
      if (idx < 0) return;
      state.tasks[idx].status = 'done';
      state.tasks[idx].completedAt = nowIso_();
      break;
    }
    case 'reopen_task': {
      idx = findById_(state.tasks, m.id);
      if (idx < 0) return;
      state.tasks[idx].status = 'open';
      state.tasks[idx].completedAt = '';
      break;
    }
    case 'delete_task': {
      idx = findById_(state.tasks, m.id);
      if (idx >= 0) state.tasks.splice(idx, 1);
      break;
    }
    case 'add_memo': {
      var mm = m.memo || {};
      var text = String(mm.text || '').trim();
      if (!text) return;
      var memo = {
        id: mm.id || genId_('m'),
        text: text,
        status: mm.status || 'inbox', // 'inbox'(未整理) | 'organized'(整理済み) | 'archived'
        category: mm.category || '',  // Claudeの整理で付与(アイデア/参考/日記 など自由)
        tags: mm.tags || [],
        createdAt: mm.createdAt || nowIso_()
      };
      idx = findById_(state.memos, memo.id);
      if (idx >= 0) state.memos[idx] = memo; else state.memos.push(memo);
      break;
    }
    case 'update_memo': {
      idx = findById_(state.memos, m.id);
      if (idx < 0) return;
      var mpatch = m.patch || {};
      for (var mk in mpatch) {
        if (mk !== 'id') state.memos[idx][mk] = mpatch[mk];
      }
      break;
    }
    case 'delete_memo': {
      idx = findById_(state.memos, m.id);
      if (idx >= 0) state.memos.splice(idx, 1);
      break;
    }
    default:
      logPush_(state, 'unknown op: ' + m.op);
  }
}

// ==================== inbox取り込み(Claudeからの書き込み) ====================

function ingestInbox_(root, state) {
  var inbox = getOrCreateChildFolder_(root, INBOX_FOLDER_NAME);
  var processed = getOrCreateChildFolder_(root, PROCESSED_FOLDER_NAME);
  var it = inbox.getFiles();
  var files = [];
  while (it.hasNext()) files.push(it.next());
  // ファイル名先頭のタイムスタンプで時系列順に適用する
  files.sort(function (a, b) { return a.getName() < b.getName() ? -1 : 1; });
  files.forEach(function (f) {
    try {
      var data = JSON.parse(f.getBlob().getDataAsString('UTF-8'));
      var muts = (data && data.mutations) || [];
      muts.forEach(function (m) { applyMutation_(state, m); });
      logPush_(state, 'ingested ' + f.getName() + ' (' + muts.length + ' mutations)');
    } catch (e) {
      logPush_(state, 'ingest FAILED ' + f.getName() + ': ' + e);
    }
    f.moveTo(processed);
  });
  return files.length;
}

// ==================== カレンダー ====================

function getCalendarEvents_() {
  var now = new Date();
  var start = new Date(now.getTime() - CALENDAR_PAST_DAYS * 86400000);
  start.setHours(0, 0, 0, 0);
  var end = new Date(now.getTime() + CALENDAR_FUTURE_DAYS * 86400000);
  end.setHours(23, 59, 59, 999);
  try {
    var events = CalendarApp.getDefaultCalendar().getEvents(start, end).map(function (ev) {
      return {
        id: ev.getId(),
        title: ev.getTitle(),
        start: ev.getStartTime().toISOString(),
        end: ev.getEndTime().toISOString(),
        allDay: ev.isAllDayEvent(),
        location: ev.getLocation() || ''
      };
    });
    return { ok: true, rangeStart: start.toISOString(), rangeEnd: end.toISOString(), events: events };
  } catch (e) {
    // カレンダー権限が未承認でもToDo・メモは使えるようにする
    return { ok: false, error: String(e), events: [] };
  }
}

// ==================== エントリポイント ====================

function doGet(e) {
  var params = (e && e.parameter) || {};
  try {
    checkToken_(params.token);
    if (params.action === 'ping') return jsonOutput_({ ok: true, pong: true });

    var lock = LockService.getScriptLock();
    lock.waitLock(20000);
    try {
      var root = getRoot_();
      var state = loadState_(root);
      var ingested = ingestInbox_(root, state);
      if (ingested > 0) saveState_(root, state);
      return jsonOutput_({ ok: true, state: state, calendar: getCalendarEvents_() });
    } finally {
      lock.releaseLock();
    }
  } catch (err) {
    return jsonOutput_({ ok: false, error: String((err && err.message) || err) });
  }
}

// PWAからの書き込み。CORSプリフライトを避けるため、クライアントは
// Content-Type: text/plain でJSON文字列をPOSTする。
// ボディ: { "token": "...", "mutations": [ ... ] }
function doPost(e) {
  try {
    var body = {};
    if (e && e.postData && e.postData.contents) {
      body = JSON.parse(e.postData.contents);
    }
    checkToken_(body.token || (e && e.parameter && e.parameter.token));

    var muts = body.mutations || [];
    var lock = LockService.getScriptLock();
    lock.waitLock(20000);
    try {
      var root = getRoot_();
      var state = loadState_(root);
      ingestInbox_(root, state);
      muts.forEach(function (m) { applyMutation_(state, m); });
      saveState_(root, state);
      return jsonOutput_({ ok: true, applied: muts.length, state: state, calendar: getCalendarEvents_() });
    } finally {
      lock.releaseLock();
    }
  } catch (err) {
    return jsonOutput_({ ok: false, error: String((err && err.message) || err) });
  }
}

function jsonOutput_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

// ==================== 動作確認用(スクリプトエディタから手動実行) ====================
// 初回はこれを実行してDrive/カレンダーのアクセス権限を承認しておくこと。

function _test_state() {
  var root = getRoot_();
  var state = loadState_(root);
  ingestInbox_(root, state);
  saveState_(root, state);
  Logger.log(JSON.stringify(state, null, 2));
  Logger.log(JSON.stringify(getCalendarEvents_()));
}
