import secrets
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from ajs.db.session import get_session
from ajs.services.blob import BlobStore
from ajs.services.langflow_client import LangflowClient
from ajs.settings import Settings, get_settings

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[Session, Depends(get_session)]


def require_api_key(
    settings: SettingsDep, x_api_key: Annotated[str | None, Header()] = None
) -> None:
    """A1: every route needs `X-API-Key == BACKEND_API_KEY`. An unset key refuses everything."""
    expected = settings.backend_api_key
    if not expected or x_api_key is None or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing or invalid API key")


def get_blob_store(settings: SettingsDep) -> BlobStore:
    return BlobStore(settings)


def get_langflow_client(settings: SettingsDep) -> Iterator[LangflowClient]:
    yield LangflowClient(settings)


BlobDep = Annotated[BlobStore, Depends(get_blob_store)]
LangflowDep = Annotated[LangflowClient, Depends(get_langflow_client)]
