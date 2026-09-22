# AI Sessions (tm) — VS Code拡張機能

CodexとClaude CodeのtmuxセッションをVS Codeのサイドバーから一覧・状態確認・アタッチするための拡張機能（プロトタイプ版）。
既存の[`tm`](../README.md)（CLI/Webダッシュボード）と同じメモファイル（`~/sync/logs/tmux-sessions_notes.json`）を共有する。

## できること（MVP）

- サイドバーにホスト（ローカル／SSH先）ごとのtmuxセッション一覧をツリー表示
- 各セッションの状態を自動判定して色分け表示
  - 🟢 実行中／🟡 承認待ち／⚪ 待機中／🔴 接続切れ・状態不明
  - 判定方法: `tmux capture-pane`の直近数行を正規表現でパターンマッチ（承認待ちプロンプトらしき文字列）。
    マッチしなければ最終アクティビティ時刻からの経過時間で実行中/待機中を推定。
    **ヒューリスティックのため誤判定はあり得る**（仕様検討時に指摘した「状態不明へのフォールバック」を実装）
- セッションをクリック（または右クリック→アタッチ）でVS Code統合ターミナルに`ssh -t <host> tmux attach`（ローカルは`tmux attach`）を実行
- サイドバー右上の＋ボタンで新規セッション作成（メモ付き）
- 右クリックでメモを編集

## セットアップ

```bash
cd vscode-extension
npm install
npm run compile
```

VS Codeでこのフォルダを開き、`F5`（「拡張機能のデバッグ実行」）で拡張機能開発ホストが起動する。

## 設定（`settings.json`）

```json
{
  "tmSessions.hosts": [
    { "label": "ローカル" },
    { "label": "mtb-linux (SSH)", "ssh": "mtb-linux" }
  ],
  "tmSessions.memoPath": "~/sync/logs/tmux-sessions_notes.json",
  "tmSessions.pollIntervalSec": 5
}
```

- `ssh`には`~/.ssh/config`のHost名、または`user@host`を指定する
- SSH接続には鍵認証（パスワード入力なし）が前提。`ssh mtb-linux`が手動で通ることを先に確認すること

## 今回のスコープ外（次にやること）

- ブラウザ/Webview内への実ターミナル埋め込み（VS Code標準の統合ターミナルで代用）
- Codex/Claude Code間の作業引き継ぎ（結果のコピー＆送信）
- 承認待ち判定パターンの精度向上（実際のプロンプト文言に合わせた調整が必要）
- SSH認証情報の管理UI（現状は`~/.ssh/config`任せ）
- `.vsix`パッケージ化・Marketplace非公開配布

## 動作確認状況

TypeScriptのコンパイルは通ることを確認済み（`npm run compile`）。
実機（VS Code上での起動・実際のtmux/SSHに対する動作）は未確認 — 手元のVS Codeで`F5`起動して確認してください。
