const test = require('node:test');
const assert = require('node:assert/strict');

function loadWhatsappClientWithWebhookConfigured(env = {}) {
  const modulePath = require.resolve('../src/whatsappClient');
  const configPath = require.resolve('../src/config');
  delete require.cache[modulePath];
  delete require.cache[configPath];

  process.env.CRM_WEBHOOK_URL = 'http://crm.test/webhooks/whatsapp';
  delete process.env.CRM_WEBHOOK_SECRET;
  delete process.env.CRM_WEBHOOK_ROUTE_TOKEN;
  for (const [key, value] of Object.entries(env)) {
    process.env[key] = value;
  }

  return require('../src/whatsappClient');
}

function captureForward() {
  const state = { body: null };
  global.fetch = async (_url, options) => {
    state.body = JSON.parse(options.body);
    return { ok: true, status: 200, json: async () => ({ ok: true }), text: async () => '' };
  };
  return state;
}

function mediaMessage(overrides = {}) {
  return {
    fromMe: false,
    isStatus: false,
    from: '31612345678@c.us',
    timestamp: 1000,
    type: 'image',
    hasMedia: true,
    id: { _serialized: 'wamid.media-1' },
    downloadMedia: async () => ({ data: 'aGVsbG8=', mimetype: 'image/png', filename: 'photo.png' }),
    ...overrides,
  };
}

test('an inbound media message forwards the downloaded bytes to the CRM', async () => {
  const originalFetch = global.fetch;
  try {
    const { forwardInboundMessage } = loadWhatsappClientWithWebhookConfigured();
    const captured = captureForward();

    const result = await forwardInboundMessage(mediaMessage());

    assert.equal(result, true);
    assert.equal(captured.body.attachments.length, 1);
    assert.deepEqual(captured.body.attachments[0], {
      filename: 'photo.png',
      mime_type: 'image/png',
      size_bytes: 5,
      data_base64: 'aGVsbG8=',
    });
  } finally {
    global.fetch = originalFetch;
  }
});

test('a caption-less media message of a known type keeps its existing type placeholder', async () => {
  const originalFetch = global.fetch;
  try {
    const { forwardInboundMessage } = loadWhatsappClientWithWebhookConfigured();
    const captured = captureForward();

    await forwardInboundMessage(mediaMessage());

    // MEDIA_TYPE_LABELS already covers 'image', so the established placeholder wins.
    assert.equal(captured.body.message, '[Image]');
    assert.equal(captured.body.attachments.length, 1);
  } finally {
    global.fetch = originalFetch;
  }
});

test('a caption-less media message of an unknown type falls back to the filename', async () => {
  const originalFetch = global.fetch;
  try {
    const { forwardInboundMessage } = loadWhatsappClientWithWebhookConfigured();
    const captured = captureForward();

    // An unlisted type has no MEDIA_TYPE_LABELS entry, so extractText yields nothing and the
    // message would previously have been dropped entirely.
    const result = await forwardInboundMessage(mediaMessage({ type: 'some_new_media_type' }));

    assert.equal(result, true);
    assert.equal(captured.body.message, '[File] photo.png');
    assert.equal(captured.body.attachments.length, 1);
  } finally {
    global.fetch = originalFetch;
  }
});

test('a captioned media message keeps its caption as the message text', async () => {
  const originalFetch = global.fetch;
  try {
    const { forwardInboundMessage } = loadWhatsappClientWithWebhookConfigured();
    const captured = captureForward();

    await forwardInboundMessage(mediaMessage({ body: 'Look at this' }));

    assert.equal(captured.body.message, 'Look at this');
    assert.equal(captured.body.attachments.length, 1);
  } finally {
    global.fetch = originalFetch;
  }
});

test('a failed media download still forwards the message with its placeholder text', async () => {
  const originalFetch = global.fetch;
  try {
    const { forwardInboundMessage } = loadWhatsappClientWithWebhookConfigured();
    const captured = captureForward();

    const result = await forwardInboundMessage(
      mediaMessage({
        downloadMedia: async () => {
          throw new Error('media expired');
        },
      }),
    );

    assert.equal(result, true);
    assert.deepEqual(captured.body.attachments, []);
    // extractText's MEDIA_TYPE_LABELS placeholder still applies.
    assert.equal(captured.body.message, '[Image]');
  } finally {
    global.fetch = originalFetch;
  }
});

test('downloadMedia resolving undefined is treated as no media, not a crash', async () => {
  const originalFetch = global.fetch;
  try {
    const { forwardInboundMessage } = loadWhatsappClientWithWebhookConfigured();
    const captured = captureForward();

    const result = await forwardInboundMessage(mediaMessage({ downloadMedia: async () => undefined }));

    assert.equal(result, true);
    assert.deepEqual(captured.body.attachments, []);
  } finally {
    global.fetch = originalFetch;
  }
});

test('media above the size cap is skipped without dropping the message', async () => {
  const originalFetch = global.fetch;
  const originalCap = process.env.WHATSAPP_MAX_INBOUND_MEDIA_BYTES;
  try {
    const { forwardInboundMessage } = loadWhatsappClientWithWebhookConfigured({
      WHATSAPP_MAX_INBOUND_MEDIA_BYTES: '3',
    });
    const captured = captureForward();

    const result = await forwardInboundMessage(mediaMessage());

    assert.equal(result, true);
    assert.deepEqual(captured.body.attachments, []);
  } finally {
    global.fetch = originalFetch;
    if (originalCap === undefined) {
      delete process.env.WHATSAPP_MAX_INBOUND_MEDIA_BYTES;
    } else {
      process.env.WHATSAPP_MAX_INBOUND_MEDIA_BYTES = originalCap;
    }
  }
});

test('a text-only inbound message carries an empty attachments array', async () => {
  const originalFetch = global.fetch;
  try {
    const { forwardInboundMessage } = loadWhatsappClientWithWebhookConfigured();
    const captured = captureForward();

    await forwardInboundMessage({
      fromMe: false,
      isStatus: false,
      body: 'plain text',
      from: '31612345678@c.us',
      timestamp: 1000,
      id: { _serialized: 'wamid.text-1' },
    });

    assert.deepEqual(captured.body.attachments, []);
  } finally {
    global.fetch = originalFetch;
  }
});

// The single highest-blast-radius risk in this feature: backfillAllChats forwards in batches
// of 200, so downloading media there would mean thousands of WhatsApp Web round trips and
// multi-hundred-MB batch bodies. The guard is the call site, not a `source` check.
test('the history/backfill path never downloads media', async () => {
  const originalFetch = global.fetch;
  const originalEnv = {
    CRM_API_BASE_URL: process.env.CRM_API_BASE_URL,
    CRM_WEBHOOK_SECRET: process.env.CRM_WEBHOOK_SECRET,
  };

  try {
    const batchedPayloads = [];
    global.fetch = async (url, options = {}) => {
      if (String(url).includes('/backfill-identities')) {
        return {
          ok: true,
          status: 200,
          headers: { 'content-type': 'application/json' },
          json: async () => ({
            ok: true,
            entries: [
              {
                tenant_id: 7,
                tenant_name: 'Guest',
                booking_id: 'B-1',
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
      if (options.body) {
        const parsed = JSON.parse(options.body);
        if (Array.isArray(parsed.messages)) {
          batchedPayloads.push(...parsed.messages);
          return {
            ok: true,
            status: 200,
            headers: { 'content-type': 'application/json' },
            json: async () => ({ ok: true, processed: parsed.messages.length, failed: 0 }),
            text: async () => '',
          };
        }
      }
      return {
        ok: true,
        status: 200,
        headers: { 'content-type': 'application/json' },
        json: async () => ({ ok: true }),
        text: async () => '',
      };
    };

    process.env.CRM_API_BASE_URL = 'http://crm.test';
    process.env.CRM_WEBHOOK_SECRET = 'test-webhook-secret';
    const { backfillAllChats } = loadWhatsappClientWithWebhookConfigured();

    let downloadCalls = 0;
    const historyMessage = {
      fromMe: false,
      isStatus: false,
      type: 'image',
      hasMedia: true,
      body: 'Historical photo',
      from: '31612345678@c.us',
      to: '15550000000@c.us',
      timestamp: 1710000000,
      id: { _serialized: 'wamid.history-1' },
      downloadMedia: async () => {
        downloadCalls += 1;
        return { data: 'aGVsbG8=', mimetype: 'image/png', filename: 'photo.png' };
      },
    };

    await backfillAllChats({
      all: true,
      clientOverride: {
        getChats: async () => [
          {
            id: { _serialized: '31612345678@c.us', user: '31612345678' },
            isGroup: false,
            syncHistory: async () => {},
            fetchMessages: async () => [historyMessage],
          },
        ],
      },
      readyOverride: true,
      limit: 10,
      postSyncDelayMs: 0,
    });

    assert.equal(downloadCalls, 0, 'backfill must never call downloadMedia');
    assert.ok(batchedPayloads.length > 0, 'expected the backfill to forward at least one message');
    for (const item of batchedPayloads) {
      assert.deepEqual(item.attachments, [], 'backfilled messages must carry no media');
    }
  } finally {
    global.fetch = originalFetch;
    for (const [key, value] of Object.entries(originalEnv)) {
      if (value === undefined) {
        delete process.env[key];
      } else {
        process.env[key] = value;
      }
    }
  }
});
