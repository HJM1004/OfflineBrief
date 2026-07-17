/**
 * OfflineBrief — Google Apps Script バックエンド(読み取り専用版)
 *
 * 経緯:
 *  当初はdoPostでClaudeからMarkdownを受け取る設計だったが、Claudeの実行環境(サンドボックス)
 *  からはGoogleの各種ドメインへのネットワークアクセスがプロキシで遮断されており、
 *  curl等でこのWeb Appへ直接POSTすることができないと判明した。
 *  そのためClaudeは「Google Drive連携ツール」を使って、当日分のMarkdownを
 *  OfflineBrief/YYYY-MM-DD/YYYY-MM-DD.md として直接Driveに保存する。
 *  このスクリプトはその保存されたMarkdownを読み取り、閲覧アプリ(public/)からの
 *  fetchに応じてオンデマンドで解析・配信する「読み取り専用API」として働く。
 *
 *  2026-07-15追記: 実際の日次ブリーフ(150〜235KB程度の日本語Markdown)を
 *  Drive連携ツールのcreate_file呼び出し1回で送ろうとすると、Claude側の
 *  1応答あたりの出力トークン上限を超えてしまい、書き込みが途中で切れる
 *  (=不完全なファイルが複数できる)ことが判明した。そのためClaudeは1日分を
 *  約45,000バイトずつの複数ファイルに分割し、
 *    OfflineBrief/YYYY-MM-DD/YYYY-MM-DD_partNofM.md  (N=1..M)
 *  という名前で連番アップロードする方式に変更した。このスクリプトはpart
 *  ファイル群をパート番号順に結合してから、従来通りのMarkdownパーサに渡す。
 *  なお、1ファイルで収まる場合(例: 2026-07-05.mdのように過去に単一ファイルで
 *  保存されたもの)にも後方互換のため対応し、そちらを優先的に探す。
 *
 * doGet:
 *   ?date=YYYY-MM-DD → OfflineBrief/YYYY-MM-DD/ 以下のMarkdown(単一ファイル
 *                       またはpartNofM分割ファイル)を結合・解析して構造化JSONを返す
 *   (パラメータなし)  → OfflineBrief直下のYYYY-MM-DD形式サブフォルダを一覧し、日付一覧を返す
 *
 * デプロイ方法は scripts/gas/DEPLOY.md を参照。
 */

// ==================== 設定 ====================

// OfflineBriefフォルダのDrive ID。
// Google Driveでフォルダを開いたときのURL
//   https://drive.google.com/drive/folders/【ここがID】
// の【ここがID】部分をコピーして書き換えてください。
var ROOT_FOLDER_ID = '1i7-h9yAQYMqzceYpu6CN5BxLazin7wdA';

var DATE_FOLDER_RE = /^\d{4}-\d{2}-\d{2}$/;

// ==================== フォルダ操作ヘルパー ====================

function getRootFolder_() {
  return DriveApp.getFolderById(ROOT_FOLDER_ID);
}

function findDateFolders_() {
  var root = getRootFolder_();
  var it = root.getFolders();
  var names = [];
  while (it.hasNext()) {
    var f = it.next();
    if (DATE_FOLDER_RE.test(f.getName())) names.push(f.getName());
  }
  names.sort();
  names.reverse();
  return names;
}

// 単一ファイル(date + '.md')を探す。複数ヒットした場合は最終更新が最も新しい
// ものを採用する(過去の書き損じファイルが残っていても、最新の正しいものを
// 優先するため)。
function readSingleFile_(folder, date) {
  var files = folder.getFilesByName(date + '.md');
  var best = null;
  while (files.hasNext()) {
    var f = files.next();
    if (!best || f.getLastUpdated() > best.getLastUpdated()) best = f;
  }
  return best;
}

// date_partNofM.md 形式のファイル群を集め、パート番号(N)順に結合する。
// 同じNが複数存在する場合(アップロードのやり直し等)は最終更新が新しい方を
// 採用する。Mが食い違うファイルが混在していても、拾えたパートを番号順に
// 単純結合するベストエフォート方式(古いテスト用ファイルなどはこの命名規則に
// 一致しない限り無視される)。
function readPartFiles_(folder, date) {
  var re = new RegExp('^' + date.replace(/[-]/g, '\\-') + '_part(\\d+)of(\\d+)\\.md$');
  var it = folder.getFiles();
  var byPart = {}; // partNumber -> file (最新優先)
  while (it.hasNext()) {
    var f = it.next();
    var m = re.exec(f.getName());
    if (!m) continue;
    var n = parseInt(m[1], 10);
    if (!byPart[n] || f.getLastUpdated() > byPart[n].getLastUpdated()) {
      byPart[n] = f;
    }
  }
  var partNumbers = Object.keys(byPart).map(Number).sort(function (a, b) { return a - b; });
  if (partNumbers.length === 0) return null;
  var texts = partNumbers.map(function (n) {
    return byPart[n].getBlob().getDataAsString('UTF-8');
  });
  return texts.join('\n');
}

// フォルダ名で子フォルダを探す。DriveApp.getFoldersByName()はDriveの検索インデックス
// 経由のため、作成直後のフォルダが見つからないことがある(2026-07-16に実際に発生した
// 障害: 直後にdate一覧には出るのに ?date= 個別取得だけ "not found" になった)。
// findDateFolders_と同じgetFolders()の直接列挙+名前比較に統一し、この遅延を回避する。
function findDateFolder_(date) {
  var root = getRootFolder_();
  var it = root.getFolders();
  while (it.hasNext()) {
    var f = it.next();
    if (f.getName() === date) return f;
  }
  return null;
}

function readMarkdownForDate_(date) {
  var folder = findDateFolder_(date);
  if (!folder) return null;

  // 1) 単一ファイルがあればそれを優先(後方互換: 2026-07-05.md等)
  var single = readSingleFile_(folder, date);
  if (single) return single.getBlob().getDataAsString('UTF-8');

  // 2) なければ分割ファイル(_partNofM.md)を結合
  var joined = readPartFiles_(folder, date);
  if (joined !== null) return joined;

  return null;
}

// ==================== Markdownパーサ ====================
// scripts/build_site.py の parse_front_matter / split_genre_blocks / parse_block を
// そのままJavaScriptに移植したもの。フォーマット仕様はCLAUDE.mdを参照。

function parseFrontMatter_(text) {
  var meta = {};
  var body = text;
  var m = text.match(/^\s*---\s*\n([\s\S]*?)\n---\s*\n/);
  if (m) {
    m[1].split('\n').forEach(function (line) {
      var idx = line.indexOf(':');
      if (idx >= 0) {
        var k = line.slice(0, idx).trim();
        var v = line.slice(idx + 1).trim();
        meta[k] = v;
      }
    });
    body = text.slice(m[0].length);
  }
  return { meta: meta, body: body };
}

function splitGenreBlocks_(text) {
  var re = /^---[ \t]*\r?\n(?=genre\s*:)/gm;
  var starts = [];
  var mm;
  while ((mm = re.exec(text)) !== null) {
    starts.push(mm.index);
  }
  if (starts.length === 0) return [text];
  starts.push(text.length);
  var blocks = [];
  for (var i = 0; i < starts.length - 1; i++) {
    blocks.push(text.slice(starts[i], starts[i + 1]));
  }
  return blocks;
}

function parseBlock_(text, fallbackName) {
  var fm = parseFrontMatter_(text);
  var meta = fm.meta;
  var body = fm.body;

  var lines = body.split('\n');
  var overviewLines = [];
  var restLines = [];
  var seenSection = false;
  for (var i = 0; i < lines.length; i++) {
    var line = lines[i];
    if (line.indexOf('## ') === 0) seenSection = true;
    if (!seenSection && line.trim().indexOf('>') === 0) {
      overviewLines.push(line.trim().replace(/^>\s*/, ''));
    } else {
      restLines.push(line);
    }
  }

  var sections = [];
  var current = null;
  for (var j = 0; j < restLines.length; j++) {
    var l = restLines[j];
    if (l.indexOf('## ') === 0) {
      current = { title: l.slice(3).trim(), meta: {}, bodyLines: [], inHead: true };
      sections.push(current);
      continue;
    }
    if (current === null) continue;
    var s = l.trim();
    var mm2 = s.match(/^-\s*(source|url|date|from)\s*:\s*(.+)$/);
    if (current.inHead && (mm2 || s === '')) {
      if (mm2) current.meta[mm2[1]] = mm2[2].trim();
      continue;
    }
    current.inHead = false;
    current.bodyLines.push(l);
  }

  var order = parseInt(meta.order || '99', 10);
  if (isNaN(order)) order = 99;

  return {
    genre: meta.genre || fallbackName,
    slug: meta.slug || (fallbackName.replace(/\W+/g, '') || 'sec'),
    order: order,
    overview: overviewLines.filter(function (l) { return l; }).join(' '),
    sections: sections.map(function (s) {
      return { title: s.title, meta: s.meta, body: s.bodyLines.join('\n').trim() };
    }),
  };
}

function parseMarkdown_(text, baseName) {
  var blocks = splitGenreBlocks_(text);
  return blocks.map(function (b, i) {
    return parseBlock_(b, i ? baseName + '_' + i : baseName);
  });
}

// ==================== doGet: データ配信 ====================

function doGet(e) {
  var params = (e && e.parameter) || {};

  if (params.date) {
    var date = params.date;
    if (!DATE_FOLDER_RE.test(date)) {
      return jsonOutput_({ ok: false, error: 'invalid date (expected YYYY-MM-DD)' });
    }
    var markdown = readMarkdownForDate_(date);
    if (markdown === null) {
      return jsonOutput_({ ok: false, error: 'not found: ' + date });
    }
    var genres = parseMarkdown_(markdown, date).sort(function (a, b) {
      return a.order - b.order;
    });
    return jsonOutput_({ ok: true, date: date, genres: genres });
  }

  // パラメータなし: 日付一覧を返す
  return jsonOutput_({ ok: true, days: findDateFolders_() });
}

function jsonOutput_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

// ==================== 動作確認用(スクリプトエディタから手動実行) ====================

function _test_listDays() {
  Logger.log(JSON.stringify(findDateFolders_()));
}

function _test_getDate() {
  var days = findDateFolders_();
  if (!days.length) {
    Logger.log('no date folders found');
    return;
  }
  var fakeE = { parameter: { date: days[0] } };
  Logger.log(doGet(fakeE).getContent());
}
