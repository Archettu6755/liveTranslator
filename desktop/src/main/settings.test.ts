import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve, dirname, basename } from 'node:path';
import { DEFAULTS, SettingsStore } from './settings';
import { action, endpoint } from './validation';

const cipher = {
  isEncryptionAvailable: () => true,
  encryptString: (text: string) => Buffer.from([...Buffer.from(text)].map(byte => byte ^ 91)),
  decryptString: (data: Buffer) => Buffer.from([...data].map(byte => byte ^ 91)).toString(),
};
test('keys remain in the main-process store; failed encryption never writes plaintext', async t => {
  const folder = mkdtempSync(join(tmpdir(), 'lt-desktop-test-'));
  t.after(() => { assert.equal(dirname(resolve(folder)), resolve(tmpdir())); assert.ok(basename(folder).startsWith('lt-desktop-test-')); rmSync(folder, { recursive: true, force: true }); });
  const path = join(folder, 'settings.json');
  const store = new SettingsStore(path, cipher);
  await store.save({ type: 'settings.save', settings: DEFAULTS, apiKey: 'private-test-key', asrToken: 'private-local-token' });
  assert.equal(await store.secret('apiKey'), 'private-test-key');
  assert.equal(store.public().hasApiKey, true);
  assert.ok(!JSON.stringify(store.public()).includes('private-'));
  assert.ok(!readFileSync(path, 'utf8').includes('private-'));
  const restored = new SettingsStore(path, cipher);
  assert.equal(await restored.secret('asrToken'), 'private-local-token');
  await restored.save({ type: 'settings.save', settings: DEFAULTS, clearApiKey: true });
  assert.equal(await restored.secret('apiKey'), '');
  const unavailable = new SettingsStore(join(folder, 'no-crypto.json'), { ...cipher, isEncryptionAvailable: () => false });
  await assert.rejects(unavailable.save({ type: 'settings.save', settings: DEFAULTS, apiKey: 'never-plaintext' }), /加密不可用/);
  assert.equal(unavailable.public().hasApiKey, false);
});
test('unsafe URLs, injected IPC fields and invalid overlay bounds are rejected', () => {
  for (const url of ['http://example.com/v1', 'https://user:secret@example.com/v1', 'https://example.com/v1?api_key=secret', 'file:///test', 'http://127.0.0.1.example.com/v1']) assert.throws(() => endpoint(url));
  for (const url of ['ws://0.0.0.0/v1/asr', 'ws://example.com/v1/asr', 'ws://localhost/wrong']) assert.throws(() => endpoint(url, true));
  assert.equal(endpoint('http://127.0.0.1:5432/v1'), 'http://127.0.0.1:5432/v1');
  assert.equal(endpoint('ws://[::1]:5432/v1/asr', true), 'ws://[::1]:5432/v1/asr');
  assert.throws(() => action({ type: 'session.start', sourceId: 'app:1', command: 'untrusted' }));
  assert.throws(() => action({ type: 'overlay.update', patch: { fontSize: 900 } }));
  assert.throws(() => action({ type: 'settings.save', settings: DEFAULTS, apiKey: 'value\r\nHeader: injected' }));
});
