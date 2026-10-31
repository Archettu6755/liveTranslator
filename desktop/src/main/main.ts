import { app } from 'electron';
import { createApplication } from './app';
import { mkdirSync } from 'node:fs';
import { resolve, join } from 'node:path';

app.setName('Live Translator');
const selfTest = process.argv.indexOf('--self-test');
let testOutput: string | undefined;
if (selfTest >= 0) {
  testOutput = resolve(process.argv[selfTest + 1] ?? join(app.getPath('temp'), 'live-translator-self-test'));
  mkdirSync(join(testOutput, 'user-data'), { recursive: true });
  app.setPath('userData', join(testOutput, 'user-data'));
  app.commandLine.appendSwitch('disable-gpu');
}
app.whenReady().then(async () => {
  if (testOutput) {
    const { runPackageSmoke } = await import('./package-smoke.js');
    await runPackageSmoke(testOutput);
  } else await createApplication();
}).catch(() => {
  console.error('Live Translator could not start. Extract the complete client package and try again.');
  app.exit(1);
});
app.on('window-all-closed', () => app.quit());
