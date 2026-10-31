import { EventEmitter } from 'node:events';
import { randomBytes } from 'node:crypto';
import type { Action, AppState, Scenario, Snapshot, Source, TranslationRequest } from '../shared/types';
import { CoreProcess, PythonProcess } from './python';
import { SettingsStore } from './settings';
import { translate, translationRequest } from './translation';
import { action, object, text } from './validation';

export class Controller extends EventEmitter {
  readonly core = new CoreProcess();
  state: AppState;
  private worker: PythonProcess | null = null;
  private jobs = new Map<string, AbortController>();
  private busy = false;
  private closing = false;
  private generation = 0;
  constructor(readonly root: string, readonly store: SettingsStore) {
    super();
    this.state = { revision: 0, connection: 'starting', error: store.warning, snapshot: null, scenarios: [], sources: [], sourceError: null, settings: store.public(), overlay: { ...store.overlay }, http: { completed: 0, failed: 0, lastMs: null } };
    this.core.on('message', message => {
      try { this.receive(message); }
      catch { this.state.error = '核心返回的数据无效'; this.state.connection = 'error'; this.publish(); void this.core.close(); }
    });
    this.core.on('fault', message => {
      if (this.closing) return;
      this.state.connection = 'error'; this.state.error = message; this.state.snapshot = null;
      this.abortTranslations(); this.publish();
    });
    this.core.on('closed', expected => {
      this.abortTranslations();
      if (!expected && !this.closing) { this.state.connection = 'error'; this.state.error = '字幕核心意外退出，可点击重启核心恢复'; this.state.snapshot = null; this.publish(); }
      void this.stopWorker();
    });
  }
  async start(): Promise<void> {
    this.generation++; this.state.connection = 'starting'; this.state.snapshot = null; this.state.error = this.store.warning; this.publish();
    try {
      await this.core.start(this.root);
      await this.configure();
      this.state.connection = 'ready'; this.publish();
      await this.refreshSources();
    } catch {
      this.state.connection = 'error'; this.state.error = '字幕组件启动失败，请重启客户端；若仍失败，请重新解压完整客户端包'; this.publish();
      await this.core.close();
    }
  }
  private requireIdle(): void {
    if (this.state.connection !== 'ready') throw new Error('请等待核心就绪，或点击重启核心');
    if (this.state.snapshot && (this.state.snapshot.state !== 'idle' || this.state.snapshot.mode !== 'idle')) throw new Error('请先停止当前会话');
  }
  async dispatch(input: unknown, view: 'main' | 'overlay'): Promise<void> {
    const operation = action(input);
    if (view === 'overlay' && !['overlay.update', 'window.show'].includes(operation.type)) throw new Error('该窗口无权执行此操作');
    if (operation.type === 'overlay.update') {
      this.store.setOverlay(operation.patch); this.state.overlay = { ...this.store.overlay };
      this.emit('overlay'); this.publish(); return;
    }
    if (operation.type === 'window.show') { this.emit('showMain'); return; }
    if (this.busy || this.closing) throw new Error('正在处理上一项操作，请稍候');
    this.busy = true;
    try {
      this.state.error = null;
      switch (operation.type) {
        case 'demo.start':
          this.requireIdle();
          if (!this.state.scenarios.some(s => s.name === operation.scenario)) throw new Error('演示场景不存在');
          await this.core.command('demo.start', { scenario: operation.scenario }); break;
        case 'session.start': await this.startSession(operation.sourceId); break;
        case 'session.stop':
          await this.core.command('session.stop', {}, 'session.stopped');
          await this.stopWorker(); this.abortTranslations(); break;
        case 'core.restart':
          this.generation++; this.abortTranslations(); await this.core.close(); await this.stopWorker();
          await this.start(); break;
        case 'sources.refresh': await this.refreshSources(); break;
        case 'settings.save':
          this.requireIdle(); await this.store.save(operation); this.state.settings = this.store.public();
          await this.configure(); break;
      }
    } finally { this.busy = false; this.publish(); }
  }
  private async configure(): Promise<void> {
    const config = this.store.config;
    await this.core.command('config.update', { translation: { executor: config.translation.backend === 'chat' && config.asr.backend !== 'scripted' ? 'host' : 'core_mock', mode: config.translation.mode }, glossary: config.glossary });
  }
  private async refreshSources(): Promise<void> {
    this.requireIdle();
    await this.core.command('sources.list', { request_id: 'desktop-sources' });
  }
  private async startSession(sourceId: string): Promise<void> {
    this.requireIdle();
    const selected = this.state.sources.find(item => item.id === sourceId);
    if (!selected) throw new Error('请选择声音来源；应用退出后请刷新列表');
    const config = this.store.config;
    let url = config.asr.url;
    let token: string;
    if (config.asr.backend === 'scripted') {
      token = randomBytes(32).toString('hex');
      url = await this.startWorker(token);
    } else {
      token = await this.store.secret('asrToken');
      if (token.length < 16) throw new Error('请先保存本地 ASR 服务令牌（至少 16 个字符）');
    }
    const source = selected.kind === 'application'
      ? { kind: selected.kind, root_pid: selected.root_pid, label: selected.name }
      : { kind: selected.kind, device_id: selected.id.slice('device:'.length), label: selected.name };
    try {
      await this.configure();
      await this.core.command('session.start', { source, asr: { url, token } });
      if (this.state.snapshot?.mode === 'idle') await this.stopWorker();
    } catch (error) { await this.stopWorker(); throw error; }
  }
  private async startWorker(token: string): Promise<string> {
    await this.stopWorker();
    const worker = new PythonProcess(); this.worker = worker;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { reject(new Error('模拟 ASR 启动超时')); void this.stopWorker(); }, 12_000);
      const fail = () => { clearTimeout(timer); reject(new Error('模拟 ASR 启动失败')); };
      worker.once('message', message => {
        clearTimeout(timer);
        if (message.type !== 'asr.listening' || !Number.isInteger(message.port) || (message.port as number) < 1 || (message.port as number) > 65535) { fail(); return; }
        resolve(`ws://127.0.0.1:${message.port}/v1/asr`);
      });
      worker.on('fault', fail);
      worker.on('closed', expected => {
        clearTimeout(timer);
        if (!expected) { fail(); this.state.error = '模拟 ASR 意外退出，请停止后重新开始'; this.publish(); }
      });
      worker.start(this.root, ['asr-worker', '--backend', 'scripted'], { LIVE_TRANSLATOR_ASR_TOKEN: token });
    });
  }
  private async stopWorker(): Promise<void> {
    const worker = this.worker; this.worker = null;
    if (worker) await worker.close();
  }
  private receive(message: Record<string, unknown>): void {
    if (message.type === 'core.ready') {
      if (!Array.isArray(message.scenarios) || message.scenarios.length > 30) throw new Error('invalid scenarios');
      this.state.scenarios = message.scenarios.map(value => { const s = object(value); return { name: text(s.name, 80), title: text(s.title, 120), description: text(s.description, 1000) }; });
    } else if (message.type === 'snapshot') {
      this.state.snapshot = snapshot(message);
      if (this.state.snapshot.mode === 'idle') this.abortTranslations();
    } else if (message.type === 'sources.result') {
      const apps = Array.isArray(message.applications) ? message.applications : [];
      const devices = Array.isArray(message.devices) ? message.devices : [];
      this.state.sources = [...apps, ...devices].slice(0, 256).map(value => {
        const s = object(value); const id = text(s.id, 300); const name = text(s.name, 200);
        if (s.kind === 'application' && Number.isSafeInteger(s.root_pid) && (s.root_pid as number) > 0) return { id, name, kind: 'application', root_pid: s.root_pid, active: !!s.active } as Source;
        if (s.kind === 'output_device' && id.startsWith('device:')) return { id, name, kind: 'output_device', is_default: !!s.is_default } as Source;
        throw new Error('invalid source');
      });
      this.state.sourceError = typeof message.error === 'string' ? message.error.slice(0, 300) : null;
    } else if (message.type === 'translate.request') {
      const request = translationRequest(message);
      void this.executeTranslation(request);
    } else if (message.type === 'error' && !message.command_id) {
      this.state.error = '字幕核心报告异常，请停止后重试';
    }
    this.publish();
  }
  private async executeTranslation(request: TranslationRequest): Promise<void> {
    if (this.jobs.has(request.request_id)) return;
    if (this.jobs.size >= 2) { await this.reply(request, { error: 'translation_busy' }); return; }
    const config = this.store.config.translation;
    if (config.backend !== 'chat') { await this.reply(request, { error: 'translation_not_configured' }); return; }
    const controller = new AbortController(); this.jobs.set(request.request_id, controller);
    const generation = this.generation; const started = performance.now();
    try {
      const content = await translate(request, config, await this.store.secret('apiKey'), controller.signal);
      if (!controller.signal.aborted && generation === this.generation) { this.state.http.completed++; await this.reply(request, { content }); }
    } catch (error) {
      if (!controller.signal.aborted && generation === this.generation) {
        this.state.http.failed++;
        const message = error instanceof Error ? error.message : 'translation_failed';
        this.state.error = message; await this.reply(request, { error: message });
      }
    } finally { if (this.jobs.get(request.request_id) === controller) this.jobs.delete(request.request_id); this.state.http.lastMs = Math.round(performance.now() - started); this.publish(); }
  }
  private async reply(request: TranslationRequest, result: { content: string } | { error: string }): Promise<void> {
    try { await this.core.command('translation.result', { request_id: request.request_id, session_id: request.session_id, source_revision: request.source_revision, ...result }); }
    catch { if (!this.closing) { this.state.error = '翻译返回未送达核心，请停止后重试'; this.publish(); } }
  }
  private abortTranslations(): void { for (const job of this.jobs.values()) job.abort(); this.jobs.clear(); }
  publish(): void { this.state.revision++; this.emit('state', this.state); }
  async close(): Promise<void> {
    this.closing = true;
    await this.core.close(); await this.stopWorker(); this.abortTranslations();
    this.state.connection = 'closed'; this.state.snapshot = null;
  }
}

function snapshot(value: Record<string, unknown>): Snapshot {
  if (!['idle', 'running', 'stopping'].includes(String(value.state)) || !['idle', 'demo', 'live'].includes(String(value.mode)) || !Number.isSafeInteger(value.version)) throw new Error('invalid snapshot');
  const cue = (value: unknown): Snapshot['current'] => {
    if (value === null) return null;
    const c = object(value);
    text(c.text, 4000);
    for (const key of ['cue_id', 'segment_id', 'version', 'shown_at_ms', 'expires_at_ms']) if (!Number.isSafeInteger(c[key])) throw new Error('invalid cue');
    if (!['subtitle', 'correction'].includes(String(c.kind)) || typeof c.source_incomplete !== 'boolean') throw new Error('invalid cue');
    return c as unknown as Snapshot['current'];
  };
  if (!Array.isArray(value.history) || value.history.length > 50) throw new Error('invalid history');
  for (const item of value.history) {
    const h = object(item); text(h.source, 4000, true);
    if (h.translation !== null) text(h.translation, 4000, true);
    if (!Array.isArray(h.corrections) || h.corrections.length > 50) throw new Error('invalid corrections');
  }
  object(value.source); object(value.activity); object(value.stats);
  return { ...value, current: cue(value.current), previous: cue(value.previous) } as unknown as Snapshot;
}
