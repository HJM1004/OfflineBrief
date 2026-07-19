# OfflineBrief — Claudeへの作業指示

このリポジトリは「機内でオフラインで読むニュースブリーフ」を生成・公開するためのもの。
ユーザーが「今日のブリーフを作って」と言ったら、以下の手順でニュースを調査・執筆し、
Google Drive連携ツールで直接Google Driveに保存する。閲覧アプリ(`public/`)はその場でGAS
Web AppにアクセスしてJSONを取得して表示するため、**Driveへの保存が完了した瞬間に
閲覧アプリ側も自動的に最新版になる(ビルドやgit pushは不要)**。
**外部APIは使わない。ニュース調査はWebSearch/web_fetchで、執筆はClaude自身が行う。**

## 全体アーキテクチャ(2026年7月〜)

以前はcontent/にMarkdownをコミットし、scripts/build_site.pyで全日付を1つの静的HTMLにビルドし、
git push→GitHub Actions→GitHub Pagesという流れだった。現在は以下の構成に移行している。

- **データ層**: Claudeが「Google Drive連携ツール」(create_file等)を使い、当日分のMarkdownを
  `OfflineBrief/YYYY-MM-DD/YYYY-MM-DD_partNofM.md`(約45,000バイトごとの分割ファイル、詳細は
  下記「手順」参照)として直接Google Driveに保存する。
  **重要**: ClaudeのbashサンドボックスからはGoogle系ドメイン(script.google.com含む)への
  ネットワークアクセスがプロキシで遮断されており、curlでGAS Web Appへ直接POSTすることは
  できない。そのためデータの書き込みは必ずDrive連携ツール経由で行うこと(bashのcurlでは不可)。
  また1ファイルにまとめて送ろうとすると出力トークン上限を超えるため、必ず分割アップロードする。
- **配信層**: Google Apps Script Web App(`scripts/gas/Code.gs`、ユーザーがscript.google.com
  にデプロイ済み・読み取り専用)が、`doGet`リクエストに応じて上記Markdownをオンデマンドで
  解析し構造化JSONとして返す。書き込み(doPost)は行わない設計。
- **閲覧アプリ層**: `public/`(GitHub Pagesで公開)は薄いPWAシェルで、ページを開くたびにGAS Web App
  のURLへfetchし、日付一覧と選択中の日のJSONを取得して描画する。取得結果はブラウザのCache
  Storage APIにも保存されるため、一度オンラインで開いておけば、その後は機内などオフラインでも
  キャッシュされた内容を読める。
- **git/GitHub Pagesの役割**: 閲覧アプリのコード(`public/`)とGASスクリプトのソース
  (`scripts/gas/`)の管理のみ。**日々のニュースデータはgitにコミットしない**(Drive連携ツール経由で
  直接Driveに保存されるため)。`public/`が変わったとき(閲覧アプリの改修時)だけ
  `git add -A && git commit`し、pushはユーザーが行う。

GAS Web AppのURLは `.env`(gitignore済み、リポジトリ直下)に `GAS_WEB_APP_URL=...` の形で
保存されている想定。無ければユーザーに `scripts/gas/DEPLOY.md` の手順でデプロイしてもらい、
値を教えてもらうこと。**ユーザーから伝えられたURLが `script.googleusercontent.com/macros/echo?...`
という長いURLだった場合、それはブラウザがリダイレクトした後の値であり誤り。
`https://script.google.com/macros/s/.../exec` 形式の値を再度確認してもらうこと。**

## 手順

1. 各ジャンルのニュースをWeb検索で調査する(下記ジャンル構成)。長時間フライトでも読み応えがあるよう、総合・国際・経済・ビジネス・政治・行政・テック・科学・インフラ・都市・建築・環境の主要ジャンルは1ジャンルあたり約10本。インドネシア・タイ・マレーシア・東南アジア・ヨーロッパ・アメリカの国・地域別ジャンルは、その日実際に見つかるニュース量に応じて5〜10本程度でよい(本数を埋めるための無理な水増しはしない)。ジャンル数が多いため、Agentツールで複数ジャンルを分担させ並列調査すると効率的。並列実行後は、各ジャンルのファイル内容を実際に読み直し、見出し数などが期待通りかを検証してから次に進むこと(サブエージェントの完了報告を鵜呑みにしない)
2. 全ジャンルを **1つのMarkdown文字列**にまとめる(形式は下記)。ジャンルごとに `---\ngenre:...\n---` のfrontmatterブロックを連結する。事実は検索結果に基づき、出典URLを必ず付ける。推測は推測と明示
3. 同じMarkdownの末尾に「知的探究エッセイ」ブロック(`genre: 知的探究` / `slug: essays` / `order: 15`)を追加し、2〜3本書く。当日のニュースを入口に、歴史・科学・経済学・技術・都市論などへ思考を広げる約2000字の読み物。末尾に「さらに探究するには」としてキーワード・書籍を3〜5個
4. 作業用の一時ファイル(例: 作業ディレクトリの `brief.md`)にこのMarkdownを書き出し、見出し数・ジャンル数が期待通りかを実際に読み直して検証する
5. Google Drive連携ツール(`create_file`等)で、`OfflineBrief/YYYY-MM-DD/` フォルダ(なければ作成)に保存する。**重要: 1ファイルでまとめて保存しようとしないこと。** 実際の日次ブリーフ(150〜235KB程度の日本語Markdown)を`create_file`1回で送ろうとすると、Claudeの1応答あたりの出力トークン上限(64,000)を超え、書き込みが途中で切れて不完全なファイルが複数できてしまう(2026-07-15に実際に発生した障害)。そのため必ず以下の手順で分割アップロードすること。
   - まずbashで一時ファイル(`brief.md`)を1行ずつの改行境界を保ったまま約45,000バイトごとに分割する(例: Pythonで行単位に区切って結合し45,000バイトを超えたら次のパートに送る、といったスクリプトをその場で書いて実行する。ジャンルの区切りで割る必要はない、単純な行境界でよい)
   - 分割した各パートを `OfflineBrief/YYYY-MM-DD/YYYY-MM-DD_partNofM.md` (Nは1始まりの連番、Mは合計パート数、例: `2026-07-14_part1of5.md`)という名前で`create_file`により1パートずつ順にアップロードする。`disable_conversion_to_google_type: true` を必ず指定する
   - 各パートの`textContent`にはbashで分割したファイルの中身をそのまま渡す(Claudeが本文を新たに生成し直す必要はない。読み込んで渡すだけでも、tool呼び出しのパラメータとして出力する以上は出力トークンを消費するため、1パートは45,000バイト程度に収めること)
   - GAS側(`Code.gs`)は同じ日付フォルダ内に`YYYY-MM-DD.md`という単一ファイルがあればそれを優先し、なければ`_partNofM.md`ファイル群をパート番号順に結合してから解析する設計になっている(後方互換のため単一ファイル方式もサポート)
   - 同じ日付フォルダに古い失敗ファイル(中途半端な`YYYY-MM-DD.md`や、パート数の異なる`_partNofM.md`)が残っていると誤って読み込まれる可能性があるため、アップロード前にDrive上の対象フォルダを一覧し、紛らわしい古いファイルが残っていないか確認する。削除が必要な場合、Claude自身にはDriveのファイル削除ツールがないため、ユーザーに手動で削除してもらうよう依頼すること
6. 検証として、GAS Web AppのURL(`.env`の`GAS_WEB_APP_URL`)に対し `?date=YYYY-MM-DD` を付けてWebFetchツールでアクセスし、投稿した内容が正しく解析されて取得できることを確認する。**bashのcurlはGoogle系ドメインに到達できないため使わないこと**。WebFetchでも失敗する場合は、ユーザーに直接ブラウザでURLを開いて確認してもらう
7. `public/`や`scripts/gas/`のコードを変更した場合のみ `git add -A && git commit` する(pushはユーザーが行う)。日々のニュース投稿だけの場合はgit操作不要

## 閲覧アプリの仕組み(public/)

`public/index.html` はGAS Web AppのURL(`public/config.js`の`GAS_URL`)へ以下のようにアクセスする。

- パラメータなしでGET → `{"ok":true,"days":["2026-07-14","2026-07-09",...]}` のような日付一覧(降順)
- `?date=YYYY-MM-DD` でGET → その日の構造化JSON(`{"ok":true,"date":..., "genres":[{genre,slug,order,overview,sections:[{title,meta,body},...]}]}`)

取得したJSONはクライアント側のJavaScript(`mdToHtml`/`genreSectionHtml`/`essaysSectionHtml`)でHTMLに変換して描画する。日付セレクタ(`<select id="daySelect">`)で日付を切り替えると、その日のJSONを都度fetchし直す。取得に成功するたびCache Storage API(`caches.open('offlinebrief-data-v1')`)に保存されるため、次回以降オフラインでも同じ日を開ける。Service Worker(`public/sw.js`)は同一オリジンのアプリ本体(HTML/JS/CSS/アイコン)だけをキャッシュし、GAS Web Appへのクロスオリジンfetchはページ側のCache Storage処理に任せる(役割を分離している)。

## GASバックエンド(scripts/gas/) — 読み取り専用API

- `Code.gs`: `doGet`のみを実装。`?date=YYYY-MM-DD`が指定されれば`OfflineBrief/YYYY-MM-DD/`内の`YYYY-MM-DD.md`(単一ファイル、あれば優先)または`YYYY-MM-DD_partNofM.md`群(パート番号順に結合)を読み込み、Markdownパーサ(`scripts/build_site.py`のロジックをJS移植したもの)でオンデマンドに解析してJSONを返す。パラメータなしなら`OfflineBrief`直下の`YYYY-MM-DD`形式サブフォルダを一覧して日付一覧を返す。書き込みエンドポイント(doPost)は持たない(Claudeの実行環境からGoogle系ドメインへのネットワークアクセスができないため、そもそも使えない)
- `appsscript.json`: マニフェスト
- `DEPLOY.md`: 初回デプロイ手順(ユーザーが実施済み)。`Code.gs`を修正した場合は「デプロイを管理→新バージョン」で再デプロイが必要(URLは変わらない)
- `Code.gs`内の`ROOT_FOLDER_ID`(Driveの`OfflineBrief`フォルダID)は書き換え済みの想定

## ジャンル構成(ユーザーの関心)

| order | slug | genre | 調査観点 |
|---|---|---|---|
| 1 | general | 総合 | 国内の主要ニュース全般 |
| 2 | international | 国際 | 世界情勢、外交・紛争、国際関係(6〜11の個別国・地域ジャンルでカバーする話題は除く) |
| 3 | business | 経済・ビジネス | 経済、金融、企業動向 |
| 4 | politics | 政治・行政 | 国会・法案審議、内閣・与野党動向、外交・安全保障政策、地方行政 |
| 5 | tech | テック・科学 | 技術、AI、科学研究 |
| 6 | indonesia | インドネシア | 政治・経済・インフラ・社会情勢全般(ユーザーは八千代エンジニヤリング勤務。東南アジアのインフラ事業関連で業務関連度が高い) |
| 7 | thailand | タイ | 政治・経済・インフラ・社会情勢全般(業務関連) |
| 8 | malaysia | マレーシア | 政治・経済・インフラ・社会情勢全般(業務関連) |
| 9 | seasia | 東南アジア | インドネシア・タイ・マレーシア以外の東南アジア諸国(ベトナム、フィリピン、シンガポール等)の動向、ASEAN全体の話題 |
| 10 | europe | ヨーロッパ | 欧州の政治・経済・インフラ動向 |
| 11 | america | アメリカ | 米国の政治・経済・インフラ動向 |
| 12 | infra | インフラ・都市 | 国内の建設、交通、都市計画、エネルギー(業務関連) |
| 13 | architecture | 建築 | 建築デザイン、話題の建築物、都市開発事例、建築関連の技術・文化 |
| 14 | environment | 環境 | 気候変動、脱炭素、再生可能エネルギー、環境政策・規制 |
| 15 | essays | 知的探究 | エッセイ(上記ニュース派生) |

ジャンル追加の要望があればこの表を増やすだけでよい(Markdown側もブロックを追加するだけで、GAS・閲覧アプリ側の追加対応は不要)。国・地域別ジャンル(6〜11)は「その国・地域に関するニュース全般」を扱い、トピック別ジャンル(1〜5, 12〜14)は国内外を横断する話題を扱う、という住み分け。

## Markdown形式

1日分のMarkdownは、下記フォーマットのブロックをジャンル数だけ連結したもの。ブロックの区切りは「行頭の `---` の直後に `genre:` が続く箇所」で自動判定される(空行を1行挟んで連結すればよい)。この形式はGASの`Code.gs`が解析するため厳密に守ること。

```markdown
---
genre: 総合
slug: general
order: 1
---

> このジャンルの今日の概況を150〜250字で。

## 記事の見出し(本質を突いた言い換え可)
- source: NHK
- url: https://www3.nhk.or.jp/news/...
- date: 2026-07-05

事実の要約を150〜250字で。

**解説**
背景・文脈、なぜ重要か、今後の展望を400〜600字で。事実と推測を区別する。

---
genre: 国際
slug: international
order: 2
---
...(次のジャンルのブロックが続く。以降、経済・ビジネス→政治・行政→テック・科学→インドネシア→タイ→マレーシア→東南アジア→ヨーロッパ→アメリカ→インフラ・都市→建築→環境→知的探究、の順で連結)
```

- `slug: essays` のブロックは知的探究タブとして表示され、`## ` がエッセイ1本の区切り。メタは `- from: きっかけのニュース` のみ
- 本文で使えるMarkdown: `## / ###` 見出し、`**強調**`、`- 箇条書き`、`[リンク](url)`、段落(空行区切り)

## ライフログ(予定・ToDo・メモ)アシスタント — 2026年7月〜

ニュースブリーフとは別に、このリポジトリには「予定・ToDo・メモ管理アシスタント」(LifeLog)も
含まれる。ユーザーが予定・やること・思いつきについて話したら、Claudeは以下のプロトコルで動く。

### 構成

- **予定**: Googleカレンダー本体をGoogle Calendar連携ツール(`list_events`/`create_event`/
  `update_event`/`delete_event`/`suggest_time`)で直接読み書きする。独自の予定データは持たない
- **ToDo・メモの正本**: Driveの `LifeLog/state.json`(タスク配列+メモ配列)。
  このファイルを更新するのは**LifeLog用GAS Web App**(`scripts/gas-life/Code.gs`、
  OfflineBriefとは別プロジェクトとしてデプロイ)だけ
- **Claudeからの書き込み**: DriveツールはファイルのUPDATEができない(create/read/searchのみ)ため、
  Claudeは `LifeLog/inbox/` にミューテーションJSONを`create_file`で置く(下記形式)。
  GASがdoGet/doPostのたびにinboxを取り込み、`state.json`に適用して `LifeLog/processed/` へ移動する
- **PWA**: `public/life/`(GitHub Pages `/life/`)。閲覧+スマホからの直接入力(GAS doPost)。
  オフラインではキャッシュ閲覧+未送信キューに書き溜めて再接続時に自動送信
- **認証**: GASのスクリプトプロパティ `LIFELOG_TOKEN`。`.env`(リポジトリ直下、gitignore済み)に
  `GAS_LIFE_URL=...` と `LIFELOG_TOKEN=...` がある想定。無ければ `scripts/gas-life/DEPLOY.md` の
  手順でユーザーにデプロイしてもらう

### Claudeの読み取り手順

最新状態は **WebFetchツール**で `GAS_LIFE_URL?token=LIFELOG_TOKEN` をGETして取得する
(inbox取り込み済みのstate+カレンダー14日分が返る。bashのcurlはGoogle系ドメイン不可)。
WebFetchが使えない場合の代替: Driveツールで `LifeLog/state.json` を読む(+`LifeLog/inbox/`に
未処理ファイルがないか確認)。カレンダーはGoogle Calendarツールで直接読む。

### Claudeの書き込み手順(ToDo・メモ)

1. ミューテーションJSONを組み立てる:
   ```json
   {"mutations": [
     {"op": "add_task", "task": {"id": "t-<ユニーク値>", "title": "...", "due": "YYYY-MM-DD", "priority": "high|normal|low", "project": "", "tags": [], "notes": ""}},
     {"op": "complete_task", "id": "t-..."},
     {"op": "update_task", "id": "t-...", "patch": {"due": "..."}},
     {"op": "delete_task", "id": "t-..."},
     {"op": "add_memo", "memo": {"id": "m-<ユニーク値>", "text": "...", "category": "", "tags": []}},
     {"op": "update_memo", "id": "m-...", "patch": {"status": "organized", "category": "アイデア"}},
     {"op": "delete_memo", "id": "m-..."}
   ]}
   ```
   - add系は自分で `id` を生成して入れる(例: `t-20260719-a1b2`)。同じidの再投入は上書きになる
     ため二重取り込みされても安全
   - メモの `status`: `inbox`(未整理)→`organized`(整理済み)→`archived`
2. Driveツール`create_file`で `LifeLog/inbox/` フォルダに
   `YYYYMMDD-HHMMSS_claude.json`(タイムスタンプ順に処理される)として保存。
   `contentMimeType: "application/json"`、`disable_conversion_to_google_type: true` を指定
3. WebFetchで `GAS_LIFE_URL?token=...` をGETし、inboxが取り込まれて反映されたことを確認する
   (このGET自体が取り込みのトリガーになる)

### アシスタントとしての振る舞い

- **予定の相談**(「来週の空きは?」「◯◯を入れて」)→ Calendarツールで直接操作。日時・所要時間が
  曖昧なら確認してから登録する
- **やることの発生**(「〜しなきゃ」「あとで〜する」)→ add_taskへ。期限・優先度を会話から推定し、
  推定したことを明示する
- **思いつき・アイデア**→ add_memoへ。そのまま書き、勝手に要約しすぎない
- **「メモを整理して」**→ inboxステータスのメモを読み、(1)実はタスクならadd_task化して
  update_memoでorganized+カテゴリ付与、(2)アイデア・参考情報ならカテゴリ(自由語彙: アイデア/
  仕事/読みたい/買う物 など)とタグを付けてorganizedに、(3)不要と思われるものは勝手に消さず
  ユーザーに提案する
- **「今日のまとめ」「朝のブリーフ」**→ カレンダー+期限切れ・今日のタスク+未整理メモ件数を
  まとめて提示し、今日の段取りを提案する
- ToDo・メモの日常操作でgit操作は不要。`public/life/`や`scripts/gas-life/`のコード変更時のみコミット

## 注意

- 過去分(2026-07-05〜2026-07-09)は`content/`にMarkdownとして残っている。`content/`はもうgit管理の対象外(.gitignore済み)。ローカルでの下書き・検証用の作業場所として使ってよいが、コミットはしない
- `public/`は現在ビルド生成物ではなく手書きの閲覧アプリ本体なのでコミット対象(以前の`.gitignore`ルールから変更済み)
- **bashのcurlはGoogle系ドメイン(script.google.com、googleapis.com等)に到達できない(プロキシのallowlistでブロックされている)。日々のデータ保存は必ずGoogle Drive連携ツール(create_file等)を使うこと。動作確認もbashのcurlではなくWebFetchツールを使う**
- `scripts/build_site.py`と`.github/workflows/build-brief.yml`の旧ロジックは参考用として残っているが、日々の運用では使わない
