"""Vstupní bod aplikace Autoservis."""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import config
from app.db import engine, init_db
from app.api.rest import router as api_router
from app.mcp_server import server as mcp_server
from app.services import ChybaValidace, NenalezenoError, zalohy
from app.services.api_klice import ChybaPristupu
from app.web.aktualizace import router as aktualizace_router
from app.web.routes import router as web_router
from app.web.zalohy import router as zalohy_router
from app.web.sprava_dat import router as sprava_dat_router
from app.web.statistiky import router as statistiky_router
from app.web.api_klice import router as api_klice_router
from app.web.sablony import templates
from app.web import pin as pin_web, zabezpeceni


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    zalohy.spust_planovac(_slozka_zaloh)
    async with mcp_server.mcp.session_manager.run():   # MCP pro boty (#148)
        yield
    zalohy.zastav_planovac()


def _slozka_zaloh() -> str:
    from sqlmodel import Session
    with Session(engine) as s:
        return zalohy.slozka(s)


app = FastAPI(title=config.APP_NAME, version=config.APP_VERSION, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")
app.include_router(pin_web.router)  # #219: PIN pro Nastavení (/nastaveni/pin před ostatními trasami Nastavení)
app.include_router(web_router)
app.include_router(aktualizace_router)
app.include_router(zalohy_router)
app.include_router(sprava_dat_router)
app.include_router(statistiky_router)
app.include_router(api_router)
app.include_router(api_klice_router)
app.mount("/mcp", mcp_server.asgi)
app.middleware("http")(pin_web.ochrana_nastaveni)    # #219: Nastavení jen po zadání PINu
app.middleware("http")(zabezpeceni.kontrola_puvodu)  # #220: požadavky měnící data jen ze stránky Autoservisu (běží první)


def _je_api(request: Request) -> bool:
    return request.url.path.startswith("/api/")


@app.exception_handler(ChybaPristupu)
def _chyba_pristupu(request: Request, exc: ChybaPristupu):
    return JSONResponse({"chyba": str(exc)}, status_code=exc.kod)


@app.exception_handler(NenalezenoError)
def _nenalezeno(request: Request, exc: NenalezenoError):
    if _je_api(request):
        return JSONResponse({"chyba": str(exc)}, status_code=404)
    return templates.TemplateResponse(
        request, "chyba.html", {"nadpis": "Nenalezeno", "zprava": str(exc)}, status_code=404
    )


@app.exception_handler(ChybaValidace)
def _chyba_validace(request: Request, exc: ChybaValidace):
    if _je_api(request):
        return JSONResponse({"chyba": str(exc)}, status_code=422)
    return templates.TemplateResponse(
        request, "chyba.html", {"nadpis": "Akci nelze provést", "zprava": str(exc)}, status_code=422
    )


@app.get("/api/zdravi")
def zdravi():
    """Kontrola, že aplikace běží."""
    return {"stav": "ok", "verze": config.APP_VERSION}
