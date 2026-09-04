const test = require('node:test');
const assert = require('node:assert/strict');

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { detectSystemdUnit, isQrArtLine, readServiceLogs } = require('../src/serviceLogs');

function cgroupFixture(contents) {
  const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'wa-cgroup-')), 'cgroup');
  fs.writeFileSync(file, contents, 'utf8');
  return file;
}

// A real qrcode-terminal row from the journal. This is a live linking credential: anyone who scans
// it links their own device to the account, so it must never leave the box over HTTP.
const QR_ART_LINE =
  'Sep 04 14:49:57 ssi-server node[662603]: █ █▄▄▄█ █  ▄███ ▄ ▄ ▄█▀█▀█ █▀▀▀█▄█▄ ▄▄▄▄█ █▀▀▄███▄▀▄▄▀▀▀███';

// Verified against the live box: the service runs as "0::/system.slice/crm-whatsapp.service".
test('detects the systemd unit from a real service cgroup', () => {
  assert.equal(
    detectSystemdUnit(cgroupFixture('0::/system.slice/crm-whatsapp.service\n')),
    'crm-whatsapp.service',
  );
  assert.equal(
    detectSystemdUnit(cgroupFixture('0::/system.slice/crm-whatsapp-2.service\n')),
    'crm-whatsapp-2.service',
  );
});

// A bare "*.service" match would return user@1000.service here and serve the wrong journal.
test('does not mistake a user session for a system unit', () => {
  assert.equal(detectSystemdUnit(cgroupFixture('0::/user.slice/user-1000.slice/session-44433.scope\n')), null);
  assert.equal(detectSystemdUnit(cgroupFixture('0::/user.slice/user-1000.slice/user@1000.service/app.slice\n')), null);
});

test('a missing cgroup file degrades to no unit rather than throwing', () => {
  assert.equal(detectSystemdUnit('/definitely/not/here/cgroup'), null);
});

test('QR art lines are recognised so they can be withheld', () => {
  assert.equal(isQrArtLine(QR_ART_LINE), true);
});

test('ordinary log lines are not mistaken for QR art', () => {
  const ordinary = [
    '2026-09-04T12:16:03+02:00 ssi-server node[1]: WhatsApp client disconnected: LOGOUT',
    '2026-09-04T12:16:03+02:00 ssi-server node[1]: Ignored transient WhatsApp page-navigation race: Target closed',
    '2026-09-04T12:16:03+02:00 ssi-server node[1]: Forwarding sendMessage WhatsApp message to CRM: message_id=wamid.X',
    '2026-09-04T12:16:03+02:00 ssi-server node[1]: progress ▀ 50%',
  ];

  for (const line of ordinary) {
    assert.equal(isQrArtLine(line), false, `should not be treated as QR art: ${line}`);
  }
});

test('readServiceLogs returns journal lines with QR art stripped', async () => {
  const stdout = [
    '2026-09-04T12:16:02+02:00 ssi-server node[1]: Scan this QR code with WhatsApp to connect the service:',
    QR_ART_LINE,
    QR_ART_LINE,
    '2026-09-04T12:16:03+02:00 ssi-server node[1]: WhatsApp client disconnected: LOGOUT',
    '',
  ].join('\n');

  const result = await readServiceLogs({
    unit: 'crm-whatsapp.service',
    lines: 50,
    readJournal: async () => stdout,
  });

  assert.equal(result.available, true);
  assert.equal(result.unit, 'crm-whatsapp.service');
  assert.equal(result.lines.length, 2, 'both QR rows and the blank line are dropped');
  assert.ok(result.lines[1].includes('disconnected: LOGOUT'));
  assert.ok(result.lines.every((line) => !isQrArtLine(line)));
});

test('the requested line count is clamped to the maximum', async () => {
  let capturedArgs = null;

  await readServiceLogs({
    unit: 'crm-whatsapp.service',
    lines: 100000,
    maxLines: 1000,
    readJournal: async (args) => {
      capturedArgs = args;
      return '';
    },
  });

  assert.equal(capturedArgs[capturedArgs.indexOf('-n') + 1], '1000');
});

test('a journalctl failure is reported, not thrown', async () => {
  const result = await readServiceLogs({
    unit: 'crm-whatsapp.service',
    readJournal: async () => {
      throw new Error('Permission denied');
    },
  });

  assert.equal(result.available, false);
  assert.deepEqual(result.lines, []);
  assert.match(result.message, /Permission denied/);
});

// Running outside systemd (local dev) is legitimate, not an error state.
test('an undetectable unit degrades to a clear message', async () => {
  const result = await readServiceLogs({
    unit: null,
    readJournal: async () => {
      throw new Error('journalctl should not be called without a unit');
    },
  });

  assert.equal(result.available, false);
  assert.equal(result.unit, null);
  assert.match(result.message, /WHATSAPP_SERVICE_UNIT/);
});
