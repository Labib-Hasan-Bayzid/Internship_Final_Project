import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawn, execFileSync } from 'node:child_process';
import { performance } from 'node:perf_hooks';
import net from 'node:net';

const WORK = '/work';

function hashFile(file) {
  try { return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex'); } catch { return ''; }
}

function walk(dir, base = dir, out = {}) {
  if (!fs.existsSync(dir)) return out;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full, base, out);
    else if (entry.isFile()) out[path.relative(base, full)] = hashFile(full);
  }
  return out;
}

function decodeIPv4(hex) {
  if (!/^[0-9a-fA-F]{8}$/.test(hex)) return hex;
  const bytes = Buffer.from(hex, 'hex');
  return `${bytes[3]}.${bytes[2]}.${bytes[1]}.${bytes[0]}`;
}

function decodeIPv6(hex) {
  if (!/^[0-9a-fA-F]{32}$/.test(hex)) return hex;
  const raw = Buffer.from(hex, 'hex');
  const reordered = Buffer.concat([raw.subarray(0,4).reverse(), raw.subarray(4,8).reverse(), raw.subarray(8,12).reverse(), raw.subarray(12,16).reverse()]);
  const groups = [];
  for (let i = 0; i < 16; i += 2) groups.push(reordered.readUInt16BE(i).toString(16));
  const addr = groups.join(':').replace(/(^|:)0(:0)+:0(:|$)/, '::');
  return addr;
}

function snapshotNetwork() {
  const endpoints = new Set();
  for (const [filename, ipv6] of [['/proc/net/tcp', false], ['/proc/net/tcp6', true]]) {
    try {
      const lines = fs.readFileSync(filename, 'utf8').trim().split('\n').slice(1);
      for (const line of lines) {
        const cols = line.trim().split(/\s+/);
        if (!cols[2] || !cols[3] || cols[3] === '0A') continue; // ignore LISTEN sockets
        const [hexIp, hexPort] = cols[2].split(':');
        const port = Number.parseInt(hexPort, 16);
        if (!Number.isFinite(port)) continue;
        const ip = ipv6 ? decodeIPv6(hexIp) : decodeIPv4(hexIp);
        if (net.isIP(ip)) endpoints.add(`${ip}:${port}`);
      }
    } catch {}
  }
  return endpoints;
}

function processSnapshot() {
  const out = new Map();
  try {
    const rows = execFileSync('ps', ['-eo', 'pid,ppid,args'], { encoding: 'utf8' }).split('\n').slice(1);
    for (const row of rows) {
      const match = row.trim().match(/^(\d+)\s+(\d+)\s+(.*)$/);
      if (match) out.set(Number(match[1]), { ppid: Number(match[2]), cmd: match[3].slice(0, 500) });
    }
  } catch {}
  return out;
}

function descendants(snapshot, rootPid) {
  const result = new Set([rootPid]);
  let changed = true;
  while (changed) {
    changed = false;
    for (const [pid, item] of snapshot.entries()) {
      if (!result.has(pid) && result.has(item.ppid)) { result.add(pid); changed = true; }
    }
  }
  return result;
}

async function run(command, args, cwd, timeoutMs = 300000) {
  const site = path.join(cwd, 'node_modules');
  const beforeFiles = walk(site);
  const beforeNetwork = snapshotNetwork();
  const start = performance.now();
  const child = spawn(command, args, { cwd, env: process.env, stdio: ['ignore', 'pipe', 'pipe'], detached: true });
  const chunks = [];
  const observedProcessCommands = new Set();
  const observedNetwork = new Set(beforeNetwork);
  let lastSnapshot = processSnapshot();
  let timedOut = false;
  const monitor = setInterval(() => {
    lastSnapshot = processSnapshot();
    for (const pid of descendants(lastSnapshot, child.pid)) {
      const cmd = lastSnapshot.get(pid)?.cmd;
      if (cmd && pid !== child.pid) observedProcessCommands.add(cmd);
    }
    for (const endpoint of snapshotNetwork()) observedNetwork.add(endpoint);
  }, 80);

  child.stdout.on('data', b => chunks.push(b));
  child.stderr.on('data', b => chunks.push(b));
  const timer = setTimeout(() => {
    timedOut = true;
    try { process.kill(-child.pid, 'SIGKILL'); } catch { try { child.kill('SIGKILL'); } catch {} }
  }, timeoutMs);

  const code = await new Promise(resolve => child.on('close', c => resolve(c ?? 1)));
  clearTimeout(timer);
  clearInterval(monitor);
  lastSnapshot = processSnapshot();
  for (const pid of descendants(lastSnapshot, child.pid)) {
    const cmd = lastSnapshot.get(pid)?.cmd;
    if (cmd && pid !== child.pid) observedProcessCommands.add(cmd);
  }
  for (const endpoint of snapshotNetwork()) observedNetwork.add(endpoint);

  const afterFiles = walk(site);
  const changedKeys = [...new Set([...Object.keys(afterFiles), ...Object.keys(beforeFiles)])].filter(k => beforeFiles[k] !== afterFiles[k]);
  return {
    exit_code: code,
    timed_out: timedOut,
    duration_ms: Math.round(performance.now() - start),
    files_changed: changedKeys.slice(0, 500),
    files_added: Object.keys(afterFiles).filter(k => !(k in beforeFiles)).slice(0, 500),
    files_removed: Object.keys(beforeFiles).filter(k => !(k in afterFiles)).slice(0, 500),
    files_modified: Object.keys(afterFiles).filter(k => k in beforeFiles && beforeFiles[k] !== afterFiles[k]).slice(0, 500),
    process_commands: [...observedProcessCommands].slice(0, 100),
    network_endpoints: [...observedNetwork].filter(x => !beforeNetwork.has(x)).slice(0, 200),
    stdout_tail: Buffer.concat(chunks).toString('utf8').slice(-6000),
  };
}

function freshDir(name) {
  const target = path.join(WORK, name);
  fs.rmSync(target, { recursive: true, force: true });
  fs.mkdirSync(target, { recursive: true });
  return target;
}

async function registryMetadata(packageName, version) {
  try {
    const response = await fetch(`https://registry.npmjs.org/${encodeURIComponent(packageName)}/${encodeURIComponent(version)}`, { headers: { 'user-agent': 'dependency-change-verification/10.0' } });
    if (!response.ok) return { lookup_error: `HTTP_${response.status}` };
    const data = await response.json();
    return { name: data.name, version: data.version, deprecated: data.deprecated || null, license: data.license || null };
  } catch (error) {
    return { lookup_error: error?.name || 'Error' };
  }
}

async function dependencyVersions(cwd) {
  try {
    const result = await new Promise((resolve) => {
      const child = spawn('npm', ['ls', '--json', '--all', '--depth=20'], { cwd, env: process.env, stdio: ['ignore', 'pipe', 'ignore'] });
      const chunks = [];
      child.stdout.on('data', b => chunks.push(b));
      child.on('close', () => {
        try { resolve(JSON.parse(Buffer.concat(chunks).toString('utf8')).dependencies || {}); } catch { resolve({}); }
      });
    });
    const flatten = (node, prefix = '', out = {}) => {
      for (const [name, info] of Object.entries(node || {})) {
        if (info?.version) out[`${prefix}${name}`] = info.version;
        flatten(info?.dependencies, `${prefix}${name}>`, out);
      }
      return out;
    };
    return flatten(result);
  } catch { return {}; }
}

async function experiment(packageName, version, smokeImport) {
  const work = freshDir(`experiment-${version.replaceAll('/', '_')}`);
  fs.writeFileSync(path.join(work, 'package.json'), JSON.stringify({ private: true, type: 'module' }));
  const install = await run('npm', ['install', `${packageName}@${version}`, '--no-audit', '--no-fund'], work);
  install.phase = 'install';
  install.version = version;
  install.registry = await registryMetadata(packageName, version);
  install.dependency_versions = install.exit_code === 0 ? await dependencyVersions(work) : {};
  if (install.exit_code === 0 && smokeImport) {
    const smoke = await run('node', ['-e', `import(${JSON.stringify(smokeImport)})`], work, 60000);
    smoke.phase = 'smoke_import';
    smoke.import = smokeImport;
    install.smoke_test = smoke;
  }
  return install;
}

const packageName = process.env.PACKAGE_NAME;
const oldVersion = process.env.OLD_VERSION;
const newVersion = process.env.NEW_VERSION;
const smokeImport = (process.env.SMOKE_IMPORT || packageName || '').trim();
const oldResult = await experiment(packageName, oldVersion, smokeImport);
const newResult = await experiment(packageName, newVersion, smokeImport);
console.log('VERIFICATION_RESULT:' + JSON.stringify({
  package_name: packageName,
  ecosystem: 'node',
  old_version: oldVersion,
  new_version: newVersion,
  old: oldResult,
  new: newResult,
  verification_model: 'install + registry metadata + dependency tree + runtime import smoke test + live process/network/filesystem observation'
}));
