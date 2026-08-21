"""Render an HTML email body down to readable plain text.

Gmail messages carry a `text/plain` part only when the sender's client bothered to
build one. Plenty of real traffic - OTA notifications, marketing-styled confirmations,
anything composed in a rich-text client - arrives as `text/html` alone. Those messages
used to persist with an empty `body`, which silently reduced every AI prompt to the
subject line, so the model answered without ever seeing what the guest wrote.

This is deliberately a small stdlib parser rather than a dependency: the input is
already-sanitized-for-display email HTML and the output only ever feeds a prompt or a
preview string, so faithful structure matters far less than never crashing on the
malformed markup mail clients routinely emit.
"""

import re
from html.parser import HTMLParser

# Tags whose content is markup machinery, never prose the reader would see.
_SKIPPED_CONTENT_TAGS = {"script", "style", "head", "title", "meta", "link"}

# Tags that end the current line. <br> is handled here too; it has no closing tag.
_BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "br", "div", "dd", "dl", "dt",
    "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4",
    "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p", "pre", "section",
    "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
}

# Tags that start a visually separate paragraph, so they earn a blank line rather
# than just a line break.
_PARAGRAPH_TAGS = {"p", "div", "blockquote", "table", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}

_MULTI_BLANK_LINE = re.compile(r"\n{3,}")
_TRAILING_SPACE = re.compile(r"[ \t]+\n")
_MULTI_SPACE = re.compile(r"[ \t]{2,}")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        # convert_charrefs handles &amp;/&#39; for us, so there is no separate unescape pass.
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        # A counter, not a flag: mail HTML nests <style> inside <head>, and a single
        # closing tag must not re-enable capture while an outer skipped tag is still open.
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in _SKIPPED_CONTENT_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in _PARAGRAPH_TAGS:
            self._chunks.append("\n\n")
        elif tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # <br/> and friends: a self-closing tag never opens a skipped region.
        if not self._skip_depth and tag.lower() in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _SKIPPED_CONTENT_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag in _PARAGRAPH_TAGS:
            self._chunks.append("\n\n")
        elif tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        # Newlines inside HTML source are insignificant whitespace; only the breaks we
        # emit for block tags should survive into the output.
        self._chunks.append(data.replace("\r", " ").replace("\n", " "))

    def text(self) -> str:
        return "".join(self._chunks)


def html_to_text(html: str | None) -> str:
    """Best-effort plain-text rendering of an HTML email body.

    Returns "" for empty input or markup that carries no readable text, so callers can
    use it directly as an `or` fallback behind a real `text/plain` part.
    """
    if not html or not html.strip():
        return ""

    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        # HTMLParser is lenient, but a truncated or pathological body must degrade to
        # "no text" rather than take down an entire Gmail sync.
        return ""

    text = parser.text()
    text = _MULTI_SPACE.sub(" ", text)
    text = _TRAILING_SPACE.sub("\n", text)
    text = _MULTI_BLANK_LINE.sub("\n\n", text)
    return "\n".join(line.rstrip() for line in text.split("\n")).strip()
