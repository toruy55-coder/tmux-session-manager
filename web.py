#!/usr/bin/env python3
"""tmuxセッションの状態をブラウザで見て、メモ編集・接続コマンドのコピーができるダッシュボード。

実際のターミナル接続はブラウザ内では行わない（SSHコマンドをコピーして
手元のターミナルに貼り付ける方式）。tmuxサーバー自体はVaioU側で独立して
動いているため、このアプリやブラウザが落ちてもセッションには影響しない。
"""

import html
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

import tm_core as core

BIND_HOST = os.environ.get("TM_WEB_HOST", "100.74.222.40")  # Tailscaleアドレスのみ待ち受け
BIND_PORT = int(os.environ.get("TM_WEB_PORT", "8765"))
SSH_USER = os.environ.get("TM_WEB_SSH_USER", "mtb-linux")
SSH_HOST = os.environ.get("TM_WEB_SSH_HOST", "mtb-linux")

PAGE_HEAD = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>tmux セッション一覧</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: -apple-system, "Hiragino Sans", sans-serif; margin: 0; padding: 24px;
         background: #f4f5f7; color: #222; }
  h1 { font-size: 1.3rem; margin-bottom: 4px; }
  .sub { color: #666; font-size: 0.85rem; margin-bottom: 20px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 14px; }
  .card { background: #fff; border-radius: 10px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
  .card.attached { border-left: 4px solid #2e9e44; }
  .card.detached { border-left: 4px solid #bbb; }
  .row1 { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
  .name { font-weight: 600; font-size: 1.05rem; }
  .status { font-size: 0.8rem; padding: 2px 8px; border-radius: 999px; }
  .status.attached { background: #e3f6e6; color: #1f7a34; }
  .status.detached { background: #eee; color: #777; }
  .path { font-size: 0.8rem; color: #888; margin-bottom: 2px; word-break: break-all; }
  .activity { font-size: 0.8rem; color: #888; margin-bottom: 10px; }
  textarea { width: 100%; box-sizing: border-box; font-size: 0.9rem; padding: 6px 8px;
             border: 1px solid #ddd; border-radius: 6px; resize: vertical; min-height: 40px;
             font-family: inherit; }
  .actions { display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
  button, .btn { font-size: 0.82rem; padding: 6px 12px; border-radius: 6px; border: 1px solid #ccc;
                 background: #fafafa; cursor: pointer; }
  button.primary { background: #2d6cdf; color: #fff; border-color: #2d6cdf; }
  button.copy { background: #333; color: #fff; border-color: #333; }
  button.danger { background: #fff0f0; color: #b33; border-color: #e9b9b9; }
  .copied { color: #1f7a34; font-size: 0.78rem; margin-left: 6px; }
  .empty { color: #888; }
  details { margin-top: 28px; }
  summary { cursor: pointer; color: #666; }
  .orphan-row { display: flex; align-items: center; justify-content: space-between;
                padding: 6px 0; border-bottom: 1px solid #eee; font-size: 0.85rem; }
</style>
</head>
<body>
"""

PAGE_TAIL = """
<script>
function copyCmd(btn, cmd) {
  navigator.clipboard.writeText(cmd).then(() => {
    const note = btn.nextElementSibling;
    note.style.display = "inline";
    setTimeout(() => { note.style.display = "none"; }, 1500);
  });
}
</script>
</body>
</html>
"""


def render_page():
    rows = core.build_rows()
    orphans = core.orphan_notes()

    parts = [PAGE_HEAD]
    parts.append("<h1>tmux セッション一覧</h1>")
    parts.append(
        f'<div class="sub">{SSH_USER}@{SSH_HOST} ／ 接続が切れてもtmuxセッションは残ります'
        f'（ただしVaioU自体の再起動では全て消えます。常用セッションは <code>tm save</code> /'
        f' <code>tm restore</code> で復元してください）。 <a href="/">更新</a></div>'
    )

    if not rows:
        parts.append('<p class="empty">tmuxセッションはありません。</p>')
    else:
        parts.append('<div class="grid">')
        for r in rows:
            name = html.escape(r["name"])
            state_cls = "attached" if r["attached"] else "detached"
            state_label = "●接続中" if r["attached"] else "○切断中"
            memo = html.escape(r["memo"])
            path = html.escape(r["path"])
            attach_cmd = f"ssh {SSH_USER}@{SSH_HOST} -t 'tmux attach -t {r['name']}'"
            attach_cmd_js = html.escape(attach_cmd).replace("'", "&#39;")
            parts.append(f"""
<div class="card {state_cls}">
  <div class="row1">
    <span class="name">{name}</span>
    <span class="status {state_cls}">{state_label}</span>
  </div>
  <div class="path">{path}</div>
  <div class="activity">最終操作: {r['activity_rel']}</div>
  <form method="post" action="/memo">
    <input type="hidden" name="name" value="{name}">
    <textarea name="memo" placeholder="何の作業か（メモ）">{memo}</textarea>
    <div class="actions">
      <button type="submit" class="primary">メモを保存</button>
      <button type="button" class="copy" onclick="copyCmd(this, '{attach_cmd_js}')">接続コマンドをコピー</button>
      <span class="copied" style="display:none;">コピーしました</span>
    </div>
  </form>
</div>
""")
        parts.append("</div>")

    parts.append("<details>")
    parts.append(f"<summary>使われていないメモ（{len(orphans)}件）</summary>")
    if not orphans:
        parts.append('<p class="empty">ありません。</p>')
    else:
        for name, memo in orphans.items():
            n = html.escape(name)
            m = html.escape(memo) if memo else "(メモなし)"
            parts.append(f"""
<div class="orphan-row">
  <span>{n}: {m}</span>
  <form method="post" action="/delete_orphan" style="margin:0;">
    <input type="hidden" name="name" value="{n}">
    <button type="submit" class="danger">削除</button>
  </form>
</div>
""")
    parts.append("</details>")

    parts.append(PAGE_TAIL)
    return "".join(parts).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _redirect_home(self):
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

    def _read_form(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        parsed = parse_qs(body)
        return {k: v[0] for k, v in parsed.items()}

    def do_GET(self):
        if self.path != "/":
            self.send_response(404)
            self.end_headers()
            return
        body = render_page()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        form = self._read_form()
        if self.path == "/memo":
            name = form.get("name", "").strip()
            memo = form.get("memo", "")
            if name:
                core.set_memo(name, memo)
            self._redirect_home()
        elif self.path == "/delete_orphan":
            name = form.get("name", "").strip()
            if name:
                core.delete_memo(name)
            self._redirect_home()
        else:
            self.send_response(404)
            self.end_headers()


def main():
    server = ThreadingHTTPServer((BIND_HOST, BIND_PORT), Handler)
    print(f"tm-web: http://{BIND_HOST}:{BIND_PORT} で待ち受け中")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
