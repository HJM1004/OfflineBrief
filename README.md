# ✈ OfflineBrief — 機内オフラインブリーフ

搭乗前にCowork(Claude)に「今日のブリーフを作って」と頼むと、Claudeが最新ニュースを調査し、
解説と「知的探究エッセイ」をMarkdownで執筆。pushするとGitHub Pagesに公開され、
機内でオフラインのまま読めるPWA(Webアプリ)になります。**APIキー不要・追加コストゼロ。**

## 仕組み

```
Cowork「今日のブリーフ作って」
   → Claudeがニュース調査+content/YYYY-MM-DD/*.md を執筆+コミット
   → あなたが git push
   → GitHub Actionsが build_site.py でPWAをビルド → Pagesへ自動公開
```

ページを一度オンラインで開けば、Service Workerが全コンテンツをキャッシュ。機内モードでも閲覧できます。

## 初期セットアップ(1回だけ)

1. GitHubに新しいリポジトリを作成し、このフォルダをpush(コミット済み)

   ```bash
   cd C:\ClaudeData\OfflineBrief
   git remote add origin https://github.com/<あなたのユーザー名>/offline-brief.git
   git push -u origin main
   ```

2. **Pagesを有効化**: リポジトリの Settings → Pages → Source を「**GitHub Actions**」に設定

APIキーやSecretsの設定は不要です。

## 使い方(搭乗前の流れ)

1. Coworkでこのフォルダを開き「**今日のブリーフを作って**」と依頼(手順は `CLAUDE.md` に定義済み)
2. 完了したら `git push`
3. 1〜2分でActionsが完了 → `https://<ユーザー名>.github.io/offline-brief/` をスマホで開き、全タブ表示されるのを確認
   - iPhoneなら「ホーム画面に追加」しておくとアプリのように開けます
4. 機内モードにしても、そのまま読めます

## カスタマイズ

- **ジャンルの追加・変更**: `CLAUDE.md` のジャンル表を編集(Claudeへの指示がそのまま仕様)
- **デザイン**: `scripts/build_site.py` 内のCSSを編集
- **コンテンツの手直し**: `content/YYYY-MM-DD/*.md` を直接編集してpushすれば再ビルドされます

## ローカルでのプレビュー

```bash
python scripts/build_site.py   # 依存パッケージ不要
# public/index.html をブラウザで開く
```

## 注意

- 解説・エッセイはClaudeが執筆したもので、誤りを含む可能性があります。各記事の出典リンクから原文を確認できます(オンライン時)
- Publicリポジトリの場合、生成ページは誰でも閲覧可能です。Privateにしても Pages を有効化すればページURLは公開されます(GitHub Freeの仕様)
