import { mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import type { Action, OverlaySettings, PublicSettings, Settings } from '../shared/types';
import { object, overlayPatch, settings } from './validation';

interface SecretStorage { isEncryptionAvailable(): boolean; encryptString(value: string): Buffer | Promise<Buffer>; decryptString(value: Buffer): string | Promise<string> }
export const DEFAULTS: Settings = {
  translation: { backend: 'mock', endpoint: '', model: '', mode: 'plain' },
  asr: { backend: 'scripted', url: 'ws://127.0.0.1:8765/v1/asr' }, glossary: {},
};
export class SettingsStore {
  config: Settings = structuredClone(DEFAULTS);
  overlay: OverlaySettings = { visible: true, locked: true, clickThrough: false, fontSize: 30, width: 800 };
  warning: string | null = null;
  private apiKeyEncrypted = '';
  private asrTokenEncrypted = '';
  constructor(private path: string, private crypto: SecretStorage) {
    try {
      const data = object(JSON.parse(readFileSync(path, 'utf8')));
      if (data.version !== 1) throw new Error('unsupported settings version');
      this.config = settings(data.settings);
      this.overlay = { ...this.overlay, ...overlayPatch(data.overlay), clickThrough: false };
      this.apiKeyEncrypted = typeof data.apiKeyEncrypted === 'string' ? data.apiKeyEncrypted : '';
      this.asrTokenEncrypted = typeof data.asrTokenEncrypted === 'string' ? data.asrTokenEncrypted : '';
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') this.warning = '设置文件无法读取，当前使用默认设置；可重新保存。';
    }
  }
  public(): PublicSettings {
    return { ...structuredClone(this.config), hasApiKey: !!this.apiKeyEncrypted, hasAsrToken: !!this.asrTokenEncrypted, canStoreSecrets: this.crypto.isEncryptionAvailable() };
  }
  async secret(which: 'apiKey' | 'asrToken'): Promise<string> {
    const value = which === 'apiKey' ? this.apiKeyEncrypted : this.asrTokenEncrypted;
    if (!value) return '';
    try { return await this.crypto.decryptString(Buffer.from(value, 'base64')); }
    catch { throw new Error('已保存的密钥无法解密，请重新输入并保存'); }
  }
  async save(input: Extract<Action, { type: 'settings.save' }>): Promise<void> {
    const config = settings(input.settings);
    const encrypt = async (value: string | undefined, current: string, clear: boolean | undefined): Promise<string> => {
      if (clear) return '';
      if (!value) return current;
      if (!this.crypto.isEncryptionAvailable()) throw new Error('系统密钥加密不可用，暂不能保存密钥');
      return (await this.crypto.encryptString(value)).toString('base64');
    };
    const apiKey = await encrypt(input.apiKey, this.apiKeyEncrypted, input.clearApiKey);
    const asrToken = await encrypt(input.asrToken, this.asrTokenEncrypted, input.clearAsrToken);
    this.persist(config, this.overlay, apiKey, asrToken);
    this.config = config; this.apiKeyEncrypted = apiKey; this.asrTokenEncrypted = asrToken; this.warning = null;
  }
  setOverlay(patch: Partial<OverlaySettings>): void {
    const next = { ...this.overlay, ...overlayPatch(patch) };
    this.persist(this.config, next, this.apiKeyEncrypted, this.asrTokenEncrypted);
    this.overlay = next;
  }
  private persist(settings: Settings, overlay: OverlaySettings, apiKeyEncrypted: string, asrTokenEncrypted: string): void {
    mkdirSync(dirname(this.path), { recursive: true });
    const temp = this.path + '.tmp';
    writeFileSync(temp, JSON.stringify({ version: 1, settings, overlay, apiKeyEncrypted, asrTokenEncrypted }), { mode: 0o600 });
    renameSync(temp, this.path);
  }
}
