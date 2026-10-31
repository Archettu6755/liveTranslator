import { test } from 'node:test';
import assert from 'node:assert/strict';
import { join } from 'node:path';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, resolve, basename } from 'node:path';
import { once } from 'node:events';
import { Controller } from './controller';
import { SettingsStore } from './settings';

test('a crashed core clears subtitles, rejects overlay privileges and restarts without resuming capture', { timeout: 20_000 }, async t => {
  const directory = mkdtempSync(join(tmpdir(), 'lt-desktop-test-'));
  const store = new SettingsStore(join(directory, 'settings.json'), { isEncryptionAvailable: () => false, encryptString: () => { throw new Error('unavailable'); }, decryptString: () => { throw new Error('unavailable'); } });
  const controller = new Controller(join(__dirname, '../../..'), store);
  t.after(async () => { await controller.close(); assert.equal(dirname(resolve(directory)), resolve(tmpdir())); assert.ok(basename(directory).startsWith('lt-desktop-test-')); rmSync(directory, { recursive: true, force: true }); });
  await controller.start();
  assert.equal(controller.state.connection, 'ready');
  await assert.rejects(controller.dispatch({ type: 'session.start', sourceId: 'app:999999' }, 'overlay'), /无权/);
  await controller.dispatch({ type: 'demo.start', scenario: 'basic' }, 'main');
  const deadline = Date.now() + 5_000;
  while (!controller.state.snapshot?.current && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 40));
  assert.ok(controller.state.snapshot?.current);
  const closed = once(controller.core, 'closed'); controller.core.process.child!.kill(); await closed;
  assert.equal(controller.state.connection, 'error'); assert.equal(controller.state.snapshot, null);
  await controller.dispatch({ type: 'core.restart' }, 'main');
  assert.equal(controller.state.connection, 'ready'); assert.equal(controller.state.error, null);
  const restartedState = (() => controller.state)();
  assert.ok(!restartedState.snapshot || restartedState.snapshot.mode === 'idle');
});
