from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    return request.app.state.templates.TemplateResponse(request, "dashboard.html", {"page": "dashboard"})


@router.get("/discovery", response_class=HTMLResponse)
async def discovery_page(request: Request):
    return request.app.state.templates.TemplateResponse(request, "discovery.html", {"page": "discovery"})


@router.get("/leads", response_class=HTMLResponse)
async def leads_page(request: Request):
    return request.app.state.templates.TemplateResponse(request, "leads.html", {"page": "leads"})


@router.get("/leads/{lead_key:path}", response_class=HTMLResponse)
async def lead_detail_page(request: Request, lead_key: str):
    return request.app.state.templates.TemplateResponse(request, "lead_detail.html", {"page": "leads", "lead_key": lead_key})


@router.get("/manual-website", response_class=HTMLResponse)
async def manual_website_page(request: Request):
    return RedirectResponse(url="/website-monitor", status_code=307)


@router.get("/website-monitor", response_class=HTMLResponse)
async def website_monitor_page(request: Request):
    return request.app.state.templates.TemplateResponse(
        request,
        "website_monitor.html",
        {"page": "website_monitor"},
    )


@router.get("/website-studio", response_class=HTMLResponse)
async def retired_website_studio_page():
    return RedirectResponse(url="/website-monitor", status_code=307)


@router.get("/website-studio/{lead_key:path}", response_class=HTMLResponse)
async def retired_website_studio_editor_page(lead_key: str):
    return RedirectResponse(url=f"/leads/{quote(lead_key, safe='')}", status_code=307)


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    return request.app.state.templates.TemplateResponse(request, "settings.html", {"page": "settings"})
