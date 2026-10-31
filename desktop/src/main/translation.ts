import type { Settings, TranslationRequest } from '../shared/types';
import { endpoint, object, text } from './validation';

export function translationRequest(value: unknown): TranslationRequest {
  const data = object(value);
  for (const key of ['request_id', 'session_id']) text(data[key], 200);
  for (const key of ['segment_id', 'source_revision', 'attempt']) if (!Number.isSafeInteger(data[key]) || (data[key] as number) < 1) throw new Error('翻译请求版本无效');
  if (typeof data.final !== 'boolean' || !Array.isArray(data.messages) || data.messages.length !== 2) throw new Error('翻译请求无效');
  data.messages.forEach((entry, index) => {
    const message = object(entry);
    if (message.role !== (index === 0 ? 'system' : 'user')) throw new Error('翻译消息角色无效');
    text(message.content, 64_000);
  });
  return data as unknown as TranslationRequest;
}
export async function translate(
  request: TranslationRequest, config: Settings['translation'], apiKey: string,
  signal: AbortSignal, fetcher: typeof fetch = fetch,
): Promise<string> {
  const url = endpoint(config.endpoint);
  const timeout = AbortSignal.timeout(6_000);
  const combined = AbortSignal.any([signal, timeout]);
  try {
    const response = await fetcher(url, {
      method: 'POST', redirect: 'error', signal: combined,
      headers: { 'Content-Type': 'application/json', ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}) },
      body: JSON.stringify({ model: config.model, messages: request.messages, stream: false }),
    });
    if (!response.ok) { await response.body?.cancel(); throw new Error(`HTTP ${response.status}`); }
    if (!response.body) throw new Error('empty response');
    const reader = response.body.getReader();
    const chunks: Uint8Array[] = []; let size = 0;
    try {
      while (true) {
        const part = await reader.read(); if (part.done) break;
        size += part.value.byteLength;
        if (size > 256 * 1024) throw new Error('response too large');
        chunks.push(part.value);
      }
    } finally { await reader.cancel().catch(() => undefined); }
    const data = object(JSON.parse(Buffer.concat(chunks).toString('utf8')));
    const choice = Array.isArray(data.choices) ? object(data.choices[0]) : {};
    const message = object(choice.message);
    if (message.tool_calls || message.function_call) throw new Error('unexpected tool request');
    return text(message.content, 16_000);
  } catch (error) {
    if (signal.aborted) throw new Error('translation_cancelled');
    if (timeout.aborted) throw new Error('translation_timeout');
    if (error instanceof Error && /^HTTP \d{3}$/.test(error.message)) throw new Error(`翻译服务返回 ${error.message}`);
    throw new Error('翻译连接或回复无效，请检查接口、模型及密钥');
  }
}
