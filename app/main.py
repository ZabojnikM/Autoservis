"""Vstupní bod aplikace Autoservis."""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app import config
from app.db import init_db
from app.services import ChybaValidace, NenalezenoError
from app.web.aktualizace import router as aktualizace_router
from app.web.routes import router as web_router
from app.web.sablony import templates


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title=config.APP_NAME, version=config.APP_VERSION, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")
app.include_router(web_router)
app.include_router(aktualizace_router)


@app.exception_handler(NenalezenoError)
def _nenalezeno(request: Request, exc: NenalezenoError):
    return templates.TemplateResponse(
        request, "chyba.html", {"nadpis": "Nenalezeno", "zprava": str(exc)}, status_code=404
    )


@app.exception_handler(ChybaValidace)
def _chyba_validace(request: Request, exc: ChybaValidace):
    return templates.TemplateResponse(
        request, "chyba.html", {"nadpis": "Akci nelze provést", "zprava": str(exc)}, status_code=422
    )


@app.get("/api/zdravi")
def zdravi():
    """Kontrola, že aplikace běží."""
    return {"stav": "ok", "verze": config.APP_VERSION}
