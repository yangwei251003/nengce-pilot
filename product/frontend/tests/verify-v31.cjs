const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawnSync } = require('node:child_process');
const dir = path.resolve(__dirname, '..');
const out = path.resolve(dir, '../../qa/v31/frontend');
fs.mkdirSync(out, { recursive: true });
const commands = [
  ['typecheck', ['node_modules/typescript/bin/tsc', '-b']],
  ['build', ['node_modules/vite/bin/vite.js', 'build']],
  ['dom', ['tests/ui.test.cjs']],
];
const results = [];
for (const [name, args] of commands) {
  const start = performance.now();
  const result = spawnSync(process.execPath, args, { cwd: dir, encoding: 'utf8', maxBuffer: 1024 * 1024 * 5 });
  fs.writeFileSync(path.join(out, `${name}.log`), (result.stdout || '') + (result.stderr || ''));
  results.push({ name, command: [process.execPath, ...args], status: result.status === 0 ? 'PASS' : 'FAIL', exit_code: result.status, elapsed_seconds: (performance.now() - start) / 1000 });
}
const files = ['src/App.tsx', 'src/components/AssistantPanel.tsx', 'src/components/ModelSettings.tsx', 'src/types.ts', 'src/styles.css', 'index.html', 'dist/index.html', 'package-lock.json', 'tests/ui.test.cjs', 'tests/browser-v31.cjs'];
const hashes = Object.fromEntries(files.map(file => [file, crypto.createHash('sha256').update(fs.readFileSync(path.join(dir, file))).digest('hex')]));
const report = { completed_at: new Date().toISOString(), status: results.every(result => result.status === 'PASS') ? 'PASS' : 'FAIL', runtime: { node: process.version, platform: process.platform, architecture: process.arch }, results, hashes, limitation: 'DOM/mock checks do not replace actual API, browser, provider connection or layout tests.' };
fs.writeFileSync(path.join(out, 'verification.json'), JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
if (report.status !== 'PASS') process.exitCode = 1;
