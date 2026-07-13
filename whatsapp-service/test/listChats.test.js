const test = require('node:test');
const assert = require('node:assert/strict');

const { listChats } = require('../src/whatsappClient');
const { whatsappClientId } = require('../src/config');

function fakeChat({ id, name, timestamp, body, isGroup = false }) {
  return {
    id: { _serialized: id },
    name,
    isGroup,
    lastMessage: timestamp ? { timestamp, body } : undefined,
  };
}

test('listChats returns the exact chat_id, including @lid identities', async () => {
  const clientOverride = {
    getChats: async () => [
      fakeChat({ id: '326472368@lid', name: 'Alberto', timestamp: 1710000100, body: 'Hi there' }),
      fakeChat({ id: '111222333@c.us', name: 'Someone Else', timestamp: 1710000000, body: 'Hey' }),
    ],
  };

  const result = await listChats({ externalAccountId: whatsappClientId, clientOverride, readyOverride: true });

  assert.equal(result.total_count, 2);
  const alberto = result.chats.find((chat) => chat.chat_id === '326472368@lid');
  assert.ok(alberto, 'expected the @lid chat to be present with its exact chat_id');
  assert.equal(alberto.chat_name, 'Alberto');
  assert.equal(alberto.last_message_preview, 'Hi there');
  // Most recent activity first.
  assert.equal(result.chats[0].chat_id, '326472368@lid');
});

test('listChats search matches by chat_id substring', async () => {
  const clientOverride = {
    getChats: async () => [
      fakeChat({ id: '326472368@lid', name: 'Alberto', timestamp: 1710000100, body: 'Hi' }),
      fakeChat({ id: '111222333@c.us', name: 'Someone Else', timestamp: 1710000000, body: 'Hey' }),
    ],
  };

  const result = await listChats({ externalAccountId: whatsappClientId, search: '326472368', clientOverride, readyOverride: true });

  assert.equal(result.chats.length, 1);
  assert.equal(result.chats[0].chat_id, '326472368@lid');
});

test('listChats does not fall back to the raw @lid id as the chat name', async () => {
  const clientOverride = {
    getChats: async () => [
      fakeChat({ id: '326472368@lid', name: undefined, timestamp: 1710000100, body: 'Hi' }),
      fakeChat({ id: '351912345678@c.us', name: undefined, timestamp: 1710000000, body: 'Hey' }),
    ],
  };

  const result = await listChats({ externalAccountId: whatsappClientId, clientOverride, readyOverride: true });

  const lidChat = result.chats.find((chat) => chat.chat_id === '326472368@lid');
  assert.equal(lidChat.chat_name, null, 'unnamed @lid chats should not leak the raw id as a display name');

  const phoneChat = result.chats.find((chat) => chat.chat_id === '351912345678@c.us');
  assert.equal(phoneChat.chat_name, '+351912345678', 'unnamed @c.us chats should display the phone number instead');
});

test('listChats search matches phone numbers regardless of spacing', async () => {
  const clientOverride = {
    getChats: async () => [
      fakeChat({ id: '351912345678@c.us', name: '351 912 345 678', timestamp: 1710000100, body: 'Hi' }),
      fakeChat({ id: '111222333@c.us', name: 'Someone Else', timestamp: 1710000000, body: 'Hey' }),
    ],
  };

  const result = await listChats({ externalAccountId: whatsappClientId, search: '351912345678', clientOverride, readyOverride: true });

  assert.equal(result.chats.length, 1);
  assert.equal(result.chats[0].chat_id, '351912345678@c.us');
});

test('listChats search matches text from the last message preview', async () => {
  const clientOverride = {
    getChats: async () => [
      fakeChat({ id: '326472368@lid', name: 'Alberto', timestamp: 1710000100, body: 'See you at the checkout desk' }),
      fakeChat({ id: '111222333@c.us', name: 'Someone Else', timestamp: 1710000000, body: 'Hey' }),
    ],
  };

  const result = await listChats({ externalAccountId: whatsappClientId, search: 'checkout desk', clientOverride, readyOverride: true });

  assert.equal(result.chats.length, 1);
  assert.equal(result.chats[0].chat_id, '326472368@lid');
});

test('listChats rejects a mismatched external_account_id', async () => {
  const clientOverride = { getChats: async () => [] };
  await assert.rejects(
    () => listChats({ externalAccountId: 'some-other-account', clientOverride, readyOverride: true }),
    /account id mismatch/,
  );
});

test('listChats throws when the client is not ready', async () => {
  await assert.rejects(() => listChats({ externalAccountId: whatsappClientId, clientOverride: null, readyOverride: false }), /not ready/);
});
