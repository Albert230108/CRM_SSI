"""Strip quoted thread history from an email body, leaving only the new content.

Gmail stores each message's plain-text body with the entire quoted history the
sender's mail client included (e.g. "On ... wrote:" followed by the previous
message, `>`-prefixed lines, or an Outlook "-----Original Message-----" block).
This trims that trailing quoted content so the UI can show just the message
that was actually written for that specific email.
"""

import re

_QUOTE_HEADER_PATTERNS = [
    # Gmail / Apple Mail / most clients: "On Mon, Jan 1, 2024 at 1:23 PM John Doe <john@x.com> wrote:"
    re.compile(r"^[ \t]*On .{0,200} wrote:[ \t]*$", re.IGNORECASE | re.MULTILINE),
    # Outlook: "-----Original Message-----"
    re.compile(r"^[ \t]*-{2,}\s*Original Message\s*-{2,}[ \t]*$", re.IGNORECASE | re.MULTILINE),
    # Outlook separator line before headers
    re.compile(r"^[ \t]*_{5,}[ \t]*$", re.MULTILINE),
    # "From: ... Sent: ... To: ... Subject: ..." header block (Outlook plain text forwards/replies)
    re.compile(r"^[ \t]*From:.{0,300}\n[ \t]*Sent:.{0,300}\n[ \t]*To:", re.IGNORECASE | re.MULTILINE),
    # Generic "-------- Forwarded message --------"
    re.compile(r"^[ \t]*-{2,}\s*Forwarded message\s*-{2,}[ \t]*$", re.IGNORECASE | re.MULTILINE),
]

_QUOTED_LINE = re.compile(r"^[ \t]*>")


def strip_quoted_reply(body: str) -> str:
    """Return only the newly-written portion of an email body.

    Falls back to the original body untouched if stripping would remove
    everything (e.g. the message *is* just a forwarded quote).
    """
    if not body:
        return body

    text = body.replace("\r\n", "\n")

    cutoff = len(text)
    for pattern in _QUOTE_HEADER_PATTERNS:
        match = pattern.search(text)
        if match:
            cutoff = min(cutoff, match.start())

    trimmed = text[:cutoff]

    lines = trimmed.split("\n")
    while lines and _QUOTED_LINE.match(lines[-1]):
        lines.pop()
    trimmed = "\n".join(lines).rstrip()

    if not trimmed.strip():
        return text.strip()
    return trimmed
