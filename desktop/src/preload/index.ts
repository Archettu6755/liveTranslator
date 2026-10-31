import { contextBridge, ipcRenderer } from 'electron';
import type { AppState, DesktopApi } from '../shared/types';

const api: DesktopApi = {
  getState: () => ipcRenderer.invoke('desktop:state'),
  command: action => ipcRenderer.invoke('desktop:command', action),
  onState: listener => {
    const handler = (_event: Electron.IpcRendererEvent, state: AppState) => listener(state);
    ipcRenderer.on('desktop:state', handler);
    return () => ipcRenderer.removeListener('desktop:state', handler);
  },
};
contextBridge.exposeInMainWorld('liveTranslator', api);
