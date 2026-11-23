"""PDF dokladu přímo ze serveru (#189) – ze stejné tiskové šablony jako Tisk (WeasyPrint, media print).

WeasyPrint potřebuje systémové knihovny Pango (na Linuxu běžně jsou, na Windows bez GTK ne). Když chybí,
`dostupne()` vrátí False a web místo PDF ukáže hlášku „použijte Tisk“ – zbytek aplikace funguje dál.
"""
from __future__ import annotations

import mimetypes
from pathlib import Path

from app import config

_CHYBA: str | None = None
try:
    import weasyprint  # noqa: F401
except Exception as e:  # ImportError i OSError (chybí Pango)
    weasyprint = None
    _CHYBA = str(e)

NENI = "PDF se na tomto počítači nedá vytvořit (chybí knihovna pro PDF). Použijte Tisk / PDF v prohlížeči."


def dostupne() -> bool:
    return weasyprint is not None


def _fetcher():
    """Statické soubory (/static/…) čte z disku, data: URL zpracuje WeasyPrint; nic se nestahuje ze sítě."""
    from weasyprint.urls import URLFetcher, URLFetcherResponse

    class Fetcher(URLFetcher):
        def fetch(self, url, headers=None):
            if "/static/" in url and not url.startswith("data:"):
                cesta = url.split("/static/", 1)[1].split("?", 1)[0]
                koren = Path(config.STATIC_DIR).resolve()
                soubor = (koren / cesta).resolve()
                if koren in soubor.parents and soubor.is_file():
                    typ = mimetypes.guess_type(soubor.name)[0] or "application/octet-stream"
                    return URLFetcherResponse(url, body=soubor.read_bytes(), headers={"Content-Type": typ})
            if url.startswith("data:"):
                return super().fetch(url, headers)
            raise ValueError(f"PDF nenačítá externí zdroje: {url}")

    return Fetcher(allowed_protocols=["http", "data"])


def z_html(html: str) -> bytes:
    if weasyprint is None:
        raise RuntimeError(NENI)
    return weasyprint.HTML(string=html, base_url="http://autoservis/", url_fetcher=_fetcher()).write_pdf()


def nazev_souboru(cislo: str) -> str:
    return "".join(z for z in cislo if z.isalnum() or z in "-_") + ".pdf"
