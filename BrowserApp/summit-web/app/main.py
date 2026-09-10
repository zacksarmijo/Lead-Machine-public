from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

import app.config  # noqa: F401 — triggers sys.path setup

from app.routers import pages, dashboard, discovery, leads, ai, settings, outreach, website_monitor
from app.security import LocalOnlyMiddleware

APP_DIR = Path(__file__).resolve().parent


def create_app() -> FastAPI:
    # Built-in interactive docs execute CDN-hosted scripts with app privileges.
    # The local OpenAPI JSON schema remains available without remote code.
    application = FastAPI(title="Summit", docs_url=None, redoc_url=None)
    application.add_middleware(LocalOnlyMiddleware)

    application.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")

    templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
    application.state.templates = templates

    application.include_router(pages.router)
    application.include_router(dashboard.router)
    application.include_router(discovery.router)
    application.include_router(leads.router)
    application.include_router(ai.router)
    application.include_router(settings.router)
    application.include_router(outreach.router)
    application.include_router(website_monitor.router)

    return application


app = create_app()
