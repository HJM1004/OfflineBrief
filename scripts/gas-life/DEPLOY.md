# LifeLog GAS Web App デプロイ手順

予定・ToDo・メモ管理(LifeLog)用のバックエンド。**OfflineBriefのGASプロジェクトとは別に、
新しいGASプロジェクトとして作成する**(既存のニュース配信APIに影響を与えないため)。

## 1. GASプロジェクトの作成

1. https://script.google.com/ を開き「新しいプロジェクト」を作成
2. プロジェクト名を「LifeLog」などに変更
3. エディタの `コード.gs` にこのフォルダの `Code.gs` の内容を貼り付け
4. 「プロジェクトの設定」(歯車)→「『appsscript.json』マニフェスト ファイルをエディタで表示する」
   にチェックを入れ、エディタに現れた `appsscript.json` をこのフォルダの `appsscript.json` の内容で置き換え

## 2. 認証トークンの設定(重要)

ToDo・メモは個人情報のため、共有トークンでアクセスを保護する。

1. 「プロジェクトの設定」(歯車)→「スクリプト プロパティ」→「スクリプト プロパティを追加」
2. プロパティ名: `LIFELOG_TOKEN`
   値: 推測されにくいランダムな文字列(例: パスワードマネージャで32文字生成)
3. 保存

このトークンは後で閲覧アプリ(PWA)の初回設定画面と、リポジトリ直下の `.env` に入力する。

## 3. 初回実行(権限承認)

1. エディタ上部の関数選択で `_test_state` を選んで「実行」
2. 「承認が必要です」と出るので、自分のGoogleアカウントで
   **Google Drive**(state.json等の読み書き)と **Googleカレンダー**(予定の読み取り)を承認
3. 実行ログに `{"version":1,...}` のようなJSONが出れば成功。
   このときマイドライブ直下に `LifeLog/` フォルダ(なければ)と `LifeLog/state.json` が自動作成される

※ マイドライブ直下以外に `LifeLog` フォルダを置きたい場合は、フォルダIDを
`Code.gs` 冒頭の `ROOT_FOLDER_ID` に設定する。

## 4. Web Appとしてデプロイ

1. 右上「デプロイ」→「新しいデプロイ」
2. 種類: 「ウェブアプリ」
3. 設定:
   - 次のユーザーとして実行: **自分**
   - アクセスできるユーザー: **全員**(匿名アクセス。データ自体はトークンで保護される)
4. 「デプロイ」を押し、表示される **ウェブアプリのURL**(`https://script.google.com/macros/s/.../exec`)をコピー

※ ブラウザで開いた後の `script.googleusercontent.com/macros/echo?...` はリダイレクト後のURLなので使わないこと。

## 5. URLとトークンの登録

1. リポジトリ直下の `.env`(gitignore済み)に追記:
   ```
   GAS_LIFE_URL=https://script.google.com/macros/s/.../exec
   LIFELOG_TOKEN=(手順2で設定した値)
   ```
   Claudeがアシスタントとして状態確認(WebFetch)する際に使う。
2. スマホ/PCで閲覧アプリ `https://<GitHub PagesのURL>/life/` を開き、
   初回設定画面にWeb AppのURLとトークンを入力(端末のlocalStorageにのみ保存される)

## 6. 動作確認

ブラウザで以下を開いてJSONが返ればOK:

```
<ウェブアプリのURL>?token=<LIFELOG_TOKEN>&action=ping
→ {"ok":true,"pong":true}

<ウェブアプリのURL>?token=<LIFELOG_TOKEN>
→ {"ok":true,"state":{...},"calendar":{...}}
```

## Code.gsを修正したとき

「デプロイ」→「デプロイを管理」→ 鉛筆アイコン →「バージョン: 新バージョン」→「デプロイ」。
URLは変わらない。

## セキュリティ上の注意

- トークン(`LIFELOG_TOKEN`)はgitにコミットしない(`.env`はgitignore済み、
  `public/life/config.js` にも書かない — GitHub Pagesで全世界に公開されるため)
- トークンが漏れた場合はスクリプトプロパティの値を変更すれば即座に無効化できる
  (PWA側の設定画面と `.env` も更新する)
