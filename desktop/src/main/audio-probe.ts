import { app } from 'electron';
import assert from 'node:assert/strict';
import { spawn, type ChildProcess } from 'node:child_process';
import { createServer } from 'node:http';
import { once } from 'node:events';
import { randomBytes } from 'node:crypto';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { createApplication } from './app';
import { PythonProcess, pythonEnvironment, pythonPath } from './python';

app.setName('Live Translator Audio Probe');
app.commandLine.appendSwitch('disable-gpu');
const root = join(__dirname, '../../..'); const output = join(root, 'artifacts/audio-probe');
mkdirSync(join(output, 'runtime'), { recursive: true }); app.setPath('userData', join(output, 'runtime'));
const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));
async function until(predicate: () => boolean, message: string, timeout = 12_000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) { if (predicate()) return; await delay(60); }
  throw new Error(message);
}
app.whenReady().then(async () => {
  if (process.platform !== 'win32') throw new Error('The controlled audio probe requires Windows.');
  const desktop = await createApplication({ show: false, settingsPath: join(output, 'settings.json') });
  const worker = new PythonProcess(); let player: ChildProcess | null = null;
  let requests = 0; let authorized = true;
  let diagnostics = '';
  const server = createServer(async (request, response) => {
    const chunks = []; for await (const chunk of request) chunks.push(chunk);
    const data = JSON.parse(Buffer.concat(chunks).toString());
    assert.ok(Array.isArray(data.messages));
    authorized &&= request.headers.authorization === 'Bearer fixture-api-key'; requests++;
    response.setHeader('Content-Type', 'application/json');
    response.end(JSON.stringify({ choices: [{ message: { content: '你好，这是采集链路测试。' } }] }));
  });
  try {
    await until(() => desktop.controller.state.connection === 'ready', 'core not ready');
    desktop.controller.core.process.child?.stderr.on('data', chunk => { diagnostics = (diagnostics + chunk.toString()).slice(-12_000); });
    server.listen(0, '127.0.0.1'); await once(server, 'listening');
    const address = server.address(); assert.ok(address && typeof address !== 'string');
    const token = randomBytes(32).toString('hex');
    const listening = once(worker, 'message'); worker.on('fault', () => {});
    worker.start(root, ['asr-worker', '--backend', 'scripted'], { LIVE_TRANSLATOR_ASR_TOKEN: token });
    const [ready] = await Promise.race([listening, delay(12_000).then(() => { throw new Error('worker did not start'); })]);
    const settings = { translation: { backend: 'chat', endpoint: `http://127.0.0.1:${address.port}/v1/chat/completions`, model: 'loopback-fixture', mode: 'plain' }, asr: { backend: 'external', url: `ws://127.0.0.1:${ready.port}/v1/asr` }, glossary: {} };
    const reply = await desktop.main.webContents.executeJavaScript(`window.liveTranslator.command(${JSON.stringify({ type: 'settings.save', settings, apiKey: 'fixture-api-key', asrToken: token })})`);
    assert.equal(reply.ok, true);
    const tone = [
      'import io, math, struct, time, wave, winsound',
      'buffer = io.BytesIO()',
      'with wave.open(buffer, "wb") as wav:',
      ' wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)',
      ' wav.writeframes(b"".join(struct.pack("<h", int(900*math.sin(2*math.pi*440*i/16000))) for i in range(16000)))',
      'for _ in range(6):',
      ' winsound.PlaySound(buffer.getvalue(), winsound.SND_MEMORY); time.sleep(0.25)',
      'time.sleep(2)',
    ].join('\n');
    player = spawn(pythonPath(root), ['-I', '-u', '-c', tone], { cwd: join(root, 'core'), env: pythonEnvironment(), windowsHide: true, stdio: 'ignore' });
    const pid = player.pid; assert.ok(pid);
    let sourceId = '';
    for (let attempt = 0; attempt < 15; attempt++) {
      await delay(200); await desktop.controller.dispatch({ type: 'sources.refresh' }, 'main');
      sourceId = desktop.controller.state.sources.find(source => source.root_pid === pid)?.id ?? '';
      if (sourceId) break;
    }
    assert.ok(sourceId, 'tone-playing application was not discovered');
    const started = await desktop.main.webContents.executeJavaScript(`window.liveTranslator.command(${JSON.stringify({ type: 'session.start', sourceId })})`);
    assert.equal(started.ok, true, started.error);
    await until(() => requests > 0 && !!desktop.controller.state.snapshot?.current, 'audio did not reach fixture translation and subtitle');
    assert.equal(desktop.controller.state.snapshot?.source.capturing, true);
    assert.equal(desktop.controller.state.snapshot?.source.asr_backend, 'scripted');
    assert.equal(desktop.controller.state.snapshot?.current?.text, '你好，这是采集链路测试。');
    const sourceStats = desktop.controller.state.snapshot?.source;
    const stopped = await desktop.main.webContents.executeJavaScript('window.liveTranslator.command({type:"session.stop"})');
    assert.equal(stopped.ok, true); assert.equal(desktop.controller.state.snapshot?.mode, 'idle');
    assert.ok(authorized && requests > 0);
    assert.ok(!JSON.stringify(desktop.controller.state).includes(token));
    assert.ok(!JSON.stringify(desktop.controller.state).includes('fixture-api-key'));
    writeFileSync(join(output, 'result.json'), JSON.stringify({ result: 'PASS', selectedApplicationPid: pid, sourceStats, fixtureHttpRequests: requests, fixtureAuthVerified: authorized, nativeApplicationCapture: true, realAsr: false, realTranslation: false, recordingSaved: false, externalNetworkUsed: false, drainedStop: true }, null, 2));
    console.log(`Controlled application audio probe passed: ${output}`);
  } catch (error) {
    console.error(error);
    console.error(diagnostics);
    writeFileSync(join(output, 'result.json'), JSON.stringify({ result: 'FAIL', error: String(error), source: desktop.controller.state.snapshot?.source }, null, 2));
    process.exitCode = 1;
  } finally {
    await desktop.close(); await worker.close();
    if (player && player.exitCode === null) { const closed = once(player, 'close'); player.kill(); await closed; }
    server.closeAllConnections(); server.close(); app.exit(Number(process.exitCode ?? 0));
  }
}).catch(error => { console.error(error); app.exit(1); });
