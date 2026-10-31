import { isIP } from 'node:net';
import type { Action, OverlaySettings, Settings } from '../shared/types';

export function object(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) throw new Error('需要对象格式');
  return value as Record<string, unknown>;
}
export function text(value: unknown, max = 200, empty = false): string {
  if (typeof value !== 'string' || value.length > max || (!empty && !value.trim())) throw new Error('文本字段无效');
  return value;
}
export function exact(value: Record<string, unknown>, allowed: string[]): void {
  if (Object.keys(value).some(key => !allowed.includes(key))) throw new Error('包含不支持的字段');
}
export function loopback(host: string): boolean {
  host = host.replace(/^\[|\]$/g, '').toLowerCase();
  return host === 'localhost' || host === '::1' || (isIP(host) === 4 && host.split('.')[0] === '127');
}
export function endpoint(value: unknown, asr = false): string {
  const input = text(value, 2048);
  let url: URL;
  try { url = new URL(input); } catch { throw new Error('接口地址无效'); }
  if (url.username || url.password || url.hash || url.search || /[\r\n]/.test(input)) throw new Error('接口地址不能包含凭据、查询参数或片段');
  if (asr ? url.protocol !== 'ws:' || !loopback(url.hostname) || url.pathname !== '/v1/asr'
    : url.protocol !== 'https:' && !(url.protocol === 'http:' && loopback(url.hostname))) {
    throw new Error(asr ? 'ASR 仅允许本机 ws://…/v1/asr 地址' : '翻译接口必须使用 HTTPS，本机测试可用 HTTP');
  }
  return url.href;
}
export function settings(value: unknown): Settings {
  const data = object(value); exact(data, ['translation', 'asr', 'glossary']);
  const translation = object(data.translation); exact(translation, ['backend', 'endpoint', 'model', 'mode']);
  const asr = object(data.asr); exact(asr, ['backend', 'url']);
  if (!['mock', 'chat'].includes(String(translation.backend)) || !['plain', 'structured'].includes(String(translation.mode))) throw new Error('翻译模式无效');
  if (!['scripted', 'external'].includes(String(asr.backend))) throw new Error('ASR 模式无效');
  const address = text(translation.endpoint, 2048, true).trim();
  if (address) endpoint(address);
  const model = text(translation.model, 160, true).trim();
  if (translation.backend === 'chat' && (!address || !model)) throw new Error('请填写完整的翻译接口地址和模型名');
  const asrAddress = endpoint(asr.url, true);
  const glossary = object(data.glossary);
  if (Object.keys(glossary).length > 200 || Object.entries(glossary).some(([key, value]) => key.length > 64 || !key || typeof value !== 'string' || !value || value.length > 64 || ['__proto__', 'constructor', 'prototype'].includes(key))) throw new Error('术语表最多 200 项，每项不超过 64 字');
  return { translation: { backend: translation.backend as 'mock' | 'chat', endpoint: address, model, mode: translation.mode as 'plain' | 'structured' }, asr: { backend: asr.backend as 'scripted' | 'external', url: asrAddress }, glossary: { ...glossary } as Record<string, string> };
}
export function overlayPatch(value: unknown): Partial<OverlaySettings> {
  const patch = object(value); exact(patch, ['visible', 'locked', 'clickThrough', 'fontSize', 'width']);
  for (const key of ['visible', 'locked', 'clickThrough']) if (key in patch && typeof patch[key] !== 'boolean') throw new Error('字幕窗口设置无效');
  for (const [key, min, max] of [['fontSize', 20, 48], ['width', 480, 1100]] as const) {
    if (key in patch && (typeof patch[key] !== 'number' || !Number.isInteger(patch[key]) || (patch[key] as number) < min || (patch[key] as number) > max)) throw new Error('字幕尺寸超出范围');
  }
  return patch as Partial<OverlaySettings>;
}
export function action(value: unknown): Action {
  const data = object(value);
  if (Buffer.byteLength(JSON.stringify(value)) > 32 * 1024) throw new Error('操作数据过大');
  switch (data.type) {
    case 'demo.start': exact(data, ['type', 'scenario']); text(data.scenario, 80); break;
    case 'session.start': exact(data, ['type', 'sourceId']); text(data.sourceId, 300); break;
    case 'session.stop': case 'core.restart': case 'sources.refresh': case 'window.show': exact(data, ['type']); break;
    case 'overlay.update': exact(data, ['type', 'patch']); overlayPatch(data.patch); break;
    case 'settings.save':
      exact(data, ['type', 'settings', 'apiKey', 'asrToken', 'clearApiKey', 'clearAsrToken']);
      data.settings = settings(data.settings);
      for (const key of ['apiKey', 'asrToken']) if (key in data) {
        const secret = text(data[key], 4096, true);
        if (/[\r\n\x00]/.test(secret)) throw new Error('密钥格式无效');
      }
      for (const key of ['clearApiKey', 'clearAsrToken']) if (key in data && typeof data[key] !== 'boolean') throw new Error('密钥操作无效');
      break;
    default: throw new Error('不支持的操作');
  }
  return data as unknown as Action;
}
