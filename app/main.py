from fastapi import FastAPI
from app.core.config import settings
from app.core.exceptions import register_exception_handlers

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Register unified exception handlers
register_exception_handlers(app)

@app.get("/health", tags=["health"])
async def health_check():
    return {"status": "ok", "api": settings.PROJECT_NAME}
