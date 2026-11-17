import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const frontend = path.join(root, 'frontend');
const windows = process.platform === 'win32';
const pythonPath = windows ? ['Scripts', 'python.exe'] : ['bin', 'python'];
const candidates = [path.join(root, 'backend', '.venv', ...pythonPath), path.join(root, '.venv', ...pythonPath)];
const python = candidates.find(existsSync) ?? (windows ? 'python' : 'python3');

const backend = spawn(python, [
  '-m', 'uvicorn', 'main:app', '--reload', '--host', '127.0.0.1',
  '--port', '0', '--log-level', 'info', '--no-use-colors',
], {
  cwd: path.join(root, 'backend'),
  stdio: ['inherit', 'inherit', 'pipe'],
});

let vite;
let backendUrl;
let stopping = false;

function stop(code) {
  if (stopping) return;
  stopping = true;
  process.exitCode = code;
  backend.kill();
  vite?.kill();
}

function watch(child, name) {
  child.on('error', error => {
    console.error(`Failed to start ${name}: ${error.message}`);
    stop(1);
  });
  child.on('exit', code => stop(code ?? 1));
}

watch(backend, 'backend');
for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => stop(0));
}

createInterface({ input: backend.stderr }).on('line', line => {
  console.error(line);
  // Uvicorn reports the port after binding, so there is no gap between
  // choosing a port and reserving it.
  const address = line.match(/Uvicorn running on (http:\/\/127\.0\.0\.1:\d+)/)?.[1];
  if (address) backendUrl = address;
  if (!backendUrl || vite || stopping || !line.includes('Application startup complete.')) return;

  vite = spawn(process.execPath, [path.join(frontend, 'node_modules', 'vite', 'bin', 'vite.js')], {
    cwd: frontend,
    env: { ...process.env, STUDY_PLANNER_BACKEND_URL: backendUrl },
    stdio: 'inherit',
  });
  watch(vite, 'Vite');
});
