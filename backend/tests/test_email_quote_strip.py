from app.services.email_quote_strip import strip_quoted_reply


def test_strips_quote_header_wrapped_across_two_lines():
    """Gmail's plain-text formatter word-wraps long quote headers, e.g.:

    On Mon, 6 Jul 2026 at 20:25, brandscheffer <brandscheffer@protonmail.com>
    wrote:

    with "wrote:" landing on its own line. A single-line-only pattern misses this.
    """
    body = (
        "Hi Brand,\n\nHere is the update you asked for.\n\nKind regards, Sander\n\n"
        "On Mon, 6 Jul 2026 at 20:25, brandscheffer <brandscheffer@protonmail.com>\n"
        "wrote:\n\n> Hi Sander\n>\n> Thanks for the update.\n"
    )
    assert strip_quoted_reply(body) == "Hi Brand,\n\nHere is the update you asked for.\n\nKind regards, Sander"


def test_strips_quote_header_on_single_line():
    body = (
        "Hi Sander\n\nThanks for the reminder.\n\nBest\n\n"
        "On Monday, July 13th, 2026 at 4:45 PM, Short-Stay Inn <info@shortstayinn.com> wrote:\n\n"
        "> Hi Brand,\n>\n> quoted content\n"
    )
    assert strip_quoted_reply(body) == "Hi Sander\n\nThanks for the reminder.\n\nBest"


def test_leaves_plain_reply_with_no_quote_untouched():
    body = "Just a plain reply with no quote."
    assert strip_quoted_reply(body) == body


def test_does_not_false_positive_on_the_word_wrote_mid_sentence():
    body = "I wrote the report yesterday and sent it over.\n\nBest,\nSander"
    assert strip_quoted_reply(body) == body


def test_strips_outlook_original_message_block():
    body = "New content\n\n-----Original Message-----\nFrom: a@b.com\nSent: today\nTo: c@d.com\nSubject: hi\n\nold stuff"
    assert strip_quoted_reply(body) == "New content"


def test_empty_body_returns_empty():
    assert strip_quoted_reply("") == ""
