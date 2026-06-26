"""Estágio 1 — extração de chegadas do Transfermarkt.

Parsing separado de fetching para facilitar testes com HTML salvo.
"""
import hashlib
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from career_scout.models import Transfer
from career_scout.normalize.positions import normalize

CACHE_DIR = Path("data/raw")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


def _cache_path(url: str) -> Path:
    key = hashlib.md5(url.encode()).hexdigest()[:12]
    return CACHE_DIR / f"tm_{key}.html"


def fetch_html(url: str, force: bool = False) -> str:
    """Busca URL com cache em disco. Nunca refaz request se cache existe."""
    path = _cache_path(url)
    if not force and path.exists():
        return path.read_text(encoding="utf-8")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    path.write_text(resp.text, encoding="utf-8")
    time.sleep(1)  # rate-limit gentil
    return resp.text


def _parse_value(text: str) -> float | None:
    """Converte '€10.00m', '€500k', '-' em float EUR ou None."""
    t = text.strip().lower().replace(",", ".")
    if not t or t in ("-", "?", "free transfer", "loan", "end of loan"):
        return None
    t = t.replace("€", "").replace("£", "").replace("$", "")
    # extrai número + sufixo m/k, ignorando prefixos como "loan fee:"
    m = re.search(r"([\d.]+)\s*([mk]?)\s*$", t)
    if not m:
        return None
    val = float(m.group(1))
    suffix = m.group(2)
    if suffix == "m":
        return val * 1_000_000
    if suffix == "k":
        return val * 1_000
    return val


def _classify_transfer(text: str) -> tuple[str, float | None]:
    """Retorna (transfer_type, fee). transfer_type: 'permanent' | 'loan' | 'free'."""
    t = text.strip().lower()
    # "End of loan" pode ter data colada (ex.: "End of loan30/06/2014") — sempre fee=0
    if "end of loan" in t:
        return "loan", 0.0
    if "loan fee:" in t or "loan transfer" in t:
        return "loan", _parse_value(text)
    if "loan" in t:
        return "loan", 0.0
    if "free transfer" in t or "draft" in t:
        return "free", 0.0
    fee = _parse_value(text)
    if fee is None and (not t or t in ("-", "?")):
        return "permanent", None
    return "permanent", fee


def parse_arrivals(html: str, club_name: str, season: int, window: str) -> list[Transfer]:
    soup = BeautifulSoup(html, "lxml")

    arrivals_table = None
    for box in soup.select("div.box"):
        h2 = box.find("h2")
        if h2 and "arrivals" in h2.get_text(strip=True).lower():
            arrivals_table = box.find("table", class_="items")
            break

    if arrivals_table is None:
        return []

    transfers: list[Transfer] = []
    for row in arrivals_table.select("tbody tr.odd, tbody tr.even"):
        # recursive=False evita contar células das inline-tables internas
        cells = row.find_all("td", recursive=False)
        if len(cells) < 5:
            continue

        # [0] td.bg_* — posição extraída do inline-table dentro de [1]
        player_td = cells[1]
        inline_rows = player_td.select("table.inline-table tr")
        pos_raw = ""
        player_name = ""
        player_url = ""
        if inline_rows:
            # linha 0: foto + nome; linha 1: posição
            name_a = inline_rows[0].find("a", href=True)
            if name_a:
                player_name = name_a.get_text(strip=True)
                player_url = "https://www.transfermarkt.com" + name_a["href"]
            if len(inline_rows) > 1:
                pos_raw = inline_rows[1].get_text(strip=True)

        # [2] idade
        age_text = cells[2].get_text(strip=True)
        age: int | None = int(age_text) if age_text.isdigit() else None

        # [3] nacionalidade — primeira bandeira (principal)
        nationality: str | None = None
        flag = cells[3].find("img")
        if flag:
            nationality = flag.get("title") or flag.get("alt")

        # [4] clube de origem (inline-table: td.hauptlink = clube, linha 1 = liga)
        from_club: str | None = None
        from_league: str | None = None
        club_td = cells[4].find("td", class_="hauptlink")
        if club_td:
            club_a = club_td.find("a")
            from_club = club_a.get_text(strip=True) if club_a else club_td.get_text(strip=True)
        from_rows = cells[4].select("table.inline-table tr")
        if len(from_rows) > 1:
            league_a = from_rows[1].find("a")
            from_league = league_a.get_text(strip=True) if league_a else None

        # [5] fee/valor de transferência
        fee_text = cells[5].get_text(strip=True) if len(cells) > 5 else ""
        transfer_type, fee = _classify_transfer(fee_text)

        if not player_name:
            continue

        transfers.append(Transfer(
            club_name=club_name,
            season=season,
            window=window,
            player_name=player_name,
            player_url=player_url,
            position_raw=pos_raw,
            position_norm=normalize(pos_raw),
            age=age,
            nationality=nationality,
            from_club=from_club,
            from_league=from_league,
            transfer_type=transfer_type,
            fee=fee,
        ))
    return transfers


def get_arrivals(
    club_slug: str,
    club_id: int,
    club_name: str,
    seasons: list[int],
    delay: float = 1.5,
) -> list[Transfer]:
    """Coleta chegadas de múltiplas temporadas. Summer + Winter por temporada."""
    all_transfers: list[Transfer] = []
    for season in seasons:
        url = (
            f"https://www.transfermarkt.com/{club_slug}/transfers"
            f"/verein/{club_id}/saison_id/{season}"
        )
        html = fetch_html(url)
        # ponytail: parse_arrivals extrai ambas as janelas da mesma página;
        # TM agrega Summer+Winter no mesmo HTML por saison_id
        transfers = parse_arrivals(html, club_name, season, window="Summer+Winter")
        all_transfers.extend(transfers)
        time.sleep(delay)
    return all_transfers
