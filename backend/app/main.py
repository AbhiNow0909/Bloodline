from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, families, health, patients
from app.api.errors import register_error_handlers
from app.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(title="Bloodline API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(families.router)
    app.include_router(patients.router)
    return app


app = create_app()
