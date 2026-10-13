from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from ajs.api.deps import require_api_key
from ajs.api.tools import postings as tool_postings
from ajs.api.ui import postings as ui_postings
from ajs.domain.status import InvalidTransition
from ajs.services.blob import UnsafePath
from ajs.services.postings import Conflict, NotFound

app = FastAPI(title="AI Job Search API", version="0.1.0")

_protected = [Depends(require_api_key)]
app.include_router(ui_postings.router, prefix="/api/v1", dependencies=_protected)
app.include_router(tool_postings.router, prefix="/api/v1", dependencies=_protected)


def _error(status_code: int, exc: Exception) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=status_code)


@app.exception_handler(NotFound)
async def _not_found(_: Request, exc: NotFound) -> JSONResponse:
    return _error(404, exc)


@app.exception_handler(InvalidTransition)
async def _invalid_transition(_: Request, exc: InvalidTransition) -> JSONResponse:
    return _error(409, exc)


@app.exception_handler(Conflict)
async def _conflict(_: Request, exc: Conflict) -> JSONResponse:
    return _error(409, exc)


@app.exception_handler(UnsafePath)
async def _unsafe_path(_: Request, exc: UnsafePath) -> JSONResponse:
    return _error(400, exc)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    """Open on purpose: the Docker healthcheck has no API key."""
    return {"status": "ok"}
