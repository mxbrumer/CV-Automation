"""The ENV=test chat stand-in must produce a reply the review page can use."""

from ajs.services import chat


def test_stub_chat_proposes_the_document_plus_the_instruction() -> None:
    messages = chat.build_messages(
        kind="cv",
        document="# CV\n\nOld text.",
        brief=None,
        cv=None,
        history=[],
        instruction="make it shorter",
    )
    reply = chat.parse_reply("".join(chat.StubChat().stream(messages)))
    assert reply.explanation == "Stub edit applied."
    assert reply.markdown is not None
    assert reply.markdown.startswith("# CV\n\nOld text.")
    assert reply.markdown.endswith("Stub edit: make it shorter")
