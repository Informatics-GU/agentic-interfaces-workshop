import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const windows = process.platform === 'win32';
const pythonPath = windows ? 'Scripts/python.exe' : 'bin/python';
const python = ['backend/.venv', '.venv']
  .map((directory) => path.join(root, directory, pythonPath))
  .find(existsSync) ?? (windows ? 'python' : 'python3');
const children = [];
let stopping = false;

function stop(code) {
  if (stopping) return;
  stopping = true;
  process.exitCode = code;
  for (const child of children) child.kill('SIGTERM');
}

function start(command, args, directory) {
  const child = spawn(command, args, {
    cwd: path.join(root, directory),
    stdio: 'inherit',
  });
  children.push(child);
  child.on('error', (error) => {
    console.error(`Could not start ${command}: ${error.message}`);
    stop(1);
  });
  child.on('exit', (code, signal) => {
    if (!stopping) stop(code ?? (signal ? 1 : 0));
  });
}

process.on('SIGINT', () => stop(0));
process.on('SIGTERM', () => stop(0));

start(python, ['-m', 'uvicorn', 'main:app', '--reload', '--port', '8000'], 'backend');
// Launch Vite directly so shutdown reaches the server without an npm wrapper.
start(process.execPath, [path.join(root, 'frontend/node_modules/vite/bin/vite.js')], 'frontend');
