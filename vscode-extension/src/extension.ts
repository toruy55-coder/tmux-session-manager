import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as fs from 'fs';
import * as pathMod from 'path';

interface HostConfig {
  label: string;
  ssh?: string;
}

type SessionState = '実行中' | '承認待ち' | '待機中' | '接続切れ' | '状態不明';

interface SessionInfo {
  name: string;
  attached: boolean;
  activityEpoch: number;
  dir: string;
  memo: string;
  state: SessionState;
}

const APPROVAL_PATTERNS: RegExp[] = [
  /do you want to proceed/i,
  /would you like me to/i,
  /\(y\/n\)/i,
  /\[y\/n\]/i,
  /approve this/i,
  /allow this command/i,
  /allow command/i,
  /press enter to (confirm|continue)/i,
  /❯\s*1\./,
  /^\s*1\.\s*Yes/m,
];

function expandHome(p: string): string {
  if (p.startsWith('~')) {
    return pathMod.join(process.env.HOME || '', p.slice(1));
  }
  return p;
}

function execAsync(cmd: string, timeoutMs = 8000): Promise<string> {
  return new Promise((resolve) => {
    cp.exec(cmd, { timeout: timeoutMs, maxBuffer: 1024 * 1024 }, (err, stdout) => {
      if (err) {
        resolve('');
        return;
      }
      resolve(stdout);
    });
  });
}

function shQuote(s: string): string {
  return `'${s.replace(/'/g, `'\\''`)}'`;
}

async function runOnHost(host: HostConfig, remoteCmd: string): Promise<string> {
  if (!host.ssh) {
    return execAsync(remoteCmd);
  }
  const full = `ssh -o BatchMode=yes -o ConnectTimeout=5 ${host.ssh} ${shQuote(remoteCmd)}`;
  return execAsync(full);
}

const FIELD_SEP = '|||';

async function listSessions(host: HostConfig): Promise<SessionInfo[] | null> {
  const fmt = `#{session_name}${FIELD_SEP}#{session_attached}${FIELD_SEP}#{session_activity}${FIELD_SEP}#{session_path}`;
  const out = await runOnHost(host, `tmux list-sessions -F '${fmt}' 2>/dev/null`);
  if (!out.trim()) {
    return null; // tmuxサーバー未起動 or SSH到達不可。呼び出し側で「接続切れ」等に振り分ける
  }
  const lines = out.trim().split('\n');
  const sessions: SessionInfo[] = [];
  for (const line of lines) {
    const [name, attached, activity, dir] = line.split(FIELD_SEP);
    if (!name) continue;
    sessions.push({
      name,
      attached: attached === '1',
      activityEpoch: parseInt(activity, 10) || 0,
      dir: dir || '',
      memo: '',
      state: '状態不明',
    });
  }
  return sessions;
}

async function classifyState(host: HostConfig, s: SessionInfo, pollIntervalSec: number): Promise<SessionState> {
  const pane = await runOnHost(host, `tmux capture-pane -p -t ${shQuote(s.name)} -S -8 2>/dev/null`);
  if (!pane) {
    return '状態不明';
  }
  for (const pat of APPROVAL_PATTERNS) {
    if (pat.test(pane)) {
      return '承認待ち';
    }
  }
  const nowSec = Math.floor(Date.now() / 1000);
  const recentSec = Math.max(pollIntervalSec * 3, 15);
  if (nowSec - s.activityEpoch < recentSec) {
    return '実行中';
  }
  return '待機中';
}

async function loadMemos(host: HostConfig, memoPath: string): Promise<Record<string, { memo: string }>> {
  try {
    let text: string;
    if (host.ssh) {
      text = await runOnHost(host, `cat ${memoPath} 2>/dev/null || echo '{}'`);
    } else {
      text = fs.readFileSync(expandHome(memoPath), 'utf8');
    }
    return JSON.parse(text || '{}');
  } catch {
    return {};
  }
}

async function saveMemo(host: HostConfig, memoPath: string, sessionName: string, memo: string): Promise<void> {
  const memos = await loadMemos(host, memoPath);
  memos[sessionName] = { memo, updated_at: new Date().toISOString() } as any;
  const json = JSON.stringify(memos, null, 2);
  if (!host.ssh) {
    fs.writeFileSync(expandHome(memoPath), json, 'utf8');
    return;
  }
  await new Promise<void>((resolve) => {
    const child = cp.spawn('ssh', [host.ssh as string, `cat > ${memoPath}`]);
    child.stdin.write(json);
    child.stdin.end();
    child.on('close', () => resolve());
    child.on('error', () => resolve());
  });
}

class TmTreeItem extends vscode.TreeItem {
  constructor(
    label: string,
    collapsibleState: vscode.TreeItemCollapsibleState,
    public readonly host?: HostConfig,
    public readonly session?: SessionInfo
  ) {
    super(label, collapsibleState);
    if (session) {
      this.contextValue = 'session';
      this.description = `${session.state}${session.memo ? ' ・ ' + session.memo : ''}`;
      this.tooltip = `${session.dir}\n状態: ${session.state}`;
      this.iconPath = new vscode.ThemeIcon('circle-filled', stateColor(session.state));
      this.command = {
        command: 'tmSessions.attach',
        title: 'アタッチ',
        arguments: [this],
      };
    } else {
      this.contextValue = 'host';
      this.iconPath = new vscode.ThemeIcon('server');
    }
  }
}

function stateColor(state: SessionState): vscode.ThemeColor {
  switch (state) {
    case '実行中':
      return new vscode.ThemeColor('charts.green');
    case '承認待ち':
      return new vscode.ThemeColor('charts.yellow');
    case '待機中':
      return new vscode.ThemeColor('disabledForeground');
    case '接続切れ':
    case '状態不明':
    default:
      return new vscode.ThemeColor('charts.red');
  }
}

class TmTreeProvider implements vscode.TreeDataProvider<TmTreeItem> {
  private _onDidChangeTreeData = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;
  private cache = new Map<string, SessionInfo[] | null>();

  refresh(): void {
    this.cache.clear();
    this._onDidChangeTreeData.fire();
  }

  getTreeItem(element: TmTreeItem): vscode.TreeItem {
    return element;
  }

  getHosts(): HostConfig[] {
    return vscode.workspace.getConfiguration('tmSessions').get<HostConfig[]>('hosts') || [];
  }

  async getChildren(element?: TmTreeItem): Promise<TmTreeItem[]> {
    const cfg = vscode.workspace.getConfiguration('tmSessions');
    const memoPath = cfg.get<string>('memoPath') || '~/sync/logs/tmux-sessions_notes.json';
    const pollIntervalSec = cfg.get<number>('pollIntervalSec') || 5;

    if (!element) {
      return this.getHosts().map(
        (h) => new TmTreeItem(h.label, vscode.TreeItemCollapsibleState.Expanded, h)
      );
    }

    if (element.host && !element.session) {
      const host = element.host;
      let sessions = this.cache.get(host.label);
      if (sessions === undefined) {
        sessions = await listSessions(host);
        if (sessions) {
          const memos = await loadMemos(host, memoPath);
          for (const s of sessions) {
            s.memo = memos[s.name]?.memo || '';
            s.state = await classifyState(host, s, pollIntervalSec);
          }
        }
        this.cache.set(host.label, sessions);
      }
      if (!sessions) {
        const item = new TmTreeItem('（接続不可 / セッションなし）', vscode.TreeItemCollapsibleState.None, host);
        item.contextValue = 'unreachable';
        item.iconPath = new vscode.ThemeIcon('debug-disconnect');
        return [item];
      }
      return sessions.map(
        (s) => new TmTreeItem(s.name, vscode.TreeItemCollapsibleState.None, host, s)
      );
    }

    return [];
  }
}

export function activate(context: vscode.ExtensionContext) {
  const provider = new TmTreeProvider();
  vscode.window.registerTreeDataProvider('tmSessions.view', provider);

  const cfg = () => vscode.workspace.getConfiguration('tmSessions');
  let timer: NodeJS.Timeout | undefined;
  const restartTimer = () => {
    if (timer) clearInterval(timer);
    const sec = cfg().get<number>('pollIntervalSec') || 5;
    timer = setInterval(() => provider.refresh(), sec * 1000);
  };
  restartTimer();
  context.subscriptions.push({ dispose: () => timer && clearInterval(timer) });
  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration('tmSessions')) {
        restartTimer();
        provider.refresh();
      }
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('tmSessions.refresh', () => provider.refresh())
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('tmSessions.attach', (item: TmTreeItem) => {
      if (!item.session || !item.host) return;
      const termName = `${item.host.label}: ${item.session.name}`;
      const existing = vscode.window.terminals.find((t) => t.name === termName);
      if (existing) {
        existing.show();
        return;
      }
      const term = vscode.window.createTerminal(termName);
      const attachCmd = `tmux attach -t ${item.session.name}`;
      const cmd = item.host.ssh
        ? `ssh -t ${item.host.ssh} ${JSON.stringify(attachCmd)}`
        : attachCmd;
      term.sendText(cmd);
      term.show();
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('tmSessions.editMemo', async (item: TmTreeItem) => {
      if (!item.session || !item.host) return;
      const memoPath = cfg().get<string>('memoPath') || '~/sync/logs/tmux-sessions_notes.json';
      const memo = await vscode.window.showInputBox({
        prompt: `${item.session.name} のメモ`,
        value: item.session.memo,
      });
      if (memo === undefined) return;
      await saveMemo(item.host, memoPath, item.session.name, memo);
      provider.refresh();
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('tmSessions.newSession', async () => {
      const hosts = provider.getHosts();
      const pick = await vscode.window.showQuickPick(hosts.map((h) => h.label), {
        placeHolder: '作成先ホストを選択',
      });
      if (!pick) return;
      const host = hosts.find((h) => h.label === pick);
      if (!host) return;
      const name = await vscode.window.showInputBox({ prompt: '新しいセッション名' });
      if (!name) return;
      const memo = (await vscode.window.showInputBox({ prompt: 'メモ（何の作業か・省略可）' })) || '';
      await runOnHost(host, `tmux new-session -d -s ${shQuote(name)}`);
      const memoPath = cfg().get<string>('memoPath') || '~/sync/logs/tmux-sessions_notes.json';
      if (memo) {
        await saveMemo(host, memoPath, name, memo);
      }
      provider.refresh();
    })
  );
}

export function deactivate() {}
