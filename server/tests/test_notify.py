from __future__ import annotations

from server.notify import NoOpNotifier, build_reply_card, build_thread_card


def test_thread_card_shape():
    card = build_thread_card(
        title="Hello",
        author_name="邓柯",
        body="this is the body",
        thread_url="http://localhost:5173/t/general/hello",
    )
    assert card["schema"] == "2.0"
    assert card["header"]["template"] == "blue"
    assert "新讨论：Hello" in card["header"]["title"]["content"]
    md = card["body"]["elements"][0]["content"]
    assert "邓柯" in md
    assert "this is the body" in md
    button = card["body"]["elements"][1]
    assert button["tag"] == "button"
    assert button["multi_url"]["url"] == "http://localhost:5173/t/general/hello"


def test_reply_card_shape():
    card = build_reply_card(
        thread_title="Parent",
        author_name="Ken",
        body="+1",
        thread_url="http://x/y",
    )
    assert card["header"]["template"] == "green"
    assert "新回复：Parent" in card["header"]["title"]["content"]


def test_card_truncates_long_body():
    long = "x" * 500
    card = build_thread_card(
        title="T", author_name="a", body=long, thread_url="http://x",
    )
    md = card["body"]["elements"][0]["content"]
    body_portion = md.split("\n\n", 1)[1]
    assert len(body_portion) <= 201
    assert body_portion.endswith("…")


def test_noop_notifier_silent():
    n = NoOpNotifier()
    n.notify_new_thread(
        category="c", slug="s", title="t", author_name="a", body="b",
    )
    n.notify_new_reply(
        category="c", slug="s", thread_title="t", author_name="a", body="b",
    )
