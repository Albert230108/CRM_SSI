const test = require('node:test');
const assert = require('node:assert/strict');

const { sendTextMessage } = require('../src/whatsappClient');
const { whatsappClientId } = require('../src/config');

function fakeClient() {
  const calls = [];
  let counter = 0;
  return {
    calls,
    sendMessage: async (chatId, content, options) => {
      counter += 1;
      calls.push({ chatId, content, options: options ?? null });
      return { id: { _serialized: `wamid.sent-${counter}` } };
    },
  };
}

function basePayload(client, overrides = {}) {
  return {
    to: '31612345678',
    tenant_id: 7,
    external_account_id: whatsappClientId,
    whatsapp_endpoint_id: 42,
    clientOverride: client,
    readyOverride: true,
    ...overrides,
  };
}

const PDF = { filename: 'invoice.pdf', mime_type: 'application/pdf', data_base64: 'JVBERi0xLjQ=' };
const PNG = { filename: 'photo.png', mime_type: 'image/png', data_base64: 'iVBORw0KGgo=' };

test('a single attachment with text rides along as a caption in one message', async () => {
  const client = fakeClient();

  const result = await sendTextMessage(basePayload(client, { message: 'Here is your invoice', attachments: [PDF] }));

  assert.equal(client.calls.length, 1);
  assert.equal(client.calls[0].options.caption, 'Here is your invoice');
  assert.equal(client.calls[0].content.mimetype, 'application/pdf');
  assert.equal(client.calls[0].content.filename, 'invoice.pdf');
  assert.equal(result.messages.length, 1);
  assert.deepEqual(result.messages[0], {
    whatsapp_message_id: 'wamid.sent-1',
    kind: 'media',
    attachment_index: 0,
  });
});

test('multiple attachments send the text as its own message first, then each file uncaptioned', async () => {
  const client = fakeClient();

  const result = await sendTextMessage(basePayload(client, { message: 'Two files', attachments: [PDF, PNG] }));

  assert.equal(client.calls.length, 3);
  assert.equal(client.calls[0].content, 'Two files');
  assert.equal(client.calls[0].options, null);
  assert.equal(client.calls[1].content.filename, 'invoice.pdf');
  assert.equal(client.calls[1].options, null, 'caption must not be reused on the media parts');
  assert.equal(client.calls[2].content.filename, 'photo.png');

  assert.deepEqual(
    result.messages.map((entry) => [entry.kind, entry.attachment_index]),
    [['text', null], ['media', 0], ['media', 1]],
  );
});

test('an attachment with no text sends only the media', async () => {
  const client = fakeClient();

  const result = await sendTextMessage(basePayload(client, { message: '', attachments: [PDF] }));

  assert.equal(client.calls.length, 1);
  assert.equal(client.calls[0].content.filename, 'invoice.pdf');
  assert.equal(result.messages.length, 1);
  assert.equal(result.messages[0].kind, 'media');
});

test('a text-only send is unchanged and still reports a single text message', async () => {
  const client = fakeClient();

  const result = await sendTextMessage(basePayload(client, { message: 'Just text' }));

  assert.equal(client.calls.length, 1);
  assert.equal(client.calls[0].content, 'Just text');
  assert.equal(client.calls[0].options, null);
  assert.equal(result.whatsapp_message_id, 'wamid.sent-1');
  assert.deepEqual(result.messages, [
    { whatsapp_message_id: 'wamid.sent-1', kind: 'text', attachment_index: null },
  ]);
});

test('whatsapp_message_id stays the first sent id for backwards compatibility', async () => {
  const client = fakeClient();

  const result = await sendTextMessage(basePayload(client, { message: 'Two files', attachments: [PDF, PNG] }));

  assert.equal(result.whatsapp_message_id, 'wamid.sent-1');
  assert.equal(result.messages.length, 3);
  // Every sent message must be individually identifiable, or rows 2..N collide on
  // provider_message_id when the backend persists them.
  const ids = result.messages.map((entry) => entry.whatsapp_message_id);
  assert.equal(new Set(ids).size, 3);
});

test('a send with neither text nor attachments still resolves without calling sendMessage', async () => {
  const client = fakeClient();

  const result = await sendTextMessage(basePayload(client, { message: '' }));

  assert.equal(client.calls.length, 0);
  assert.deepEqual(result.messages, []);
  assert.equal(result.whatsapp_message_id, null);
});
