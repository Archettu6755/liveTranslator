import { app } from 'electron';
import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { join, relative, isAbsolute } from 'node:path';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { createApplication } from './app';
import { pythonEnvironment, pythonPath, PythonProcess } from './python';

const execute = promisify(execFile);
const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));
async function until(predicate: () => boolean | Promise<boolean>, reason: string, budget = 15_000) {
  const deadline = Date.now() + budget;
  while (Date.now() < deadline) { if (await predicate()) return; await delay(40); }
  throw new Error(reason);
}
export async function runPackageSmoke(output: string): Promise<void> {
  assert.ok(app.isPackaged, 'This check must run from the distributed executable');
  mkdirSync(output, { recursive: true });
  const root = process.resourcesPath;
  const privatePython = pythonPath(root);
  const auditCode = `import importlib.metadata as m,json,sys,ssl,ctypes
import numpy,soxr,websockets,comtypes,live_translator.audio.capture
print(json.dumps({'version':sys.version.split()[0],'executable':sys.executable,'prefix':sys.prefix,'base_prefix':sys.base_prefix,'search_paths':sys.path,'modules':{name:sys.modules[name].__file__ for name in ['numpy','soxr','websockets','comtypes','live_translator']},'dependencies':{name:m.version(name) for name in ['numpy','soxr','websockets','comtypes']}}))`;
  const { stdout } = await execute(privatePython, ['-I', '-B', '-c', auditCode], { cwd: output, env: pythonEnvironment({}, root), windowsHide: true, timeout: 15_000 });
  const audit = JSON.parse(stdout);
  const inside = (path: string) => { const rel = relative(root, path); return !isAbsolute(rel) && rel !== '..' && !rel.startsWith('..\\') && !rel.startsWith('../'); };
  for (const path of [audit.executable, audit.prefix, audit.base_prefix, ...audit.search_paths, ...Object.values(audit.modules)] as string[]) assert.ok(inside(path), 'Runtime escaped the client package');
  writeFileSync(join(output, 'runtime-audit.json'), JSON.stringify(audit, null, 2));
  const desktop = await createApplication({ show: false, settingsPath: join(output, 'settings.json') });
  const { controller, main, overlay } = desktop;
  const worker = new PythonProcess();
  try {
    await until(() => controller.state.connection === 'ready', 'Bundled core did not start');
    assert.equal(controller.state.error, null);
    await controller.dispatch({ type: 'sources.refresh' }, 'main');
    assert.equal(controller.state.sourceError, null, 'Windows source discovery did not load');
    assert.equal(await main.webContents.executeJavaScript('typeof window.require'), 'undefined');
    assert.equal(await main.webContents.executeJavaScript('typeof window.process'), 'undefined');
    assert.equal(app.getAppMetrics().find(metric => metric.pid === main.webContents.getOSProcessId())?.sandboxed, true);
    const saved = await main.webContents.executeJavaScript(`(async () => {
      const {translation,asr,glossary}=(await window.liveTranslator.getState()).settings;
      return window.liveTranslator.command({type:'settings.save',settings:{translation,asr,glossary},apiKey:'package-self-test-placeholder'});
    })()`);
    assert.equal(saved.ok, true);
    assert.ok(!readFileSync(join(output, 'settings.json'), 'utf8').includes('package-self-test-placeholder'));
    assert.equal(await controller.store.secret('apiKey'), 'package-self-test-placeholder');
    assert.ok(!JSON.stringify(controller.state).includes('package-self-test-placeholder'));
    const forbidden = await overlay.webContents.executeJavaScript('window.liveTranslator.command({type:"session.stop"})');
    assert.equal(forbidden.ok, false);
    await main.webContents.executeJavaScript('document.querySelector("[data-testid=quick-demo]").click()');
    await until(() => !!controller.state.snapshot?.current, 'Bundled demo produced no subtitle');
    await until(async () => {
      const texts = await Promise.all([main, overlay].map(win => win.webContents.executeJavaScript('document.querySelector("[data-testid=current-cue]").textContent')));
      return texts[0] === texts[1] && /[\u4e00-\u9fff]/.test(texts[0]) && texts[0] !== '字幕会显示在这里';
    }, 'Packaged windows did not share the subtitle');
    for (const win of [main, overlay]) await win.webContents.executeJavaScript('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');
    writeFileSync(join(output, 'main.png'), (await main.webContents.capturePage()).toPNG());
    writeFileSync(join(output, 'overlay.png'), (await overlay.webContents.capturePage()).toPNG());
    await main.webContents.executeJavaScript('window.liveTranslator.command({type:"session.stop"})');
    assert.equal(controller.state.snapshot?.current, null);
    const priorPid = controller.core.process.child?.pid;
    await main.webContents.executeJavaScript('window.liveTranslator.command({type:"core.restart"})');
    assert.equal(controller.state.connection, 'ready'); assert.equal(controller.state.error, null);
    assert.notEqual(controller.core.process.child?.pid, priorPid);
    const listening = new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Bundled simulation worker did not start')), 12_000);
      worker.once('message', message => { clearTimeout(timer); if (message.type === 'asr.listening') resolve(); else reject(new Error('Invalid worker readiness')); });
      worker.once('fault', () => { clearTimeout(timer); reject(new Error('Bundled worker failed')); });
    });
    worker.start(root, ['asr-worker', '--backend', 'scripted'], { LIVE_TRANSLATOR_ASR_TOKEN: 'package-smoke-fixture-token-not-a-credential' });
    await listening; await worker.close();
    await desktop.close();
    assert.equal(controller.core.process.child, null);
    writeFileSync(join(output, 'result.json'), JSON.stringify({ result: 'PASS', packaged: app.isPackaged, executable: process.execPath, privatePython, independentRuntime: true, windowsSourceDiscovery: true, sharedChineseSubtitles: true, rendererSandbox: true, encryptedSettings: true, drainedStop: true, restartedCore: true, bundledSimulationWorker: true, childrenExited: true, realAsrConfigured: false, realTranslationUsed: false }, null, 2));
    console.log('Packaged client verification passed'); app.exit(0);
  } catch (error) {
    writeFileSync(join(output, 'result.json'), JSON.stringify({ result: 'FAIL', error: String(error), connection: controller.state.connection, message: controller.state.error }, null, 2));
    await worker.close(); await desktop.close(); app.exit(1);
  }
}
