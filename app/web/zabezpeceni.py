"""Zabezpečení webu: kontrola původu požadavků (#220) a PIN pro Nastavení (#219).

Kontrola původu (ochrana proti CSRF): požadavek, který mění data (POST, PUT, PATCH, DELETE), musí přijít ze stránky
Autoservisu. Prohlížeč posílá hlavičku `Origin` (případně `Referer`); její adresa (hostitel a port) se musí shodovat
s hlavičkou `Host`, na kterou požadavek přišel – funguje tak přes jakoukoli adresu serveru (místní síť, Tailscale,
přesměrování). Bez obou hlaviček požadavek projde: posílají je všechny prohlížeče u požadavků z cizí stránky, bez nich
chodí jen programy (testy, curl). REST API a MCP chrání vlastní klíče, kontrola se na ně nevztahuje.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import Request

from app.web.sablony import templates
from app.zaznam import log

BEZPECNE_METODY = {"GET", "HEAD", "OPTIONS"}
BEZ_KONTROLY_PUVODU = ("/api/", "/mcp")


def puvod_povolen(request: Request) -> bool:
    """Přišel požadavek, který mění data, ze stránky Autoservisu?"""
    if request.method in BEZPECNE_METODY or request.url.path.startswith(BEZ_KONTROLY_PUVODU):
        return True
    puvod = request.headers.get("origin") or request.headers.get("referer")
    if not puvod:
        return True
    if puvod.strip().lower() == "null":  # sandbox / datová adresa – vždy cizí
        return False
    return urlsplit(puvod).netloc.lower() == request.headers.get("host", "").lower()


async def kontrola_puvodu(request: Request, call_next):
    if puvod_povolen(request):
        return await call_next(request)
    log.warning("Odmítnut požadavek z cizí stránky: %s %s (původ %s)", request.method, request.url.path,
                urlsplit(request.headers.get("origin") or request.headers.get("referer") or "").netloc or "null")
    return templates.TemplateResponse(request, "chyba.html", {
        "nadpis": "Akci nelze provést",
        "zprava": "Požadavek nepřišel z Autoservisu (jiná webová stránka), proto se neprovedl. Nic se nezměnilo.",
    }, status_code=403)


async def zaznam_pozadavku(request: Request, call_next):
    """#225: neošetřená chyba webu a API se zapíše s výpisem (adresa bez parametrů); volání REST API s názvem klíče."""
    try:
        odpoved = await call_next(request)
    except Exception:
        log.exception("Neošetřená chyba: %s %s", request.method, request.url.path)
        raise
    if request.url.path.startswith("/api/v1"):
        klic = getattr(request.state, "api_klic", None) or "bez platného klíče"
        uroven = log.info if odpoved.status_code < 400 else log.warning
        uroven("API %s: %s %s → %s", klic, request.method, request.url.path, odpoved.status_code)
    return odpoved
