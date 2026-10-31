export interface Cue {
  cue_id: number; segment_id: number; text: string; kind: 'subtitle' | 'correction';
  locked: boolean; shown_at_ms: number; expires_at_ms: number; version: number;
  source_incomplete: boolean; source_diagnostic: string | null; corrects_cue_id: number | null;
}
export interface HistoryEntry {
  segment_id: number; source: string; translation: string | null; quality: string;
  source_incomplete: boolean; source_diagnostic: string | null; corrections: string[];
}
export interface Snapshot {
  type: 'snapshot'; protocol: 'host-core.v1'; seq: number; version: number;
  session_id: string | null; state: 'idle' | 'running' | 'stopping'; mode: 'idle' | 'demo' | 'live';
  current: Cue | null; previous: Cue | null; history: HistoryEntry[];
  source: { kind: string; label: string; capturing: boolean; asr_connected: boolean;
    asr_backend: string | null; speech_active: boolean; frames_dropped: number;
    gap_ms: number; asr_overloaded_ms: number; error: string | null };
  activity: { active_segments: number; in_flight: number; pending: number; queued_cues: number; translating: boolean };
  stats: Record<string, number>; notices: { kind: string; at_ms: number }[];
}
export interface Scenario { name: string; title: string; description: string }
export interface Source {
  id: string; kind: 'application' | 'output_device'; name: string;
  root_pid?: number; exe?: string; active?: boolean; is_default?: boolean;
}
export interface Settings {
  translation: { backend: 'mock' | 'chat'; endpoint: string; model: string; mode: 'plain' | 'structured' };
  asr: { backend: 'scripted' | 'external'; url: string };
  glossary: Record<string, string>;
}
export interface PublicSettings extends Settings { hasApiKey: boolean; hasAsrToken: boolean; canStoreSecrets: boolean }
export interface OverlaySettings { visible: boolean; locked: boolean; clickThrough: boolean; fontSize: number; width: number }
export interface AppState {
  revision: number;
  connection: 'starting' | 'ready' | 'error' | 'closed'; error: string | null;
  snapshot: Snapshot | null; scenarios: Scenario[]; sources: Source[]; sourceError: string | null;
  settings: PublicSettings; overlay: OverlaySettings;
  http: { completed: number; failed: number; lastMs: number | null };
}
export type Action =
  | { type: 'demo.start'; scenario: string }
  | { type: 'session.start'; sourceId: string }
  | { type: 'session.stop' | 'core.restart' | 'sources.refresh' | 'window.show' }
  | { type: 'overlay.update'; patch: Partial<OverlaySettings> }
  | { type: 'settings.save'; settings: Settings; apiKey?: string; asrToken?: string; clearApiKey?: boolean; clearAsrToken?: boolean };
export type Reply = { ok: true } | { ok: false; error: string };
export interface DesktopApi {
  getState(): Promise<AppState>;
  command(action: Action): Promise<Reply>;
  onState(listener: (state: AppState) => void): () => void;
}
export interface TranslationRequest {
  type: 'translate.request'; request_id: string; session_id: string;
  segment_id: number; source_revision: number; final: boolean; attempt: number;
  messages: { role: string; content: string }[];
}
