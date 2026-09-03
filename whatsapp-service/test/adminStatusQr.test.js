const test = require('node:test');
const assert = require('node:assert/strict');
const express = require('express');

const { createMessageRouter } = require('../src/routes/messages');

// A tiny WhatsApp QR-shaped string; qrcode encodes any string, so the exact contents don't matter.
const SAMPLE_QR = '2@abc123def456,someBase64Key/,anotherBase64Key=,1';
const API_KEY = 'test-admin-key';

// Header-only guard, mirroring the real requireApiKey.
function requireApiKey(req, res, next) {
  if (String(req.get('X-API-Key') || '') !== API_KEY) {
    return res.status(401).json({ ok: false, error: 'Unauthorized' });
  }
  return next();
}

// Query-or-header guard, mirroring the real requireApiKeyForAdminGet.
function requireApiKeyForAdminGet(req, res, next) {
  const provided = String(req.get('X-API-Key') || req.query?.key || '');
  if (provided !== API_KEY) {
    return res.status(401).json({ ok: false, error: 'Unauthorized' });
  }
  return next();
}

async function withServer(deps, run) {
  const app = express();
  app.use(express.json());
  app.use(createMessageRouter({
    requireApiKey,
    requireApiKeyForAdminGet,
    // Unused by these tests but required by the factory signature.
    sendTextMessage: async () => ({}),
    sendSystemMessage: async () => ({}),
    runHistoryBackfill: async () => ({}),
    runHistoryDebugSample: async () => ({}),
    debugChatModelBuild: async () => ({}),
    listChats: async () => ({ chats: [], total_count: 0 }),
    ...deps,
  }));

  const server = await new Promise((resolve) => {
    const s = app.listen(0, '127.0.0.1', () => resolve(s));
  });
  const { port } = server.address();
  const base = `http://127.0.0.1:${port}`;
  try {
    await run(base);
  } finally {
    await new Promise((resolve) => server.close(() => resolve()));
  }
}

test('/admin/status returns the connection status as JSON', async () => {
  const status = {
    ready: false,
    client_id: 'ssi-crm-whatsapp',
    last_ready_at: '2026-09-03T14:21:40.000Z',
    last_disconnect: { reason: 'LOGOUT', at: '2026-09-03T14:26:43.000Z' },
    last_auth_failure_at: null,
    has_qr: true,
    qr_age_ms: 1200,
  };
  await withServer({ getConnectionStatus: () => status }, async (base) => {
    const res = await fetch(`${base}/admin/status`, { headers: { 'X-API-Key': API_KEY } });
    assert.equal(res.status, 200);
    const body = await res.json();
    assert.equal(body.ok, true);
    assert.equal(body.ready, false);
    assert.equal(body.last_disconnect.reason, 'LOGOUT');
    assert.equal(body.client_id, 'ssi-crm-whatsapp');
  });
});

test('/admin/qr?format=png returns PNG bytes when not ready', async () => {
  await withServer({
    getConnectionStatus: () => ({ ready: false, client_id: 'ssi', last_disconnect: null }),
    getLatestQr: () => ({ qr: SAMPLE_QR, generated_at: '2026-09-03T14:26:45.000Z' }),
  }, async (base) => {
    const res = await fetch(`${base}/admin/qr?format=png`, { headers: { 'X-API-Key': API_KEY } });
    assert.equal(res.status, 200);
    assert.equal(res.headers.get('content-type'), 'image/png');
    const bytes = Buffer.from(await res.arrayBuffer());
    // PNG magic number: 89 50 4E 47 0D 0A 1A 0A
    assert.deepEqual([...bytes.subarray(0, 8)], [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  });
});

test('/admin/qr defaults to a self-refreshing HTML page embedding the QR', async () => {
  await withServer({
    getConnectionStatus: () => ({ ready: false, client_id: 'ssi', last_disconnect: null }),
    getLatestQr: () => ({ qr: SAMPLE_QR, generated_at: '2026-09-03T14:26:45.000Z' }),
  }, async (base) => {
    const res = await fetch(`${base}/admin/qr`, { headers: { 'X-API-Key': API_KEY } });
    assert.equal(res.status, 200);
    assert.match(res.headers.get('content-type'), /text\/html/);
    const html = await res.text();
    assert.match(html, /http-equiv="refresh"/);
    assert.match(html, /data:image\/png;base64,/);
  });
});

test('/admin/qr reports already linked when ready (no QR)', async () => {
  await withServer({
    getConnectionStatus: () => ({ ready: true, client_id: 'ssi', last_disconnect: null }),
    getLatestQr: () => ({ qr: null, generated_at: null }),
  }, async (base) => {
    const res = await fetch(`${base}/admin/qr`, { headers: { 'X-API-Key': API_KEY } });
    assert.equal(res.status, 200);
    const body = await res.json();
    assert.equal(body.ok, true);
    assert.equal(body.ready, true);
    assert.equal(body.message, 'already linked');
  });
});

test('/admin/qr returns 503 when not ready and no QR is available yet', async () => {
  await withServer({
    getConnectionStatus: () => ({ ready: false, client_id: 'ssi', last_disconnect: null }),
    getLatestQr: () => ({ qr: null, generated_at: null }),
  }, async (base) => {
    const res = await fetch(`${base}/admin/qr`, { headers: { 'X-API-Key': API_KEY } });
    assert.equal(res.status, 503);
    const body = await res.json();
    assert.equal(body.ok, false);
  });
});

test('/admin/qr accepts the API key via ?key= query param', async () => {
  await withServer({
    getConnectionStatus: () => ({ ready: false, client_id: 'ssi', last_disconnect: null }),
    getLatestQr: () => ({ qr: SAMPLE_QR, generated_at: null }),
  }, async (base) => {
    const res = await fetch(`${base}/admin/qr?format=json&key=${API_KEY}`);
    assert.equal(res.status, 200);
    const body = await res.json();
    assert.equal(body.ok, true);
    assert.equal(body.qr, SAMPLE_QR);
  });
});

test('/admin/qr rejects a missing/wrong key', async () => {
  await withServer({
    getConnectionStatus: () => ({ ready: false, client_id: 'ssi', last_disconnect: null }),
    getLatestQr: () => ({ qr: SAMPLE_QR, generated_at: null }),
  }, async (base) => {
    const noKey = await fetch(`${base}/admin/qr?format=json`);
    assert.equal(noKey.status, 401);
    const wrongKey = await fetch(`${base}/admin/qr?format=json&key=nope`);
    assert.equal(wrongKey.status, 401);
  });
});
