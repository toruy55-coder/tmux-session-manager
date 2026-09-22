"""tmuxセッション一覧・メモ管理の共通ロジック（tm.py / web.py から共用）。"""

import json
import os
import subprocess
import tomllib
from datetime import datetime, timezone

NOTES_PATH = os.path.expanduser("~/sync/logs/tmux-sessions_notes.json")
SESSIONS_PATH = os.path.expanduser("~/.config/tm/sessions.toml")


def load_notes():
    if not os.path.exists(NOTES_PATH):
        return {}
    with open(NOTES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_notes(notes):
    os.makedirs(os.path.dirname(NOTES_PATH), exist_ok=True)
    with open(NOTES_PATH, "w", encoding="utf-8") as f:
        json.dump(notes, f, ensure_ascii=False, indent=2, sort_keys=True)


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def tmux_sessions():
    """tmux list-sessions の結果をパースして辞書のリストで返す。セッションが無ければ空リスト。"""
    fmt = "#{session_name}\t#{session_attached}\t#{session_created}\t#{session_activity}\t#{pane_current_path}"
    result = subprocess.run(
        ["tmux", "list-sessions", "-F", fmt],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return []
    sessions = []
    for line in result.stdout.splitlines():
        name, attached, created, activity, path = line.split("\t")
        sessions.append({
            "name": name,
            "attached": attached != "0",
            "created": int(created),
            "activity": int(activity),
            "path": path,
        })
    return sessions


def relative_time(epoch):
    delta = datetime.now().timestamp() - epoch
    if delta < 60:
        return "たった今"
    if delta < 3600:
        return f"{int(delta // 60)}分前"
    if delta < 86400:
        return f"{int(delta // 3600)}時間前"
    return f"{int(delta // 86400)}日前"


def shorten_path(path):
    home = os.path.expanduser("~")
    if path.startswith(home):
        return "~" + path[len(home):]
    return path


def build_rows():
    """現在のtmuxセッション一覧＋メモを、表示用の行データとして返す。"""
    sessions = tmux_sessions()
    notes = load_notes()
    sessions.sort(key=lambda s: s["activity"], reverse=True)
    rows = []
    for i, s in enumerate(sessions, start=1):
        memo = notes.get(s["name"], {}).get("memo", "")
        rows.append({
            "index": i,
            "name": s["name"],
            "attached": s["attached"],
            "path": shorten_path(s["path"]),
            "activity_rel": relative_time(s["activity"]),
            "memo": memo,
        })
    return rows


def orphan_notes():
    """tmux上に存在しないセッションのメモ一覧（名前→メモ内容）を返す。"""
    notes = load_notes()
    existing = {s["name"] for s in tmux_sessions()}
    return {name: data.get("memo", "") for name, data in notes.items() if name not in existing}


def resolve_target(target, rows):
    """番号 or セッション名からセッション名を解決する。見つからなければNone。"""
    if target.isdigit():
        idx = int(target)
        for r in rows:
            if r["index"] == idx:
                return r["name"]
        return None
    for r in rows:
        if r["name"] == target:
            return r["name"]
    return None


def set_memo(name, memo_text):
    notes = load_notes()
    notes[name] = {"memo": memo_text, "updated_at": now_iso()}
    save_notes(notes)


def delete_memo(name):
    notes = load_notes()
    if name in notes:
        del notes[name]
        save_notes(notes)
        return True
    return False


def _toml_escape(text):
    return text.replace("\\", "\\\\").replace('"', '\\"')


def load_session_defs():
    """~/.config/tm/sessions.toml から常用セッション定義を読む。無ければ空リスト。"""
    if not os.path.exists(SESSIONS_PATH):
        return []
    with open(SESSIONS_PATH, "rb") as f:
        data = tomllib.load(f)
    return data.get("session", [])


def save_session_defs(defs):
    """常用セッション定義をTOMLとして書き出す（標準ライブラリにTOML書き込みが無いため手書き）。"""
    os.makedirs(os.path.dirname(SESSIONS_PATH), exist_ok=True)
    lines = [
        "# tm restore / tm save が読み書きする常用セッション定義。",
        "# 再起動でtmuxサーバーが消えても、ここに登録したセッションは `tm restore` で作り直せる。",
        "# 復元できるのは名前・作業ディレクトリ・初期コマンドの構成までで、",
        "# 走っていたプロセスの中身（vimの編集内容など）は戻らない。",
        "",
    ]
    for d in defs:
        lines.append("[[session]]")
        lines.append(f'name = "{_toml_escape(d["name"])}"')
        lines.append(f'dir = "{_toml_escape(d["dir"])}"')
        lines.append(f'cmd = "{_toml_escape(d.get("cmd", ""))}"')
        lines.append("")
    with open(SESSIONS_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def current_session_defs():
    """現在動いているtmuxセッションから定義リストを作る（cmdは分からないので空）。"""
    return [
        {"name": s["name"], "dir": shorten_path(s["path"]), "cmd": ""}
        for s in tmux_sessions()
    ]


def merge_session_defs(current, previous):
    """現在の構成をベースに、既存定義に書かれていたcmdを名前が一致するものだけ引き継ぐ。"""
    prev_cmd = {d["name"]: d.get("cmd", "") for d in previous}
    merged = []
    for d in current:
        merged.append({**d, "cmd": prev_cmd.get(d["name"], "")})
    return merged


def restore_sessions():
    """定義ファイルを元に、存在しないセッションだけを作る（冪等）。作成結果を返す。"""
    defs = load_session_defs()
    existing = {s["name"] for s in tmux_sessions()}
    created, skipped = [], []
    for d in defs:
        name = d["name"]
        if name in existing:
            skipped.append(name)
            continue
        work_dir = os.path.expanduser(d["dir"])
        subprocess.run(["tmux", "new-session", "-d", "-s", name, "-c", work_dir])
        cmd = d.get("cmd", "")
        if cmd:
            subprocess.run(["tmux", "send-keys", "-t", name, cmd, "Enter"])
        created.append(name)
    return created, skipped
