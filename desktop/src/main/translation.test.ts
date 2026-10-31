import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { once } from 'node:events';
import type { TranslationRequest } from '../shared/types';
import { translate } from './translation';

const request: TranslationRequest = { type: 'translate.request', request_id: 'r1', session_id: 's', segment_id: 1, source_revision: 1, final: true, attempt: 1, messages: [{ role: 'system', content: '翻译为中文' }, { role: 'user', content: 'こんにちは' }] };
test('HTTP execution preserves prompts, bounds responses, refuses redirects and redacts service errors', async t => {
  let redirected = 0; let seen: Record<string, unknown> = {};
  const server = createServer(async (req, res) => {
    if (req.url === '/ok') {
      const chunks = []; for await (const chunk of req) chunks.push(chunk);
      seen = { auth: req.headers.authorization, body: JSON.parse(Buffer.concat(chunks).toString()) };
      res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify({ choices: [{ message: { content: '你好' } }] }));
    } else if (req.url === '/redirect') { res.writeHead(302, { Location: '/target' }); res.end(); }
    else if (req.url === '/target') { redirected++; res.end('should not be called'); }
    else if (req.url === '/large') { res.end('x'.repeat(270 * 1024)); }
    else { res.writeHead(401); res.end('private-test-key sensitive source text'); }
  });
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  t.after(() => { server.closeAllConnections(); server.close(); });
  const address = server.address(); assert.ok(address && typeof address !== 'string');
  const config = (path: string) => ({ backend: 'chat' as const, endpoint: `http://127.0.0.1:${address.port}${path}`, model: 'fixture', mode: 'plain' as const });
  assert.equal(await translate(request, config('/ok'), 'private-test-key', new AbortController().signal), '你好');
  assert.equal(seen.auth, 'Bearer private-test-key');
  assert.deepEqual((seen.body as Record<string, unknown>).messages, request.messages);
  assert.equal((seen.body as Record<string, unknown>).stream, false);
  await assert.rejects(translate(request, config('/redirect'), 'private-test-key', new AbortController().signal), /连接或回复无效/);
  assert.equal(redirected, 0);
  await assert.rejects(translate(request, config('/large'), '', new AbortController().signal), /连接或回复无效/);
  await assert.rejects(translate(request, config('/error'), 'private-test-key', new AbortController().signal), /^Error: 翻译服务返回 HTTP 401$/);
  const abort = new AbortController(); abort.abort();
  await assert.rejects(translate(request, config('/ok'), '', abort.signal), /translation_cancelled/);
});
