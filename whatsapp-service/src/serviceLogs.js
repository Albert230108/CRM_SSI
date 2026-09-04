const fs = require("fs");
const { execFile } = require("child_process");

// Reads this service's own systemd journal so operators can diagnose logout/crash loops from the
// CRM admin UI instead of needing shell access.
//
// The journal (not an in-process ring buffer) is deliberate: the logs that matter most here are the
// ones written immediately before a crash-restart, and an in-memory buffer dies with the process
// that produced them.

// qrcode-terminal renders the linking QR straight into stdout as block characters. That QR is a
// live credential - anyone who scans it links their own device to the account - so it must never be
// surfaced over HTTP. Drop any line that is mostly block-drawing glyphs.
const QR_BLOCK_CHARS = /[▀-▟]/g;

function isQrArtLine(line) {
  const blocks = (line.match(QR_BLOCK_CHARS) || []).length;
  return blocks > 8;
}

// Under systemd the cgroup path ends in the unit name, e.g. "0::/system.slice/crm-whatsapp.service".
// Detecting it here keeps the feature zero-config across both account instances, which run the same
// code from different units.
//
// Anchored to system.slice on purpose: a bare "*.service" match would also hit the session manager
// unit ("user@1000.service") when this runs from a user session, and we would then happily serve
// somebody else's journal.
function detectSystemdUnit(cgroupPath = "/proc/self/cgroup") {
  try {
    const cgroup = fs.readFileSync(cgroupPath, "utf8");
    const match = cgroup.match(/\/system\.slice\/(?:[^/\s]*\/)?([A-Za-z0-9_.@-]+\.service)/);
    return match ? match[1] : null;
  } catch (error) {
    return null;
  }
}

function runJournalctl(args, { timeoutMs }) {
  return new Promise((resolve, reject) => {
    execFile(
      "journalctl",
      args,
      { timeout: timeoutMs, maxBuffer: 8 * 1024 * 1024, encoding: "utf8" },
      (error, stdout, stderr) => {
        if (error) {
          reject(new Error(String(stderr || error.message || "journalctl failed").trim()));
          return;
        }
        resolve(String(stdout || ""));
      },
    );
  });
}

async function readServiceLogs({
  unit,
  lines = 200,
  maxLines = 1000,
  timeoutMs = 10000,
  readJournal = runJournalctl,
} = {}) {
  const resolvedUnit = unit || detectSystemdUnit();
  if (!resolvedUnit) {
    return {
      unit: null,
      lines: [],
      available: false,
      // Not an error: running outside systemd (local dev) is legitimate.
      message:
        "Could not determine the systemd unit for this service. Set WHATSAPP_SERVICE_UNIT to enable log viewing.",
    };
  }

  const requested = Math.min(Math.max(1, Number(lines) || 200), maxLines);

  let stdout;
  try {
    stdout = await readJournal(
      ["-u", resolvedUnit, "-n", String(requested), "--no-pager", "-o", "short-iso"],
      { timeoutMs },
    );
  } catch (error) {
    return {
      unit: resolvedUnit,
      lines: [],
      available: false,
      message: `Could not read the journal for ${resolvedUnit}: ${error.message}`,
    };
  }

  const collected = stdout
    .split("\n")
    .map((line) => line.replace(/\s+$/, ""))
    .filter((line) => line.length > 0)
    .filter((line) => !isQrArtLine(line));

  return { unit: resolvedUnit, lines: collected, available: true, message: null };
}

module.exports = { detectSystemdUnit, isQrArtLine, readServiceLogs };
