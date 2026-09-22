# tmux-session-manager

VaioU上のtmuxセッションを一覧表示し、セッションごとにメモ（何の作業か）を付けて管理するツール。
CLI版（`tm`）とブラウザで見られるWebダッシュボード版（`web.py`）がある。

詳しい仕様は [SPEC.md](SPEC.md) を参照。

## CLI（tm）セットアップ

`~/.local/bin/tm` にシンボリックリンクを張って使う（`~/.local/bin`はPATH済み想定）。

```bash
chmod +x ~/github/tmux-session-manager/tm.py
ln -sf ~/github/tmux-session-manager/tm.py ~/.local/bin/tm
```

## 使い方

```bash
tm                                # 一覧表示 → 番号入力でアタッチ（対話モード）
tm list                           # 一覧表示のみ
tm attach <番号|名前>              # 指定セッションにアタッチ（既存クライアントと共有）
tm attach <番号|名前> --takeover    # 他のクライアントを切り離して奪取
tm new <名前> [メモ]               # 新規セッション作成＋メモ登録
tm memo <番号|名前> "<メモ>"        # メモ更新
tm rm <番号|名前>                  # メモ削除（セッションは残す）
tm gc                             # 存在しないセッションのメモを一括削除（確認あり）
tm save                           # 現在のセッション構成を ~/.config/tm/sessions.toml に保存
tm restore                        # 定義ファイルを元に、無いセッションだけ作り直す（冪等）
```

メモは `~/sync/logs/tmux-sessions_notes.json` にセッション名をキーとして保存される（Synology Drive同期でMac側にも共有される）。

## 前提：セッションはサーバー側のもの、再起動で消える

tmuxセッションはVaioU（サーバー）側のtmuxサーバー上に存在し、特定のクライアント
（Mac/Windowsのターミナル）には紐づいていません。**手元のアプリやSSH接続が切れても
セッションはそのまま残ります。**

ただし、**VaioU自体を再起動するとtmuxサーバーごとセッションが全て消えます**
（メモリ上のプロセスのため）。再起動後も残したい常用セッションは`tm save`で
`~/.config/tm/sessions.toml`に登録しておき、`tm restore`で復元します。

```toml
[[session]]
name = "kyoto-kacho"
dir = "~/github/clients/kyoto-kacho"
cmd = ""            # 起動直後に流すコマンド（省略可）
```

`tm restore`が復元できるのは**名前・作業ディレクトリ・初期コマンドの構成まで**で、
走っていたプロセスの状態（vimの編集内容など）までは戻らない。同名セッションが
既に存在する場合はスキップする（冪等・何度実行しても安全）。

### 起動時の自動復元（tm-restore.service）

`tm-restore.service`（systemdユーザーサービス、`Type=oneshot`）が起動時に
`tm restore`を1回実行する。`kadai-kanri`・`tm-web`と同様、`loginctl enable-linger`が
有効になっている前提（SSHしていない間もsystemd --userとtmuxサーバーを生かしておくため。
このマシンでは既に有効）。

```bash
ln -sf ~/github/tmux-session-manager/deploy/tm-restore.service ~/.config/systemd/user/tm-restore.service
systemctl --user daemon-reload
systemctl --user enable tm-restore.service
```

| やりたいこと | コマンド |
|---|---|
| 手動で今すぐ実行 | `systemctl --user start tm-restore` |
| 実行結果を見る | `tail -f ~/github/tmux-session-manager/tm-restore.log` |

## Webダッシュボード（web.py）

Tailscale経由でブラウザから状態確認・メモ編集ができる。実際のターミナル接続はブラウザ内では
行わず、SSH接続コマンドをボタンでコピーして手元のターミナルに貼り付ける方式（tmuxサーバーは
VaioU側で独立して動くため、ダッシュボードやブラウザが落ちてもセッションには影響しない）。

```
http://mtb-linux:8765
```

Tailscaleアドレス（`100.74.222.40:8765`）にのみバインドしており、tailnet外（社内LAN等）からは
届かない。systemdユーザーサービス（`tm-web.service`）として常駐しており、VaioU起動時に自動復帰する。

| やりたいこと | コマンド |
|---|---|
| 状態を見る | `systemctl --user status tm-web` |
| コード更新後の反映 | `systemctl --user restart tm-web` |
| 止める | `systemctl --user stop tm-web` |
| ログ | `tail -f ~/github/tmux-session-manager/web.log` |
