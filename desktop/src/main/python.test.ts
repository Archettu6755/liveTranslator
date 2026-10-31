import { test } from 'node:test';
import assert from 'node:assert/strict';
import { join, dirname, resolve, basename } from 'node:path';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { CoreProcess, JsonLines, MAX_LINE, pythonEnvironment, pythonPath } from './python';

test('JSONL preserves split UTF-8 and rejects oversized or non-object messages', () => {
  const values: unknown[] = []; const lines = new JsonLines(value => values.push(value));
  for (const byte of Buffer.from('{"text":"日语直播"}\n{"next":true}\n')) lines.push(Buffer.from([byte]));
  assert.deepEqual(values, [{ text: '日语直播' }, { next: true }]);
  assert.throws(() => new JsonLines(() => {}).push(Buffer.from('x'.repeat(MAX_LINE + 1))), /过大/);
  assert.throws(() => new JsonLines(() => {}).push(Buffer.from('[]\n')));
});
test('ASR and core child environments do not inherit translation credentials', () => {
  process.env.LIVE_TRANSLATOR_TEST_API_KEY = 'never-forward-this';
  try { assert.equal(pythonEnvironment().LIVE_TRANSLATOR_TEST_API_KEY, undefined); }
  finally { delete process.env.LIVE_TRANSLATOR_TEST_API_KEY; }
});
test('a client bundle uses only its private Python and never falls back to a developer environment', t => {
  const root = mkdtempSync(join(tmpdir(), 'lt-bundle-test-'));
  t.after(() => { assert.equal(dirname(resolve(root)), resolve(tmpdir())); assert.ok(basename(root).startsWith('lt-bundle-test-')); rmSync(root, { recursive: true, force: true }); });
  writeFileSync(join(root, 'runtime-manifest.json'), '{}');
  assert.throws(() => pythonPath(root), /运行组件缺失/);
  mkdirSync(join(root, 'python')); writeFileSync(join(root, 'python/python.exe'), 'fixture');
  assert.equal(pythonPath(root), join(root, 'python/python.exe'));
  const environment = pythonEnvironment({}, root);
  const system = process.env.SystemRoot ?? 'C:\\Windows';
  assert.equal(environment.PATH, [join(root, 'python'), join(system, 'System32'), system].join(';'));
  assert.equal(environment.PYTHONHOME, undefined); assert.equal(environment.CONDA_PREFIX, undefined);
});
test('real Python process supports handshake, command errors, shared snapshots and drained stop', { timeout: 20_000 }, async t => {
  const core = new CoreProcess(); t.after(() => core.close());
  const snapshots: Record<string, unknown>[] = [];
  core.on('message', message => { if (message.type === 'snapshot') snapshots.push(message); });
  core.on('fault', () => {});
  await core.start(join(__dirname, '../../..'));
  await assert.rejects(core.command('invalid.operation'), /拒绝/);
  await core.command('demo.start', { scenario: 'basic' });
  const deadline = Date.now() + 5_000;
  while (!snapshots.some(item => item.current) && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 40));
  assert.ok(snapshots.some(item => item.current));
  const stopped = await core.command('session.stop', {}, 'session.stopped');
  assert.equal(stopped.type, 'session.stopped');
  assert.equal(snapshots.at(-1)?.mode, 'idle');
  assert.equal(snapshots.at(-1)?.current, null);
  await core.close(); assert.equal(core.process.child, null);
});
