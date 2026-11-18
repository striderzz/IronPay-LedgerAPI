"""RFC 9457 problem details: every error is `application/problem+json`."""

from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_JSON = "application/problem+json"


class ProblemError(Exception):
    """Raise from anywhere in a request to return a problem details response."""

    def __init__(
        self,
        status: int,
        detail: str | None = None,
        *,
        title: str | None = None,
        type_: str = "about:blank",
        headers: dict[str, str] | None = None,
        **extensions: Any,
    ) -> None:
        self.status = status
        self.detail = detail
        self.title = title or HTTPStatus(status).phrase
        self.type = type_
        self.headers = headers
        self.extensions = extensions


def problem_response(
    status: int,
    detail: str | None = None,
    *,
    title: str | None = None,
    type_: str = "about:blank",
    instance: str | None = None,
    headers: dict[str, str] | None = None,
    **extensions: Any,
) -> JSONResponse:
    body: dict[str, Any] = {"type": type_, "title": title or HTTPStatus(status).phrase}
    body["status"] = status
    if detail:
        body["detail"] = detail
    if instance:
        body["instance"] = instance
    body.update(jsonable_encoder(extensions))
    return JSONResponse(body, status_code=status, headers=headers, media_type=PROBLEM_JSON)


def install(app: FastAPI) -> None:
    @app.exception_handler(ProblemError)
    async def _problem(request: Request, exc: ProblemError) -> JSONResponse:
        return problem_response(
            exc.status,
            exc.detail,
            title=exc.title,
            type_=exc.type,
            instance=request.url.path,
            headers=exc.headers,
            **exc.extensions,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return problem_response(
            exc.status_code,
            str(exc.detail) if exc.detail else None,
            instance=request.url.path,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        return problem_response(
            422,
            "request validation failed",
            title="Unprocessable Content",
            instance=request.url.path,
            errors=errors,
        )
