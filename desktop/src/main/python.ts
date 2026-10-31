import { EventEmitter } from 'node:events';
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { StringDecoder } from 'node:string_decoder';
import { randomUUID } from 'node:crypto';
import { join } from 'node:path';
import { existsSync } from 'node:fs';
import { object } from './validation';

export const MAX_LINE = 1024 * 1024;
export class JsonLines {
  private decoder = new StringDecoder('utf8');
  private pending = '';
  constructor(private receive: (value: Record<string, unknown>) => void) {}
  push(chunk: Buffer): void {
    this.pending += this.decoder.write(chunk);
    let newline: number;
    while ((newline = this.pending.indexOf('\n')) >= 0) {
      const line = this.pending.slice(0, newline); this.pending = this.pending.slice(newline + 1);
      if (Buffer.byteLength(line) > MAX_LINE) throw new Error('核心消息过大');
      if (line.trim()) this.receive(object(JSON.parse(line)));
    }
    if (Buffer.byteLength(this.pending) > MAX_LINE) throw new Error('核心消息过大');
  }
}
export function pythonEnvironment(extra: Record<string, string> = {}, bundledRoot?: string): NodeJS.ProcessEnv {
  const allowed = ['SystemRoot', 'WINDIR', 'PATH', 'TEMP', 'TMP', 'USERPROFILE', 'HOMEDRIVE', 'HOMEPATH', 'LOCALAPPDATA', 'APPDATA', 'PROGRAMDATA', 'SystemDrive', 'COMSPEC'];
  const result: NodeJS.ProcessEnv = {};
  for (const [key, value] of Object.entries(process.env)) if (allowed.some(name => name.toLowerCase() === key.toLowerCase())) result[key] = value;
  if (bundledRoot) {
    for (const key of Object.keys(result)) if (key.toLowerCase() === 'path') delete result[key];
    const systemRoot = process.env.SystemRoot ?? 'C:\\Windows';
    result.PATH = [join(bundledRoot, 'python'), join(systemRoot, 'System32'), systemRoot].join(';');
  }
  return { ...result, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8', PYTHONDONTWRITEBYTECODE: '1', ...extra };
}
export function pythonPath(root: string): string {
  const bundled = join(root, 'python', 'python.exe');
  if (existsSync(bundled)) return bundled;
  if (existsSync(join(root, 'runtime-manifest.json'))) throw new Error('客户端运行组件缺失，请重新解压完整客户端包');
  return join(root, 'core', '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
}
export class PythonProcess extends EventEmitter {
  child: ChildProcessWithoutNullStreams | null = null;
  exited: Promise<void> = Promise.resolve();
  private closing = false;
  start(root: string, command: string[], extra: Record<string, string> = {}): void {
    if (this.child) throw new Error('进程已经启动');
    const bundled = existsSync(join(root, 'runtime-manifest.json'));
    const child = spawn(pythonPath(root), ['-I', '-u', '-m', 'live_translator', ...command], { cwd: join(root, 'core'), env: pythonEnvironment(extra, bundled ? root : undefined), windowsHide: true, stdio: 'pipe' });
    this.child = child; this.closing = false;
    const parser = new JsonLines(message => this.emit('message', message));
    child.stdout.on('data', (chunk: Buffer) => {
      try { parser.push(chunk); } catch { this.emit('fault', '核心协议无效或消息过大'); child.kill(); }
    });
    child.stderr.on('data', () => { /* Consume diagnostics without forwarding source text or secrets. */ });
    child.on('error', () => this.emit('fault', bundled ? '字幕运行组件无法启动，请重新解压完整客户端包' : '无法启动开发环境，请检查 core/.venv'));
    child.stdin.on('error', () => { if (!this.closing) this.emit('fault', '核心输入通道已关闭'); });
    this.exited = new Promise(resolve => child.once('close', () => { this.child = null; this.emit('closed', this.closing); resolve(); }));
  }
  send(message: Record<string, unknown>): void {
    const child = this.child;
    if (!child || child.exitCode !== null || child.stdin.destroyed) throw new Error('核心尚未就绪');
    const line = JSON.stringify(message) + '\n';
    if (Buffer.byteLength(line) > MAX_LINE || child.stdin.writableLength > 128 * 1024) throw new Error('核心通信繁忙，请稍后重试');
    child.stdin.write(line);
  }
  async close(graceful?: () => void, budget = 22_000): Promise<void> {
    if (!this.child) return;
    this.closing = true;
    const child = this.child;
    try { graceful?.(); } catch { /* The process may have already exited. */ }
    if (!graceful) child.kill();
    let timer: ReturnType<typeof setTimeout> | undefined;
    await Promise.race([this.exited, new Promise<void>(resolve => { timer = setTimeout(() => { child.kill(); resolve(); }, budget); })]);
    if (timer) clearTimeout(timer);
    await this.exited;
  }
}
export class CoreProcess extends EventEmitter {
  readonly process = new PythonProcess();
  private sequence = 0;
  private pending = new Map<string, { kind: string; resolve: (value: Record<string, unknown>) => void; reject: (error: Error) => void; timer: ReturnType<typeof setTimeout> }>();
  constructor() {
    super();
    this.process.on('message', message => this.receive(message));
    this.process.on('fault', error => { this.fail(error); void this.process.close(); });
    this.process.on('closed', expected => { this.fail('核心进程已退出', !expected); this.emit('closed', expected); });
  }
  async start(root: string): Promise<void> {
    this.sequence = 0;
    this.process.start(root, ['host']);
    await this.command('hello', { protocol: 'host-core.v1' }, 'core.ready');
  }
  command(type: string, fields: Record<string, unknown> = {}, result = 'command.accepted'): Promise<Record<string, unknown>> {
    if (this.pending.size >= 16) return Promise.reject(new Error('核心操作繁忙'));
    const command_id = randomUUID();
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(command_id); reject(new Error('核心响应超时，可停止后重试或重启核心')); }, result === 'session.stopped' ? 22_000 : 12_000);
      this.pending.set(command_id, { kind: result, resolve, reject, timer });
      try { this.process.send({ type, ...fields, command_id }); }
      catch (error) { clearTimeout(timer); this.pending.delete(command_id); reject(error); }
    });
  }
  async close(): Promise<void> {
    await this.process.close(() => this.process.send({ type: 'shutdown' }));
  }
  private receive(message: Record<string, unknown>): void {
    if (message.protocol !== 'host-core.v1' || !Number.isSafeInteger(message.seq) || (message.seq as number) <= this.sequence || typeof message.type !== 'string') {
      this.fail('核心协议版本或顺序无效'); void this.process.close(); return;
    }
    this.sequence = message.seq as number;
    const id = typeof message.command_id === 'string' ? message.command_id : '';
    const pending = this.pending.get(id);
    if (pending && (pending.kind === message.type || message.type === 'error')) {
      clearTimeout(pending.timer); this.pending.delete(id);
      if (message.type === 'error') pending.reject(new Error('核心拒绝该操作，请检查当前状态和设置'));
      else pending.resolve(message);
    }
    this.emit('message', message);
  }
  private fail(message: string, notify = true): void {
    for (const pending of this.pending.values()) { clearTimeout(pending.timer); pending.reject(new Error(message)); }
    this.pending.clear(); if (notify) this.emit('fault', message);
  }
}
