from typing import Optional
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder

class APIException(Exception):
    def __init__(self, status_code: int, message: str, detail: Optional[dict] = None):
        self.status_code = status_code
        self.message = message
        self.detail = detail or {}
        super().__init__(self.message)

class NotFoundException(APIException):
    def __init__(self, message: str = "Resource not found", detail: Optional[dict] = None):
        super().__init__(status_code=404, message=message, detail=detail)

class ConflictException(APIException):
    def __init__(self, message: str = "Resource conflict occurred", detail: Optional[dict] = None):
        super().__init__(status_code=409, message=message, detail=detail)

class UnauthorizedException(APIException):
    def __init__(self, message: str = "Authentication failed", detail: Optional[dict] = None):
        super().__init__(status_code=401, message=message, detail=detail)

class ForbiddenException(APIException):
    def __init__(self, message: str = "Forbidden access", detail: Optional[dict] = None):
        super().__init__(status_code=403, message=message, detail=detail)

class ValidationException(APIException):
    def __init__(self, message: str = "Validation failed", detail: Optional[dict] = None):
        super().__init__(status_code=422, message=message, detail=detail)

# Register exception handlers on the FastAPI app
def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIException)
    async def api_exception_handler(request: Request, exc: APIException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "status": "error",
                "message": exc.message,
                "detail": exc.detail
            }
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "status": "error",
                "message": "Validation failed on request parameter/body",
                "detail": jsonable_encoder(exc.errors())
            }
        )
