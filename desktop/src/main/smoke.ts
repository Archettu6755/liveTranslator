import { app } from 'electron';
import assert from 'node:assert/strict';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { createApplication } from './app';

app.setName('Live Translator Smoke');
app.commandLine.appendSwitch('disable-gpu');
const output = join(__dirname, '../../../artifacts/desktop-smoke');
mkdirSync(join(output, 'runtime'), { recursive: true });
app.setPath('userData', join(output, 'runtime'));
const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));
async function until(predicate: () => boolean | Promise<boolean>, message: string, budget = 12_000) {
  const deadline = Date.now() + budget;
  while (Date.now() < deadline) { if (await predicate()) return; await delay(50); }
  throw new Error(message);
}
app.whenReady().then(async () => {
  const desktop = await createApplication({ show: false, settingsPath: join(output, 'settings.json') });
  const { controller, main, overlay } = desktop;
  try {
    await until(() => controller.state.connection === 'ready', 'core did not become ready');
    assert.equal(await main.webContents.executeJavaScript('typeof window.require'), 'undefined');
    assert.equal(await main.webContents.executeJavaScript('typeof window.process'), 'undefined');
    const rendererMetric = app.getAppMetrics().find(metric => metric.pid === main.webContents.getOSProcessId());
    assert.equal(rendererMetric?.sandboxed, true);
    await main.webContents.executeJavaScriptInIsolatedWorld(999, [{ code: 'window.__isolationProbe = true' }]);
    assert.equal(await main.webContents.executeJavaScript('window.__isolationProbe'), undefined);
    const saved = await main.webContents.executeJavaScript(`(async () => {
      const { translation, asr, glossary } = (await window.liveTranslator.getState()).settings;
      return window.liveTranslator.command({type:'settings.save',settings:{translation,asr,glossary},apiKey:'smoke-test-not-a-real-key'});
    })()`);
    assert.equal(saved.ok, true);
    assert.equal(await controller.store.secret('apiKey'), 'smoke-test-not-a-real-key');
    assert.ok(!JSON.stringify(controller.state).includes('smoke-test-not-a-real-key'));
    assert.ok(!readFileSync(join(output, 'settings.json'), 'utf8').includes('smoke-test-not-a-real-key'));
    const forbidden = await overlay.webContents.executeJavaScript('window.liveTranslator.command({type:"session.stop"})');
    assert.equal(forbidden.ok, false);
    await main.webContents.executeJavaScript('document.querySelector("[data-testid=quick-demo]").click()');
    await until(() => !!controller.state.snapshot?.current, 'demo did not render a subtitle');
    await until(async () => {
      const values = await Promise.all([main, overlay].map(win => win.webContents.executeJavaScript('document.querySelector("[data-testid=current-cue]").textContent')));
      return values.every(value => typeof value === 'string' && /[\u4e00-\u9fff]/.test(value) && value !== '字幕会显示在这里') && values[0] === values[1];
    }, 'main and overlay did not share a Chinese subtitle');
    for (const win of [main, overlay]) await win.webContents.executeJavaScript('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))');
    writeFileSync(join(output, 'main.png'), (await main.webContents.capturePage()).toPNG());
    writeFileSync(join(output, 'overlay.png'), (await overlay.webContents.capturePage()).toPNG());
    const overlayResult = await main.webContents.executeJavaScript('window.liveTranslator.command({type:"overlay.update",patch:{locked:false,clickThrough:true,fontSize:48,width:480}})');
    assert.equal(overlayResult.ok, true); assert.equal(overlay.isMovable(), true); assert.equal(overlay.isAlwaysOnTop(), true);
    assert.equal(controller.state.overlay.clickThrough, true);
    await main.webContents.executeJavaScript('window.liveTranslator.command({type:"overlay.update",patch:{locked:true,clickThrough:false,fontSize:30,width:800}})');
    await main.webContents.executeJavaScript('window.liveTranslator.command({type:"session.stop"})');
    assert.equal(controller.state.snapshot?.mode, 'idle'); assert.equal(controller.state.snapshot?.current, null);
    await until(async () => await overlay.webContents.executeJavaScript('getComputedStyle(document.querySelector(".floating")).visibility === "hidden"'), 'stopped overlay was not hidden');
    const oldPid = controller.core.process.child?.pid;
    await main.webContents.executeJavaScript('window.liveTranslator.command({type:"core.restart"})');
    assert.equal(controller.state.connection, 'ready'); assert.equal(controller.state.error, null); assert.notEqual(controller.core.process.child?.pid, oldPid);
    await desktop.close(); assert.equal(controller.core.process.child, null);
    writeFileSync(join(output, 'result.json'), JSON.stringify({ result: 'PASS', sharedChineseSubtitle: true, isolatedRenderer: true, encryptedSecretStorage: true, overlayPermissions: true, windowControls: true, drainedStop: true, restart: true, childExited: true, windowsManualClickThroughAcceptance: false }, null, 2));
    console.log(`Desktop smoke passed. Screenshots: ${output}`); app.exit(0);
  } catch (error) {
    console.error(error);
    writeFileSync(join(output, 'result.json'), JSON.stringify({ result: 'FAIL', error: String(error), connection: controller.state.connection, message: controller.state.error }, null, 2));
    await desktop.close(); app.exit(1);
  }
}).catch(error => { console.error(error); app.exit(1); });
