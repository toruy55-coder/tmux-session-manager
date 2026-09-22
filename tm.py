#!/usr/bin/env python3
"""tmuxセッションの一覧表示・メモ管理・アタッチを行うCLIツール。"""

import os
import subprocess
import sys

import tm_core as core


def print_rows(rows):
    if not rows:
        print("tmuxセッションはありません。`tm new <名前>` で作成できます。")
        return
    print(f"{'#':>3} {'状態':^6} {'セッション名':<20} {'作業ディレクトリ':<30} {'最終操作':<8} メモ")
    print("-" * 100)
    for r in rows:
        status = "●接続中" if r["attached"] else "○切断中"
        memo = r["memo"] if r["memo"] else "(メモなし)"
        print(f"{r['index']:>3} {status:^6} {r['name']:<20} {r['path']:<30} {r['activity_rel']:<8} {memo}")


def cmd_list():
    print_rows(core.build_rows())


def cmd_interactive():
    rows = core.build_rows()
    print_rows(rows)
    if not rows:
        return
    try:
        choice = input("\nアタッチする番号を入力（Enterで何もしない）: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if not choice:
        return
    name = core.resolve_target(choice, rows)
    if name is None:
        print(f"'{choice}' に該当するセッションが見つかりません。", file=sys.stderr)
        sys.exit(1)
    do_attach(name)


def do_attach(name, takeover=False):
    if takeover:
        os.execvp("tmux", ["tmux", "attach-session", "-d", "-t", name])
    else:
        os.execvp("tmux", ["tmux", "attach-session", "-t", name])


def cmd_attach(target, takeover=False):
    rows = core.build_rows()
    name = core.resolve_target(target, rows)
    if name is None:
        print(f"'{target}' に該当するセッションが見つかりません。", file=sys.stderr)
        sys.exit(1)
    do_attach(name, takeover=takeover)


def cmd_new(name, memo):
    if not name:
        try:
            name = input("セッション名: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not name:
            print("セッション名が空です。中止しました。", file=sys.stderr)
            sys.exit(1)

    existing = {s["name"] for s in core.tmux_sessions()}
    if name in existing:
        print(f"セッション '{name}' は既に存在します。`tm attach {name}` を使ってください。", file=sys.stderr)
        sys.exit(1)

    if memo is None:
        try:
            memo = input("メモ（省略可）: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            memo = ""

    result = subprocess.run(["tmux", "new-session", "-d", "-s", name])
    if result.returncode != 0:
        print(f"tmuxセッションの作成に失敗しました。", file=sys.stderr)
        sys.exit(1)

    if memo:
        core.set_memo(name, memo)

    print(f"セッション '{name}' を作成しました。アタッチする場合は `tm attach {name}`")


def cmd_memo(target, memo_text):
    rows = core.build_rows()
    name = core.resolve_target(target, rows)
    if name is None:
        print(f"'{target}' に該当するセッションが見つかりません。", file=sys.stderr)
        sys.exit(1)
    core.set_memo(name, memo_text)
    print(f"'{name}' のメモを更新しました。")


def cmd_rm(target):
    rows = core.build_rows()
    name = core.resolve_target(target, rows)
    key = name if name is not None else target
    if not core.delete_memo(key):
        print(f"'{target}' のメモは見つかりません。", file=sys.stderr)
        sys.exit(1)
    print(f"'{key}' のメモを削除しました（tmuxセッション自体は削除していません）。")


def cmd_save():
    current = core.current_session_defs()
    if not current:
        print("動いているtmuxセッションがありません。保存する内容がありません。")
        return
    previous = core.load_session_defs()
    merged = core.merge_session_defs(current, previous)
    core.save_session_defs(merged)
    print(f"{len(merged)}件のセッション構成を {core.SESSIONS_PATH} に保存しました。")
    print("保存されるのは名前・作業ディレクトリ・初期コマンドの構成のみで、実行中のプロセスの中身は含まれません。")


def cmd_restore():
    if not os.path.exists(core.SESSIONS_PATH):
        print(f"定義ファイル {core.SESSIONS_PATH} がありません。先に `tm save` するか、手動で作成してください。")
        return
    created, skipped = core.restore_sessions()
    if created:
        print(f"作成: {', '.join(created)}")
    if skipped:
        print(f"既存のためスキップ: {', '.join(skipped)}")
    if not created and not skipped:
        print("定義ファイルにセッションが登録されていません。")


def cmd_gc():
    orphans = core.orphan_notes()
    if not orphans:
        print("削除対象のメモはありません。")
        return
    print("以下のメモは対応するtmuxセッションが存在しないため削除できます:")
    for name, memo in orphans.items():
        print(f"  - {name}: {memo}")
    try:
        answer = input("削除しますか？ [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if answer != "y":
        print("中止しました。")
        return
    for name in orphans:
        core.delete_memo(name)
    print(f"{len(orphans)}件のメモを削除しました。")


def main():
    args = sys.argv[1:]
    if not args:
        cmd_interactive()
        return

    sub = args[0]
    rest = args[1:]

    if sub == "list":
        cmd_list()
    elif sub in ("attach", "at"):
        takeover = "--takeover" in rest
        positional = [a for a in rest if a != "--takeover"]
        if not positional:
            print("使い方: tm attach <番号|名前> [--takeover]", file=sys.stderr)
            sys.exit(1)
        cmd_attach(positional[0], takeover=takeover)
    elif sub == "save":
        cmd_save()
    elif sub == "restore":
        cmd_restore()
    elif sub == "new":
        name = rest[0] if len(rest) >= 1 else None
        memo = rest[1] if len(rest) >= 2 else None
        cmd_new(name, memo)
    elif sub == "memo":
        if len(rest) < 2:
            print("使い方: tm memo <番号|名前> \"<メモ>\"", file=sys.stderr)
            sys.exit(1)
        cmd_memo(rest[0], rest[1])
    elif sub == "rm":
        if not rest:
            print("使い方: tm rm <番号|名前>", file=sys.stderr)
            sys.exit(1)
        cmd_rm(rest[0])
    elif sub == "gc":
        cmd_gc()
    elif sub in ("-h", "--help", "help"):
        print(__doc__)
        print("""
使い方:
  tm                          一覧表示 → 番号入力でアタッチ（対話モード）
  tm list                     一覧表示のみ
  tm attach <番号|名前>        指定セッションにアタッチ（既存クライアントとの共有。`tm at`でも可）
  tm attach <番号|名前> --takeover  他のクライアントを切り離して奪取
  tm new <名前> [メモ]         新規セッション作成＋メモ登録
  tm memo <番号|名前> "<メモ>"  メモ更新
  tm rm <番号|名前>            メモ削除（セッションは残す）
  tm gc                       存在しないセッションのメモを一括削除（確認あり）
  tm save                     現在のセッション構成を ~/.config/tm/sessions.toml に保存
  tm restore                  定義ファイルを元に、無いセッションだけ作り直す（冪等）

前提:
  tmuxセッションはVaioU（サーバー）側のtmuxサーバー上に存在し、特定のクライアント
  （Mac/Windowsのターミナル）には紐づいていません。手元のアプリやSSH接続が切れても
  セッションはそのまま残ります。
  ただし、VaioU自体の再起動ではtmuxサーバーごとセッションが全て消えます（メモリ上の
  プロセスのため）。再起動後も残したい常用セッションは `tm save` で登録し、
  `tm restore` （systemdサービスで起動時に自動実行）で復元してください。
  `tm restore` が復元できるのは名前・作業ディレクトリ・初期コマンドの構成までで、
  中で動いていたプロセスの状態（vimの編集内容など）までは戻りません。
""")
    else:
        print(f"不明なコマンド: {sub}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
