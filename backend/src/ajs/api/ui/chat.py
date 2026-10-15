"""Review endpoints (plan 12): chat editing of a generated document, rejection, pasted text."""

import json
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from ajs.api import schemas
from ajs.api.deps import BlobDep, SessionDep, SettingsDep
from ajs.api.ui.postings import run_pipeline
from ajs.db.models import Actor, ArtifactKind, ChatMessage, ChatRole, PostingStatus
from ajs.domain.status import transition
from ajs.services import chat, postings

router = APIRouter(tags=["review"])


def get_chat_llm(settings: SettingsDep) -> chat.ChatLLM:
    return chat.StubChat() if settings.env == "test" else chat.OllamaChat(settings)


ChatDep = Annotated[chat.ChatLLM, Depends(get_chat_llm)]


def _out(m: ChatMessage) -> schemas.ChatMessageOut:
    if m.role is ChatRole.USER:
        return schemas.ChatMessageOut(
            message_id=m.message_id, role=m.role, content=m.content, created_at=m.created_at
        )
    reply = chat.parse_reply(m.content)
    return schemas.ChatMessageOut(
        message_id=m.message_id,
        role=m.role,
        content=reply.explanation,
        proposal=reply.markdown,
        created_at=m.created_at,
    )


def _history(session: SessionDep, posting_id: int, kind: ArtifactKind) -> list[ChatMessage]:
    return list(
        session.scalars(
            select(ChatMessage)
            .where(ChatMessage.posting_id == posting_id, ChatMessage.artifact_kind == kind)
            .order_by(ChatMessage.message_id)
        )
    )


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.get("/postings/{posting_id}/artifacts/{kind}/chat")
def chat_history(
    posting_id: int, kind: ArtifactKind, session: SessionDep
) -> list[schemas.ChatMessageOut]:
    postings.get_posting(session, posting_id)
    return [_out(m) for m in _history(session, posting_id, kind)]


@router.post("/postings/{posting_id}/artifacts/{kind}/chat")
def chat_turn(
    posting_id: int,
    kind: ArtifactKind,
    body: schemas.ChatRequest,
    session: SessionDep,
    store: BlobDep,
    settings: SettingsDep,
    llm: ChatDep,
) -> StreamingResponse:
    """Server-sent events: `delta` {text} while the model writes, then `done` {message}, or
    `error` {detail}. The user turn is saved first; the assistant turn when the reply is whole."""
    posting = postings.get_posting(session, posting_id)
    artifact = postings.latest_artifact(session, posting_id, kind)
    if artifact is None:
        raise HTTPException(404, f"no {kind.value} saved for posting {posting_id}")
    cv_path = settings.profile_root / "cv.md"
    cv = cv_path.read_text(encoding="utf-8") if cv_path.is_file() else None
    earlier = _history(session, posting_id, kind)[-8:]
    messages = chat.build_messages(
        kind=kind.value,
        document=store.read_text(artifact.md_path),
        brief=posting.job_brief,
        cv=cv,
        history=[
            (m.role.value, m.content if m.role is ChatRole.USER else _out(m).content)
            for m in earlier
        ],
        instruction=body.message,
    )
    session.add(
        ChatMessage(
            posting_id=posting_id, artifact_kind=kind, role=ChatRole.USER, content=body.message
        )
    )
    session.commit()  # keep the user turn even if the model call fails

    def events() -> Iterator[str]:
        parts: list[str] = []
        try:
            for text in llm.stream(messages):
                parts.append(text)
                yield _sse("delta", {"text": text})
        except Exception as exc:  # connection refused, model missing, stream cut
            yield _sse("error", {"detail": f"model call failed: {exc}"})
            return
        message = ChatMessage(
            posting_id=posting_id,
            artifact_kind=kind,
            role=ChatRole.ASSISTANT,
            content="".join(parts),
        )
        session.add(message)
        session.commit()
        yield _sse("done", {"message": _out(message).model_dump(mode="json")})

    return StreamingResponse(
        events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )


@router.post("/postings/{posting_id}/artifacts/{kind}/chat/accept")
def chat_accept(
    posting_id: int,
    kind: ArtifactKind,
    body: schemas.ChatAcceptRequest,
    session: SessionDep,
    store: BlobDep,
) -> schemas.ArtifactContent:
    """Save the proposal of one assistant message as the next version (re-renders the PDF)."""
    posting = postings.get_posting(session, posting_id)
    message = session.get(ChatMessage, body.message_id)
    if (
        message is None
        or message.posting_id != posting_id
        or message.artifact_kind is not kind
        or message.role is not ChatRole.ASSISTANT
    ):
        raise HTTPException(404, "no such assistant message for this document")
    proposal = chat.parse_reply(message.content).markdown
    if proposal is None:
        raise HTTPException(409, "that reply holds no revised document")
    artifact = postings.save_artifact(session, store, posting, kind, proposal)
    return schemas.ArtifactContent(
        **schemas.ArtifactOut.model_validate(artifact).model_dump(), markdown=proposal
    )


@router.post("/postings/{posting_id}/reject")  # gate 2: the user decides not to apply
def reject(
    posting_id: int, body: schemas.RejectRequest, session: SessionDep
) -> schemas.StatusResponse:
    posting = postings.get_posting(session, posting_id)
    transition(
        session, posting, PostingStatus.DECLINED, Actor.USER, body.note or "review: rejected"
    )
    return schemas.StatusResponse(posting_id=posting_id, status=posting.status)


@router.patch("/postings/{posting_id}/posting-text")
def paste_posting_text(
    posting_id: int,
    body: schemas.PostingTextRequest,
    session: SessionDep,
    background: BackgroundTasks,
    settings: SettingsDep,
) -> schemas.StatusResponse:
    """Text for a `needs_manual_text` posting: save it and send the posting back to analysis."""
    posting = postings.get_posting(session, posting_id)
    transition(session, posting, PostingStatus.NEW, Actor.USER, "posting text pasted")
    posting.posting_text = body.text.strip()
    session.commit()  # the analysis run must see the new status and text
    background.add_task(run_pipeline, settings)
    return schemas.StatusResponse(posting_id=posting_id, status=posting.status)
