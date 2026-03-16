import webpush from 'web-push';
import { writeFileSync, readFileSync, existsSync, mkdirSync } from 'fs';
import { dirname } from 'path';
import { VAPID_KEYS_FILE, PUSH_SUBSCRIPTIONS_FILE } from '../lib/config.mjs';

let ready = false;
let cachedKeys = null;

function ensureDir(filepath) {
  const dir = dirname(filepath);
  if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
}

function loadOrGenerateKeys() {
  if (cachedKeys) return cachedKeys;
  if (existsSync(VAPID_KEYS_FILE)) {
    try {
      cachedKeys = JSON.parse(readFileSync(VAPID_KEYS_FILE, 'utf8'));
      return cachedKeys;
    } catch {}
  }
  cachedKeys = webpush.generateVAPIDKeys();
  ensureDir(VAPID_KEYS_FILE);
  writeFileSync(VAPID_KEYS_FILE, JSON.stringify(cachedKeys, null, 2));
  console.log('[push] Generated new VAPID keys');
  return cachedKeys;
}

function init() {
  if (ready) return;
  const keys = loadOrGenerateKeys();
  webpush.setVapidDetails('mailto:remotelab@localhost', keys.publicKey, keys.privateKey);
  ready = true;
}

export function getPublicKey() {
  init();
  return cachedKeys.publicKey;
}

function loadSubs() {
  if (!existsSync(PUSH_SUBSCRIPTIONS_FILE)) return [];
  try { return JSON.parse(readFileSync(PUSH_SUBSCRIPTIONS_FILE, 'utf8')); } catch { return []; }
}

function saveSubs(subs) {
  ensureDir(PUSH_SUBSCRIPTIONS_FILE);
  writeFileSync(PUSH_SUBSCRIPTIONS_FILE, JSON.stringify(subs, null, 2));
}

export function addSubscription(sub) {
  init();
  const subs = loadSubs();
  const idx = subs.findIndex(s => s.endpoint === sub.endpoint);
  if (idx >= 0) subs[idx] = sub; else subs.push(sub);
  saveSubs(subs);
  console.log(`[push] Subscription saved (total: ${subs.length})`);
}

export async function sendCompletionPush(session) {
  init();
  const subs = loadSubs();
  if (subs.length === 0) return;

  const folder = (session?.folder || '').split('/').pop() || 'Session';
  const name = session?.name || folder;
  const payload = JSON.stringify({ title: 'RemoteLab', body: `${name} — task completed` });

  const stale = new Set();
  await Promise.allSettled(subs.map(async (sub, i) => {
    try {
      await webpush.sendNotification(sub, payload);
    } catch (err) {
      if (err.statusCode === 410 || err.statusCode === 404) stale.add(i);
      else console.warn(`[push] Send failed: ${err.message}`);
    }
  }));

  if (stale.size > 0) {
    saveSubs(subs.filter((_, i) => !stale.has(i)));
    console.log(`[push] Removed ${stale.size} stale subscription(s)`);
  }
}
