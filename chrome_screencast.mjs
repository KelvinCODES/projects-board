#!/usr/bin/env node
// Record one Slack conversation through Chrome's DevTools screencast, no screen capture.
// Usage: chrome_screencast.mjs <url> <seconds> <out.mp4> [--profile DIR] [--port N] [--position X,Y] [--warmup S]
// Chrome runs from its own profile dir (one-time Slack login) and can sit behind other
// windows: frames are pulled with Page.captureScreenshot on a timer (paint-driven screencast
// starves when the tab is occluded). Needs ffmpeg on PATH.

import { spawn, execFileSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, rmSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const VIEWPORT = { width: 1100, height: 1000 };

function parseArgs(argv) {
  const [url, seconds, out] = argv;
  if (!url || !seconds || !out) {
    console.error('usage: chrome_screencast.mjs <url> <seconds> <out.mp4> [--profile DIR] [--port N]');
    process.exit(2);
  }
  const flag = (name, fallback) => {
    const i = argv.indexOf(name);
    return i > -1 ? argv[i + 1] : fallback;
  };
  return {
    url,
    seconds: Number(seconds),
    out,
    profile: flag('--profile', join(process.env.HOME, '.claude/projects-board/chrome-profile')),
    port: Number(flag('--port', '9333')),
    position: flag('--position', '2000,2000'),
    warmup: Number(flag('--warmup', '3')),
    fps: Number(flag('--fps', '8')),
  };
}

function launchChrome({ url, profile, port, position }) {
  mkdirSync(profile, { recursive: true });
  const args = [
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profile}`,
    `--window-size=${VIEWPORT.width},${VIEWPORT.height}`,
    `--window-position=${position}`,
    '--disable-backgrounding-occluded-windows',
    '--disable-renderer-backgrounding',
    '--no-first-run',
    '--no-default-browser-check',
    url,
  ];
  return spawn(CHROME, args, { stdio: 'ignore', detached: true });
}

async function findPage(port, url, attempts = 40) {
  for (let i = 0; i < attempts; i++) {
    try {
      const targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
      const page = targets.find((t) => t.type === 'page' && t.url.startsWith(url.split('?')[0].slice(0, 30)));
      if (page) return page;
    } catch {}
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error('Slack page not found on the debugging port');
}

class Cdp {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    this.listeners = new Map();
    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && this.pending.has(msg.id)) {
        this.pending.get(msg.id)(msg.result);
        this.pending.delete(msg.id);
      } else if (msg.method && this.listeners.has(msg.method)) {
        this.listeners.get(msg.method)(msg.params);
      }
    });
  }
  send(method, params = {}) {
    const id = ++this.id;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve) => this.pending.set(id, resolve));
  }
  on(method, fn) {
    this.listeners.set(method, fn);
  }
}

function connect(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    ws.addEventListener('open', () => resolve(new Cdp(ws)));
    ws.addEventListener('error', reject);
  });
}

async function captureFrames(cdp, seconds, fps, dir) {
  // Poll captureScreenshot on a timer instead of Page.startScreencast: a backgrounded or
  // occluded tab barely fires paint events, so the screencast starves, but captureScreenshot
  // forces a render every call and works with Chrome behind other windows.
  await cdp.send('Page.enable');
  const frames = [];
  const interval = 1 / fps;
  const start = Date.now() / 1000;
  let n = 0;
  while (Date.now() / 1000 - start < seconds) {
    const tickStart = Date.now();
    const shot = await cdp.send('Page.captureScreenshot', { format: 'png', optimizeForSpeed: true });
    if (shot && shot.data) {
      const file = join(dir, `f${String(n++).padStart(5, '0')}.png`);
      writeFileSync(file, Buffer.from(shot.data, 'base64'));
      frames.push(file);
    }
    const elapsed = (Date.now() - tickStart) / 1000;
    if (elapsed < interval) await new Promise((r) => setTimeout(r, (interval - elapsed) * 1000));
  }
  return { frames, fps };
}

function encode({ frames, fps }, out) {
  if (frames.length < 2) throw new Error(`only ${frames.length} frame(s) captured; is the page rendering?`);
  const list = frames.map((f) => `file '${f}'\nduration ${(1 / fps).toFixed(4)}`).join('\n');
  const listFile = join(frames[0], '..', 'frames.txt');
  writeFileSync(listFile, list + `\nfile '${frames[frames.length - 1]}'\n`);
  execFileSync('ffmpeg', ['-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', listFile,
    '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p', '-r', '30', '-c:v', 'h264', '-crf', '23', out]);
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  const chrome = launchChrome(opts);
  const page = await findPage(opts.port, opts.url);
  const cdp = await connect(page.webSocketDebuggerUrl);
  const dir = mkdtempSync(join(tmpdir(), 'screencast-'));
  if (opts.warmup) {
    console.log(`warming up ${opts.warmup}s so the page finishes loading …`);
    await new Promise((r) => setTimeout(r, opts.warmup * 1000));
  }
  console.log(`screencasting ${opts.seconds}s of ${page.url} …`);
  const result = await captureFrames(cdp, opts.seconds, opts.fps, dir);
  encode(result, opts.out);
  console.log(`captured ${result.frames.length} frames`);
  rmSync(dir, { recursive: true, force: true });
  cdp.ws.close();
  chrome.kill();
  console.log(`wrote ${opts.out}`);
}

main().catch((e) => {
  console.error(e.message);
  process.exit(1);
});
