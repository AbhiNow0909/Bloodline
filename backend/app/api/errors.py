from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


async def validation_error_without_input(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Like FastAPI's default 422 handler, but never echoes submitted values back.

    The default includes each invalid `input`, which can be a password or a patient's name.
    """
    errors = [
        {key: value for key, value in error.items() if key != "input"} for error in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": jsonable_encoder(errors)},
    )


def register_error_handlers(app: FastAPI) -> None:
    app.exception_handler(RequestValidationError)(validation_error_without_input)
