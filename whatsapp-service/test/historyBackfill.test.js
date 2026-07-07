const test = require('node:test');
const assert = require('node:assert/strict');

const whatsappClient = require('../src/whatsappClient');
const { buildHistoryDedupeKey, sortBackfillMessages } = whatsappClient;

test('buildHistoryDedupeKey keeps provider-id-less WhatsApp history distinct by chat, timestamp, and text', () => {
  const baseMessage = {
    timestamp: 1710000000,
    body: 'Hello history',
    from: '31612345678@c.us',
    to: '15550000000@c.us',
  };

  const sameKey = buildHistoryDedupeKey(baseMessage, '31612345678@c.us', 'inbound');
  const differentText = buildHistoryDedupeKey({ ...baseMessage, body: 'Different history' }, '31612345678@c.us', 'inbound');
  const differentChat = buildHistoryDedupeKey(baseMessage, '31600000000@c.us', 'inbound');

  assert.equal(sameKey, buildHistoryDedupeKey(baseMessage, '31612345678@c.us', 'inbound'));
  assert.notEqual(sameKey, differentText);
  assert.notEqual(sameKey, differentChat);
});

test('sortBackfillMessages orders equal timestamps by message id', () => {
  const ordered = [
    { timestamp: 1710000000, id: { _serialized: 'b-message' } },
    { timestamp: 1710000000, id: { _serialized: 'a-message' } },
    { timestamp: 1709999999, id: { _serialized: 'c-message' } },
  ].sort(sortBackfillMessages);

  assert.deepEqual(ordered.map((message) => message.id._serialized), ['c-message', 'a-message', 'b-message']);
});


test('backfillAllChats processes only CRM-eligible chats by default', async () => {
  const originalFetch = global.fetch;
  const originalEnv = {
    CRM_API_BASE_URL: process.env.CRM_API_BASE_URL,
    CRM_WEBHOOK_URL: process.env.CRM_WEBHOOK_URL,
    CRM_WEBHOOK_SECRET: process.env.CRM_WEBHOOK_SECRET,
  };
  const modulePath = require.resolve('../src/whatsappClient');
  const configPath = require.resolve('../src/config');

  try {
    process.env.CRM_API_BASE_URL = 'http://crm.test';
    process.env.CRM_WEBHOOK_URL = 'http://crm.test/webhooks/whatsapp';
    process.env.CRM_WEBHOOK_SECRET = 'test-webhook-secret';

    global.fetch = async (url, options = {}) => {
      if (String(url).includes('/backfill-identities')) {
        return {
          ok: true,
          status: 200,
          headers: { 'content-type': 'application/json' },
          json: async () => ({
            ok: true,
            total_tenants: 1,
            total_active_endpoints: 1,
            total_identity_records: 2,
            entries: [
              {
                tenant_id: 7,
                tenant_name: 'Tenant Eligible',
                booking_id: 'B-eligible',
                phone_numbers: ['31612345678'],
                chat_ids: ['31612345678@c.us'],
                external_phone_ids: [],
                external_chat_namespaces: [],
                external_account_ids: ['edi-crm-whatsapp'],
              },
            ],
          }),
          text: async () => '',
        };
      }

      return {
        ok: true,
        status: 200,
        headers: { 'content-type': 'application/json' },
        json: async () => ({ ok: true, echoed: options.method || 'GET' }),
        text: async () => '',
      };
    };

    delete require.cache[modulePath];
    delete require.cache[configPath];
    const reloaded = require('../src/whatsappClient');

    const result = await reloaded.backfillAllChats({
      clientOverride: {
        getChats: async () => [
          {
            id: { _serialized: '31612345678@c.us', user: '31612345678' },
            isGroup: false,
            syncHistory: async () => {},
            fetchMessages: async () => ([
              { timestamp: 1710000000, body: 'Historical inbound', fromMe: false, from: '31612345678@c.us', to: '15550000000@c.us', id: { _serialized: 'msg-backfill-inbound' } },
              { timestamp: 1710000001, body: 'Historical outbound', fromMe: true, from: '15550000000@c.us', to: '31612345678@c.us', id: { _serialized: 'msg-backfill-outbound' } },
            ]),
          },
          {
            id: { _serialized: '31699999999@c.us', user: '31699999999' },
            isGroup: false,
            syncHistory: async () => {},
            fetchMessages: async () => ([
              { timestamp: 1710000002, body: 'Unrelated historical chat', fromMe: false, from: '31699999999@c.us', to: '15550000000@c.us', id: { _serialized: 'msg-backfill-unrelated' } },
            ]),
          },
        ],
      },
      readyOverride: true,
      limit: 10,
      postSyncDelayMs: 1,
    });

    assert.equal(result.total_chats_in_whatsapp, 2);
    assert.equal(result.total_crm_eligible_chats, 1);
    assert.equal(result.total_synced_chats, 1);
    assert.equal(result.skipped_chats, 1);
    assert.equal(result.imported, 2);
    assert.equal(result.failed, 0);
    assert.equal(result.inbound, 1);
    assert.equal(result.outbound, 1);
    assert.equal(result.deduped, 0);
  } finally {
    global.fetch = originalFetch;
    if (originalEnv.CRM_API_BASE_URL === undefined) delete process.env.CRM_API_BASE_URL; else process.env.CRM_API_BASE_URL = originalEnv.CRM_API_BASE_URL;
    if (originalEnv.CRM_WEBHOOK_URL === undefined) delete process.env.CRM_WEBHOOK_URL; else process.env.CRM_WEBHOOK_URL = originalEnv.CRM_WEBHOOK_URL;
    if (originalEnv.CRM_WEBHOOK_SECRET === undefined) delete process.env.CRM_WEBHOOK_SECRET; else process.env.CRM_WEBHOOK_SECRET = originalEnv.CRM_WEBHOOK_SECRET;
    delete require.cache[modulePath];
    delete require.cache[configPath];
  }
});

test('backfillAllChats can be forced to sync every chat with all=true', async () => {
  const originalFetch = global.fetch;
  const originalEnv = {
    CRM_API_BASE_URL: process.env.CRM_API_BASE_URL,
    CRM_WEBHOOK_URL: process.env.CRM_WEBHOOK_URL,
    CRM_WEBHOOK_SECRET: process.env.CRM_WEBHOOK_SECRET,
  };
  const modulePath = require.resolve('../src/whatsappClient');
  const configPath = require.resolve('../src/config');

  try {
    process.env.CRM_API_BASE_URL = 'http://crm.test';
    process.env.CRM_WEBHOOK_URL = 'http://crm.test/webhooks/whatsapp';
    process.env.CRM_WEBHOOK_SECRET = 'test-webhook-secret';

    global.fetch = async (url, options = {}) => {
      if (String(url).includes('/backfill-identities')) {
        return {
          ok: true,
          status: 200,
          headers: { 'content-type': 'application/json' },
          json: async () => ({
            ok: true,
            total_tenants: 1,
            total_active_endpoints: 1,
            total_identity_records: 1,
            entries: [
              {
                tenant_id: 7,
                tenant_name: 'Tenant Eligible',
                booking_id: 'B-eligible',
                phone_numbers: ['31612345678'],
                chat_ids: ['31612345678@c.us'],
                external_phone_ids: [],
                external_chat_namespaces: [],
                external_account_ids: ['edi-crm-whatsapp'],
              },
            ],
          }),
          text: async () => '',
        };
      }

      return {
        ok: true,
        status: 200,
        headers: { 'content-type': 'application/json' },
        json: async () => ({ ok: true, echoed: options.method || 'GET' }),
        text: async () => '',
      };
    };

    delete require.cache[modulePath];
    delete require.cache[configPath];
    const reloaded = require('../src/whatsappClient');

    const result = await reloaded.backfillAllChats({
      all: true,
      clientOverride: {
        getChats: async () => [
          {
            id: { _serialized: '31612345678@c.us', user: '31612345678' },
            isGroup: false,
            syncHistory: async () => {},
            fetchMessages: async () => ([
              { timestamp: 1710000000, body: 'Historical inbound', fromMe: false, from: '31612345678@c.us', to: '15550000000@c.us', id: { _serialized: 'msg-backfill-inbound' } },
            ]),
          },
          {
            id: { _serialized: '31699999999@c.us', user: '31699999999' },
            isGroup: false,
            syncHistory: async () => {},
            fetchMessages: async () => ([
              { timestamp: 1710000002, body: 'Unrelated historical chat', fromMe: false, from: '31699999999@c.us', to: '15550000000@c.us', id: { _serialized: 'msg-backfill-unrelated' } },
            ]),
          },
        ],
      },
      readyOverride: true,
      limit: 10,
      postSyncDelayMs: 1,
    });

    assert.equal(result.scope, 'all');
    assert.equal(result.total_chats_in_whatsapp, 2);
    assert.equal(result.total_crm_eligible_chats, 1);
    assert.equal(result.total_synced_chats, 2);
    assert.equal(result.skipped_chats, 0);
    assert.equal(result.imported, 2);
    assert.equal(result.failed, 0);
    assert.equal(result.inbound, 2);
  } finally {
    global.fetch = originalFetch;
    if (originalEnv.CRM_API_BASE_URL === undefined) delete process.env.CRM_API_BASE_URL; else process.env.CRM_API_BASE_URL = originalEnv.CRM_API_BASE_URL;
    if (originalEnv.CRM_WEBHOOK_URL === undefined) delete process.env.CRM_WEBHOOK_URL; else process.env.CRM_WEBHOOK_URL = originalEnv.CRM_WEBHOOK_URL;
    if (originalEnv.CRM_WEBHOOK_SECRET === undefined) delete process.env.CRM_WEBHOOK_SECRET; else process.env.CRM_WEBHOOK_SECRET = originalEnv.CRM_WEBHOOK_SECRET;
    delete require.cache[modulePath];
    delete require.cache[configPath];
  }
});
