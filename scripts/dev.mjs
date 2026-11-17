import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const windows = process.platform === 'win32';
const pythonPath = windows ? ['Scripts', 'python.exe'] : ['bin', 'python'];
const candidates = [path.join(root, 'backend', '.venv', ...pythonPath), path.join(root, '.venv', ...pythonPath)];
const python = candidates.find(existsSync) ?? (windows ? 'python' : 'python3');

const backend = spawn(python, ['-m', 'uvicorn', 'main:app', '--reload', '--port', '1537'], {
  cwd: path.join(root, 'backend'),
  stdio: 'inherit',
});

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => backend.kill(signal));
}

backend.on('error', error => {
  console.error(`Failed to start backend: ${error.message}`);
  process.exitCode = 1;
});

backend.on('exit', code => {
  process.exitCode = code ?? 0;
});
