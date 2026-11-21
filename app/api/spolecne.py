"""Společné pro API a MCP (#145): převod na JSON, otisk náhledu, záloha a deník."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal

from sqlmodel import Session

from app.models import ApiKlic
from app.services import ChybaValidace, sprava, zalohy


def hodnota(v):
    """Decimal → text („199.00“, přesně), datum → ISO, ostatní beze změny."""
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def otisk(*casti) -> str:
    """Otisk náhledu – provedení projde jen se stejným otiskem (plán se mezitím nezměnil)."""
    text = json.dumps(casti, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode()).hexdigest()[:20]


def over_otisk(ocekavany: str | None, skutecny: str) -> None:
    if not ocekavany:
        raise ChybaValidace("Chybí otisk náhledu – nejdřív zavolejte náhled a ukažte ho uživateli.")
    if ocekavany != skutecny:
        raise ChybaValidace("Data se od náhledu změnila (nebo jsou jiné parametry). Udělejte nový náhled.")


def zaloha() -> str:
    try:
        return zalohy.pred_sloucenim().name
    except zalohy.ChybaZalohy as e:
        raise ChybaValidace(f"Úprava neproběhla, protože se nepodařilo zálohovat databázi. {e}") from e


def denik(session: Session, klic: ApiKlic | None, akce: str, popis: str, pocet: int, zaloha_: str = "") -> None:
    sprava.zapis(session, f"API {klic.nazev}: {akce}" if klic else akce, popis, pocet, zaloha_)
