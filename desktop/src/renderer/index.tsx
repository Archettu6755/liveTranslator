import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import type { Action, AppState, Cue, DesktopApi, PublicSettings, Settings } from '../shared/types';
import './style.css';

declare global { interface Window { liveTranslator: DesktopApi } }
const overlayView = new URLSearchParams(location.search).get('view') === 'overlay';
document.body.className = overlayView ? 'overlay-body' : 'main-body';

function useAppState() {
  const [state, setState] = useState<AppState | null>(null);
  useEffect(() => {
    const receive = (next: AppState) => setState(old => !old || next.revision >= old.revision ? next : old);
    const dispose = window.liveTranslator.onState(receive);
    window.liveTranslator.getState().then(receive);
    return dispose;
  }, []);
  return state;
}

function pagesFor(text: string, font: string, width: number): string[] {
  const canvas = document.createElement('canvas'); const context = canvas.getContext('2d')!;
  context.font = font;
  const segments = new Intl.Segmenter('zh', { granularity: 'grapheme' }).segment(text);
  const lines: string[] = []; let line = '';
  for (const { segment } of segments) {
    if (segment === '\n') { lines.push(line); line = ''; continue; }
    if (line && context.measureText(line + segment).width > Math.max(100, width - 2)) { lines.push(line); line = ''; }
    line += segment;
  }
  if (line || !lines.length) lines.push(line);
  const pages: string[] = [];
  for (let i = 0; i < lines.length; i += 2) pages.push(lines.slice(i, i + 2).join('\n'));
  return pages;
}
function SubtitleLine({ cue, previous, fontSize, preview }: { cue: Cue | null; previous?: boolean; fontSize: number; preview?: boolean }) {
  const ref = useRef<HTMLDivElement>(null); const [width, setWidth] = useState(700); const [page, setPage] = useState(0);
  useLayoutEffect(() => {
    const observer = new ResizeObserver(entries => setWidth(entries[0].contentRect.width));
    if (ref.current) observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  useEffect(() => setPage(0), [cue?.cue_id]);
  const pages = useMemo(() => pagesFor(cue?.text ?? '', `600 ${fontSize}px "Microsoft YaHei UI", "Microsoft YaHei", sans-serif`, width), [cue?.text, fontSize, width]);
  const index = Math.min(page, pages.length - 1);
  return <div className={`subtitle-line ${previous ? 'previous' : 'current'}`} data-cue-id={cue?.cue_id ?? ''}>
    <div className="cue-label"><span>{previous ? '前一条' : cue?.kind === 'correction' ? '更正' : '当前字幕'}</span>{cue?.source_incomplete && <span className="incomplete" title="采集或识别输入存在缺口">原文不完整</span>}
      {pages.length > 1 && <button className="page-button" onClick={() => setPage((index + 1) % pages.length)} aria-label="翻到下一页字幕">{index + 1} / {pages.length} ↻</button>}
    </div>
    <div ref={ref} className="cue-text" style={{ fontSize }} data-testid={previous ? 'previous-cue' : 'current-cue'}>{cue ? pages[index] : preview && !previous ? '字幕会显示在这里' : '\u00a0'}</div>
  </div>;
}
function Subtitles({ state, preview = false }: { state: AppState; preview?: boolean }) {
  return <div className={`subtitle-board ${preview ? 'preview' : ''}`}>
    <SubtitleLine cue={state.snapshot?.previous ?? null} previous preview={preview} fontSize={preview ? 18 : Math.max(18, state.overlay.fontSize * 0.57)} />
    <SubtitleLine cue={state.snapshot?.current ?? null} preview={preview} fontSize={preview ? 25 : state.overlay.fontSize} />
  </div>;
}
function statusText(state: AppState): string {
  if (state.connection === 'starting') return '正在准备';
  if (state.connection !== 'ready') return '需要处理';
  const snapshot = state.snapshot;
  if (snapshot?.source.error) return '来源异常';
  if (snapshot?.state === 'stopping') return '正在停止';
  if (snapshot?.mode === 'demo') return '正在演示';
  if (snapshot?.source.capturing) return snapshot.activity.translating ? '正在翻译' : '正在监听';
  return '准备就绪';
}

function Overlay({ state }: { state: AppState }) {
  const act = (action: Action) => void window.liveTranslator.command(action);
  const empty = !state.snapshot?.current && !state.snapshot?.previous;
  return <main className={`floating ${state.overlay.locked ? '' : 'movable'} ${empty && state.overlay.locked ? 'empty' : ''}`}>
    <div className="floating-toolbar"><span className="live-dot" /> <span>{state.snapshot?.mode === 'demo' ? '离线演示' : state.settings.asr.backend === 'scripted' || state.snapshot?.source.asr_backend === 'scripted' ? '采集测试 · 预设字幕' : '直播字幕'}</span><span className="floating-status">{statusText(state)}</span>
      <button onClick={() => act({ type: 'overlay.update', patch: { locked: !state.overlay.locked } })}>{state.overlay.locked ? '解锁位置' : '锁定位置'}</button>
      <button onClick={() => act({ type: 'window.show' })}>控制窗</button>
    </div>
    <Subtitles state={state} />
  </main>;
}
const quality: Record<string, string> = { normal: '已翻译', pending: '等待翻译', failed: '翻译失败', skipped: '已跳过', incomplete_translation: '译文未完成' };
function History({ state }: { state: AppState }) {
  const entries = [...(state.snapshot?.history ?? [])].reverse();
  return <section className="card history"><div className="section-title"><h2>有限回看</h2><span className="muted">{entries.length} / 50 条</span></div>
    {!entries.length && <div className="empty-history">开始演示或监听后，完整原文与译文会保留在这里。</div>}
    {entries.map((entry, index) => <details key={`${state.snapshot?.session_id}-${entry.segment_id}`}><summary><span className="history-no">{String(entries.length - index).padStart(2, '0')}</span><span>{entry.translation ?? quality[entry.quality] ?? '未翻译'}</span><span className="history-quality">{quality[entry.quality] ?? entry.quality}</span></summary>
      <div className="history-detail"><p lang="ja">{entry.source}</p><p>{entry.translation ?? '暂无译文'}</p><p className="muted">{entry.source_incomplete ? `原文不完整 · ${entry.source_diagnostic === 'capture_gap' ? '音频存在缺口' : entry.source_diagnostic ?? '来源存在缺口'}` : '未标记原文不完整'}</p>{entry.corrections.map((text, index) => <p key={index} className="correction">更正关联：{text}</p>)}</div>
    </details>)}
  </section>;
}
function SettingsPanel({ saved, act, disabled }: { saved: PublicSettings; act: (action: Action) => Promise<void>; disabled: boolean }) {
  const [config, setConfig] = useState<Settings>(() => ({ translation: { ...saved.translation }, asr: { ...saved.asr }, glossary: { ...saved.glossary } }));
  const [apiKey, setApiKey] = useState(''); const [asrToken, setAsrToken] = useState('');
  const [clearApiKey, setClearApiKey] = useState(false); const [clearAsrToken, setClearAsrToken] = useState(false);
  const [glossary, setGlossary] = useState(Object.entries(saved.glossary).map(([ja, zh]) => `${ja}=${zh}`).join('\n'));
  const [error, setError] = useState('');
  const setTranslation = (patch: Partial<Settings['translation']>) => setConfig(old => ({ ...old, translation: { ...old.translation, ...patch } }));
  const setAsr = (patch: Partial<Settings['asr']>) => setConfig(old => ({ ...old, asr: { ...old.asr, ...patch } }));
  const save = async () => {
    try {
      const entries = glossary.split('\n').filter(line => line.trim()).map(line => { const index = line.indexOf('='); if (index < 1) throw new Error('术语表请按“日语=中文”逐行填写'); return [line.slice(0, index).trim(), line.slice(index + 1).trim()]; });
      const input: Action = { type: 'settings.save', settings: { ...config, glossary: Object.fromEntries(entries) }, apiKey, asrToken, clearApiKey, clearAsrToken };
      setApiKey(''); setAsrToken(''); await act(input); setError('');
    } catch (error) { setError((error as Error).message); }
  };
  return <section className="card settings-panel"><div className="section-title"><h2>识别与翻译</h2><span className="eyebrow">停止时可修改</span></div>
    <p className="muted">保存设置不会启动识别或调用翻译。只有选择声音来源并开始后，识别文本才会发送到指定翻译接口。</p>
    <div className="settings-grid"><label>识别来源<select value={config.asr.backend} onChange={event => setAsr({ backend: event.target.value as 'scripted' | 'external' })}><option value="scripted">预设文本模拟（不识别语音）</option><option value="external">已配置的本地 ASR 服务</option></select></label>
      <label>翻译方式<select value={config.translation.backend} onChange={event => setTranslation({ backend: event.target.value as 'mock' | 'chat' })}><option value="mock">离线模拟翻译</option><option value="chat">自定义兼容 Chat Completions 的 API</option></select></label></div>
    {config.asr.backend === 'scripted' && <p className="notice">模拟识别只根据声音活动展示预设日文，并始终使用模拟翻译；适合检查采集和字幕链路。</p>}
    {config.asr.backend === 'external' && <div className="settings-grid"><label>本地 ASR 地址<input value={config.asr.url} onChange={event => setAsr({ url: event.target.value })} spellCheck={false} /></label><label>服务令牌 {saved.hasAsrToken && <span className="saved">已保存</span>}<input type="password" autoComplete="off" value={asrToken} onChange={event => setAsrToken(event.target.value)} placeholder="留空保留现有令牌" /></label><label className="check"><input type="checkbox" checked={clearAsrToken} onChange={e => setClearAsrToken(e.target.checked)} />清除已保存的服务令牌</label></div>}
    {config.translation.backend === 'chat' && <><div className="settings-grid"><label>完整翻译接口地址<input value={config.translation.endpoint} onChange={event => setTranslation({ endpoint: event.target.value })} placeholder="https://…/v1/chat/completions" spellCheck={false} /></label><label>模型名<input value={config.translation.model} onChange={event => setTranslation({ model: event.target.value })} spellCheck={false} /></label><label>API 密钥 {saved.hasApiKey && <span className="saved">已保存</span>}<input type="password" autoComplete="off" value={apiKey} onChange={event => setApiKey(event.target.value)} placeholder="留空保留；无密钥的本机服务也可使用" /></label><label>输出能力<select value={config.translation.mode} onChange={event => setTranslation({ mode: event.target.value as 'plain' | 'structured' })}><option value="plain">纯译文（默认，不启用 ASR 纠错）</option><option value="structured">结构化 JSON（含保守纠错）</option></select></label></div><label className="check"><input type="checkbox" checked={clearApiKey} onChange={e => setClearApiKey(e.target.checked)} />清除已保存的 API 密钥</label><p className="muted">密钥由客户端后台加密保存，不返回界面，不写入字幕历史。{!saved.canStoreSecrets && '当前系统加密不可用，无法保存新的密钥。'} 请自行确认所选服务的费用和文本使用政策。</p></>}
    <label>术语表 <span className="muted">可选，每行“日语=中文”</span><textarea value={glossary} onChange={event => setGlossary(event.target.value)} rows={4} placeholder="ぺこら=佩克拉" /></label>
    {error && <p className="error" role="alert">{error}</p>}<button className="primary" disabled={disabled} onClick={() => void save()}>保存设置</button>
  </section>;
}

function Main({ state }: { state: AppState }) {
  const [tab, setTab] = useState<'watch' | 'demo' | 'settings'>('watch');
  const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null);
  const [kind, setKind] = useState<'application' | 'output_device'>('application');
  const [selected, setSelected] = useState(''); const [scenario, setScenario] = useState('basic');
  const idle = !state.snapshot || state.snapshot.state === 'idle' && state.snapshot.mode === 'idle';
  const ready = state.connection === 'ready';
  const sources = state.sources.filter(source => source.kind === kind);
  useEffect(() => {
    if (sources.some(source => source.id === selected)) return;
    const suggested = kind === 'application' ? sources.filter(source => source.active) : sources.filter(source => source.is_default);
    setSelected(suggested.length === 1 ? suggested[0].id : '');
  }, [JSON.stringify(sources), selected, kind]);
  const act = async (action: Action) => {
    setBusy(true); setError(null);
    try { const reply = await window.liveTranslator.command(action); if (!reply.ok) throw new Error(reply.error); }
    catch (error) { setError((error as Error).message); throw error; }
    finally { setBusy(false); }
  };
  const run = (action: Action) => void act(action).catch(() => undefined);
  return <div className="app-shell"><aside className="sidebar"><div className="brand"><span className="brand-icon">L<span>t</span></span><div>Live Translator<small>日语直播 · 中文字幕</small></div></div>
    <div className="nav-caption">工作区</div><nav>{([['watch', '观看直播', '◉'], ['demo', '字幕演示', '▷'], ['settings', '设置', '⚙']] as const).map(([id, name, icon]) => <button key={id} className={tab === id ? 'selected' : ''} onClick={() => setTab(id)}><span>{icon}</span>{name}</button>)}</nav>
    <div className="sidebar-bottom"><span className="privacy-mark">音频留在本机</span><p>只采集你选中的来源。<br />直播页面无需改动。</p><span className="version">DESKTOP PREVIEW · 0.2</span></div>
  </aside><main className="workspace"><header className="topbar"><span className="eyebrow">JAPANESE LIVE / 简体中文</span><span className={`status-pill ${ready ? 'good' : ''}`}><i />{statusText(state)}</span></header>
    <div className="workspace-heading"><div><h1>{tab === 'watch' ? '跟上每一句直播' : tab === 'demo' ? '先感受字幕的节奏' : '按你的环境配置'}</h1><p>{tab === 'watch' ? '选择声音来源，中文字幕会出现在独立悬浮窗里。' : tab === 'demo' ? '无需模型、音频设备或 API，体验与真实输入共用的字幕路径。' : '本地识别、云端文本翻译，分别设置。'}</p></div><span className="language-stamp">日<span>→</span>中</span></div>
    {(error || state.error || state.snapshot?.source.error) && <div className="error-banner" role="alert">{error || state.error || state.snapshot?.source.error}{!ready && <button onClick={() => run({ type: 'core.restart' })} disabled={busy}>重启核心</button>}</div>}
    {tab === 'settings' ? <SettingsPanel key={JSON.stringify(state.settings)} saved={state.settings} act={act} disabled={busy || !idle || !ready} /> : <div className="content-grid"><div className="primary-column">
      {tab === 'watch' ? <section className="card source-card"><div className="section-title"><h2><span className="step">01</span>声音来源</h2><button className="text-button" disabled={busy || !idle || !ready} onClick={() => run({ type: 'sources.refresh' })}>↻ 刷新列表</button></div>
        <div className="segmented"><button disabled={!idle} className={kind === 'application' ? 'active' : ''} onClick={() => { setKind('application'); setSelected(''); }}>指定应用</button><button disabled={!idle} className={kind === 'output_device' ? 'active' : ''} onClick={() => { setKind('output_device'); setSelected(''); }}>输出设备混音</button></div>
        <label className="source-label">{kind === 'application' ? '选择正在播放直播的应用' : '选择输出设备'}<select aria-label="声音来源" value={selected} disabled={busy || !idle} onChange={event => setSelected(event.target.value)}><option value="">{sources.length ? '请选择来源' : '暂无来源，请先播放直播后刷新'}</option>{sources.map(source => <option key={source.id} value={source.id}>{source.name}{source.active ? ' · 正在发声' : ''}{source.is_default ? ' · 默认设备' : ''}</option>)}</select></label>
        <p className="source-hint">{kind === 'application' ? '同一浏览器的其他发声标签页可能混入，建议只保留直播页面发声。' : '此模式会采集该设备上所有应用的声音；应用采集失败不会自动切换到这里。'}</p>
        {state.sourceError && <p className="error">来源发现失败，请刷新后重试。</p>}
        <div className="source-mode"><span className="mode-dot" />{state.settings.asr.backend === 'scripted' ? '当前为采集测试：显示预设字幕，不识别主播内容，也不调用翻译 API。' : state.snapshot?.source.asr_backend === 'scripted' ? '本地服务正在输出预设日文，不代表真实识别；翻译按你选择的接口执行。' : `本地 ASR · ${state.settings.translation.backend === 'chat' ? '文本发送至你配置的翻译接口' : '模拟翻译'}`}</div>
        <div className="start-row"><button className="primary start-button" data-testid="start-session" disabled={busy || !ready || !idle || !selected} onClick={() => run({ type: 'session.start', sourceId: selected })}>▷ {state.settings.asr.backend === 'scripted' ? '开始采集测试' : '开始翻译'}</button><button className="secondary" data-testid="stop-session" disabled={busy || !ready || idle} onClick={() => run({ type: 'session.stop' })}>停止</button></div>
        {!selected && <p className="muted small">只列出来源，点击开始后才采集声音。</p>}
      </section> : <section className="card"><div className="section-title"><h2>选择一个演示场景</h2><span className="saved">完全离线</span></div><label>场景<select value={scenario} onChange={e => setScenario(e.target.value)}>{state.scenarios.map(s => <option key={s.name} value={s.name}>{s.title}</option>)}</select></label><p className="source-hint">{state.scenarios.find(s => s.name === scenario)?.description}</p><div className="start-row"><button className="primary" data-testid="start-demo" disabled={busy || !ready || !idle} onClick={() => run({ type: 'demo.start', scenario })}>▷ 播放演示</button><button className="secondary" disabled={busy || idle} onClick={() => run({ type: 'session.stop' })}>停止演示</button></div></section>}
      <section className="card preview-card"><div className="section-title"><h2><span className="step">02</span>字幕预览</h2><span className="muted small">与悬浮窗同步</span></div><div className="preview-backdrop"><div className="preview-topline"><span>LIVE</span><span>{state.snapshot?.source.label || '等待开始'}</span></div><Subtitles state={state} preview /></div><p className="source-hint">当前条可以修订，前一条锁定。完整内容可在下方回看。</p></section>
      <History state={state} />
    </div><div className="secondary-column"><section className="card overlay-controls"><div className="section-title"><h2>悬浮字幕</h2><span className="tiny-icon">▱</span></div>
      {([['visible', '显示悬浮窗'], ['locked', '锁定窗口位置'], ['clickThrough', '鼠标点击穿透']] as const).map(([key, label]) => <label className="toggle-row" key={key}><span>{label}</span><input role="switch" type="checkbox" checked={state.overlay[key]} onChange={event => run({ type: 'overlay.update', patch: { [key]: event.target.checked } })} /></label>)}
      <p className="muted small">穿透后可在这里关闭穿透。解锁位置后，拖动悬浮窗顶部移动。</p><label className="range-label">字号<span>{state.overlay.fontSize}px</span><input type="range" min="20" max="48" value={state.overlay.fontSize} onChange={event => run({ type: 'overlay.update', patch: { fontSize: Number(event.target.value) } })} /></label><label className="range-label">宽度<span>{state.overlay.width}px</span><input type="range" min="480" max="1100" step="20" value={state.overlay.width} onChange={event => run({ type: 'overlay.update', patch: { width: Number(event.target.value) } })} /></label>
    </section><section className="try-demo"><span className="eyebrow">无需配置，先试一下</span><h3>看看字幕怎样跟上话题</h3><p>否定晚到、乱序返回、长译文和采集缺口，都有固定演示。</p><button className="demo-link" data-testid="quick-demo" disabled={busy || !ready || !idle} onClick={() => { setTab('demo'); run({ type: 'demo.start', scenario: 'basic' }); }}>播放基础演示 <span>↗</span></button></section>
      <details className="diagnostics"><summary>运行诊断</summary><dl><dt>翻译请求</dt><dd>{state.snapshot?.stats.requests_sent ?? 0}</dd><dt>在途 / 待处理</dt><dd>{state.snapshot?.activity.in_flight ?? 0} / {state.snapshot?.activity.pending ?? 0}</dd><dt>音频缺口</dt><dd>{state.snapshot?.source.gap_ms ?? 0} ms</dd><dt>HTTP 成功 / 失败</dt><dd>{state.http.completed} / {state.http.failed}</dd><dt>最近 HTTP 耗时</dt><dd>{state.http.lastMs === null ? '—' : `${state.http.lastMs} ms`}</dd></dl><button className="text-button" disabled={busy} onClick={() => run({ type: 'core.restart' })}>重启字幕核心</button></details>
    </div></div>}
    <footer className="workspace-footer"><span>默认不采集麦克风 · 不保存录音</span><span>{state.snapshot?.mode === 'demo' ? '演示文本与译文均为预设' : '模型尚需单独配置与验收'}</span></footer>
  </main></div>;
}
function App() {
  const state = useAppState();
  if (!state) return <div className="loading">正在准备字幕工作区…</div>;
  return overlayView ? <Overlay state={state} /> : <Main state={state} />;
}
createRoot(document.getElementById('root')!).render(<App />);
