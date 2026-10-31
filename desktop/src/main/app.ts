import { app, BrowserWindow, ipcMain, safeStorage, screen, session } from 'electron';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { Controller } from './controller';
import { SettingsStore } from './settings';
import type { Reply } from '../shared/types';

export async function createApplication(options: { root?: string; show?: boolean; settingsPath?: string } = {}) {
  const root = options.root ?? (app.isPackaged ? process.resourcesPath : join(__dirname, '../../..'));
  const renderer = join(__dirname, '../renderer/index.html');
  const preload = join(__dirname, '../preload/index.js');
  const encryptionAvailable = await safeStorage.isAsyncEncryptionAvailable();
  const store = new SettingsStore(options.settingsPath ?? join(app.getPath('userData'), 'settings.json'), {
    isEncryptionAvailable: () => encryptionAvailable,
    encryptString: value => safeStorage.encryptStringAsync(value),
    decryptString: async value => (await safeStorage.decryptStringAsync(value)).result,
  });
  const controller = new Controller(root, store);
  const workArea = screen.getPrimaryDisplay().workArea;
  const show = options.show !== false;
  session.defaultSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  session.defaultSession.setPermissionCheckHandler(() => false);
  const make = (view: 'main' | 'overlay'): BrowserWindow => {
    const overlay = view === 'overlay';
    const width = overlay ? Math.min(store.overlay.width, workArea.width - 32) : Math.min(1180, workArea.width);
    const win = new BrowserWindow({
      width, height: overlay ? 290 : Math.min(900, workArea.height), minWidth: overlay ? 400 : 960, minHeight: overlay ? 240 : 700,
      ...(overlay ? { x: Math.round(workArea.x + (workArea.width - width) / 2), y: workArea.y + workArea.height - 320, frame: false, transparent: true, resizable: false, skipTaskbar: true, alwaysOnTop: true, hasShadow: false } : { title: 'Live Translator · 直播字幕', backgroundColor: '#f3f2ed' }),
      show: false,
      webPreferences: { preload, sandbox: true, contextIsolation: true, nodeIntegration: false, webSecurity: true, webviewTag: false, spellcheck: false, backgroundThrottling: false },
    });
    win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    win.webContents.on('will-navigate', event => event.preventDefault());
    win.webContents.session.on('will-download', event => event.preventDefault());
    win.once('ready-to-show', () => { if (show && (!overlay || store.overlay.visible)) win.show(); });
    return win;
  };
  const main = make('main'); const overlay = make('overlay');
  const expected = new Map([[main.webContents.id, 'main'], [overlay.webContents.id, 'overlay']] as const);
  const authorize = (event: Electron.IpcMainInvokeEvent): 'main' | 'overlay' => {
    const view = expected.get(event.sender.id);
    if (!view || !event.senderFrame || event.senderFrame !== event.sender.mainFrame || event.senderFrame.url !== `${pathToFileURL(renderer).href}?view=${view}`) throw new Error('IPC 来源无效');
    return view;
  };
  ipcMain.handle('desktop:state', event => { authorize(event); return controller.state; });
  ipcMain.handle('desktop:command', async (event, input: unknown): Promise<Reply> => {
    try { const view = authorize(event); await controller.dispatch(input, view); return { ok: true }; }
    catch (error) { return { ok: false, error: error instanceof Error ? error.message : '操作未完成' }; }
  });
  controller.on('state', state => {
    for (const window of [main, overlay]) if (!window.isDestroyed()) window.webContents.send('desktop:state', state);
  });
  const applyOverlay = () => {
    if (overlay.isDestroyed()) return;
    const prefs = controller.state.overlay;
    overlay.setMovable(!prefs.locked); overlay.setIgnoreMouseEvents(prefs.clickThrough, { forward: true });
    overlay.setAlwaysOnTop(true, 'screen-saver');
    const display = screen.getDisplayMatching(overlay.getBounds()).workArea;
    const width = Math.min(prefs.width, display.width - 24);
    const height = Math.max(290, Math.ceil(130 + 2.8 * prefs.fontSize + 2.8 * Math.max(18, prefs.fontSize * .57)));
    const [x, y] = overlay.getPosition();
    overlay.setBounds({ x: Math.max(display.x, Math.min(x, display.x + display.width - width)), y: Math.max(display.y, Math.min(y, display.y + display.height - height)), width, height });
    if (show && prefs.visible) overlay.showInactive(); else overlay.hide();
  };
  controller.on('overlay', applyOverlay);
  controller.on('showMain', () => { main.show(); main.focus(); });
  await Promise.all([main.loadFile(renderer, { query: { view: 'main' } }), overlay.loadFile(renderer, { query: { view: 'overlay' } })]);
  applyOverlay();
  let quitting = false;
  const close = async () => {
    if (quitting) return; quitting = true;
    await controller.close();
    ipcMain.removeHandler('desktop:state'); ipcMain.removeHandler('desktop:command');
    for (const win of [overlay, main]) if (!win.isDestroyed()) win.destroy();
  };
  main.on('close', event => { if (!quitting) { event.preventDefault(); void close().then(() => app.quit()); } });
  overlay.on('close', event => { if (!quitting) { event.preventDefault(); void controller.dispatch({ type: 'overlay.update', patch: { visible: false } }, 'main'); } });
  app.on('before-quit', event => { if (!quitting) { event.preventDefault(); void close().then(() => app.quit()); } });
  void controller.start();
  return { controller, main, overlay, close };
}
