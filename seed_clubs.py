#!/usr/bin/env python3
"""Seed: mapeia clubes dos CSVs Kaggle → Transfermarkt (slug, tm_id).
Salva data/club_mapping.json incrementalmente — pode interromper e retomar.

Uso:
    python seed_clubs.py                         # todos os clubes
    python seed_clubs.py "French Ligue 1"        # só uma liga
    python seed_clubs.py "French Ligue 1" "English Premier League"
"""
import csv
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = Path(__file__).parent / "data"
MAPPING_PATH = BASE / "club_mapping.json"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}
DELAY = 1.5  # segundos entre requests — não alterar sem verificar robots.txt


def collect_clubs(filter_leagues: set[str] | None = None) -> dict[str, str]:
    """{sofifa_club_name: league_name} de todos os CSVs disponíveis."""
    clubs: dict[str, str] = {}
    for csv_path in sorted((BASE / "raw").glob("players_*.csv")):
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                name   = row.get("club_name", "").strip()
                league = row.get("league_name", "").strip()
                if name and (filter_leagues is None or league in filter_leagues):
                    clubs.setdefault(name, league)
    return clubs


# times de base/B/reservas que a busca do TM costuma devolver antes do principal
YOUTH = re.compile(r"(^|-)(u\d\d|under-\d\d|jugend|youth|primavera|reserves?|b|ii|iii|formation|academy|tm)(-|$)")

# bandeira esperada (como o TM escreve) por liga; liga fora daqui = sem filtro de país
LEAGUE_NATIONS = {
    "English League Championship": {"England", "Wales"}, "Championship (England)": {"England", "Wales"},
    "Spanish Segunda División": {"Spain", "Andorra"}, "La Liga 2 (Spain)": {"Spain", "Andorra"},  # FC Andorra
    "Italian Serie B": {"Italy"}, "Serie B (Italy)": {"Italy"},
    "German 2. Bundesliga": {"Germany"}, "2. Bundesliga (Germany)": {"Germany"},
    "French Ligue 2": {"France"}, "Ligue 2 (France)": {"France"},
    "Portuguese Liga ZON SAGRES": {"Portugal"}, "Primeira Liga (Portugal)": {"Portugal"},
    "Holland Eredivisie": {"Netherlands"},
    "Argentina Primera División": {"Argentina"}, "Liga Profesional de Fútbol (Argentina)": {"Argentina"},
    "USA Major League Soccer": {"United States", "Canada"}, "Major League Soccer (United States)": {"United States", "Canada"},
    "Mexican Liga MX": {"Mexico"}, "Liga BBVA MX (Mexico)": {"Mexico"},
    "Turkish Süper Lig": {"Türkiye", "Turkey"}, "Süper Lig (Türkiye)": {"Türkiye", "Turkey"},
    "Saudi Abdul L. Jameel League": {"Saudi Arabia"}, "Pro League (Saudi Arabia)": {"Saudi Arabia"},
}

_STOP = {"fc", "afc", "cf", "ac", "as", "sc", "ss", "ssc", "us", "ud", "rc", "rcd", "cd", "sd", "ca", "bc", "calcio",
         "club", "de", "fk", "sv", "vfb", "vfl", "tsg", "og", "hsc", "osc", "ogc", "sco", "sm", "ea", "esp", "sk", "cp"}


def norm_name(s: str) -> str:
    """Nome sem acento/sufixos ('Arsenal FC' == 'Arsenal'): variantes Kaggle × SoFIFA do mesmo clube."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return " ".join(w for w in re.findall(r"[a-z0-9]+", s) if w not in _STOP)


def parse_tm_clubs(html: str) -> list[tuple[str, int, str]]:
    """(slug, id, país) da caixa "Clubs" da busca — links de clube das outras caixas (jogadores) não contam."""
    soup = BeautifulSoup(html, "lxml")
    for box in soup.select("div.box"):
        head = box.find(["h2", "div"], class_=re.compile("content-box-headline|table-header"))
        if not head or "Clubs" not in head.get_text():
            continue
        rows = []
        for tr in box.select("table.items > tbody > tr"):
            a = tr.find("a", href=re.compile(r"/startseite/verein/\d+"))
            flag = tr.find("img", class_="flaggenrahmen")
            if a:
                m = re.search(r"/([a-z0-9-]+)/startseite/verein/(\d+)", a["href"])
                rows.append((m.group(1), int(m.group(2)), flag.get("title", "") if flag else ""))
        return rows
    return []


def pick_club(rows: list[tuple[str, int, str]], nations: set[str] | None, name: str = "") -> tuple[str, int] | tuple[None, None]:
    own = set(norm_name(name).split())  # "Willem II", "FC Barcelona B": o marcador faz parte do nome, não é base
    for slug, tid, country in rows:
        youth = YOUTH.search(slug)
        if (youth and youth.group(2) not in own) or (nations and country not in nations):
            continue
        return slug, tid
    return None, None


def search_tm(club_name: str, nations: set[str] | None = None) -> tuple[str, int] | tuple[None, None]:
    """Busca no TM; retorna (slug, id) do 1º clube principal do país esperado, ou (None, None)."""
    url = (
        "https://www.transfermarkt.com/schnellsuche/ergebnis/schnellsuche"
        f"?query={requests.utils.quote(club_name)}"
    )
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"erro de rede: {e}")
        return None, None

    return pick_club(parse_tm_clubs(resp.text), nations, club_name)


def main() -> None:
    filter_leagues = set(sys.argv[1:]) or None

    mapping: dict = json.loads(MAPPING_PATH.read_text()) if MAPPING_PATH.exists() else {}
    all_clubs = collect_clubs(filter_leagues)
    todo = {name: league for name, league in all_clubs.items() if name not in mapping}

    league_info = f" (filtrando: {', '.join(filter_leagues)})" if filter_leagues else ""
    print(f"{len(all_clubs)} clubes encontrados{league_info}, {len(todo)} ainda não mapeados.\n")

    if not todo:
        print("Nada a fazer.")
        return

    # variante de nome de um clube já mapeado (ex.: "Sporting CP" × "Sporting Clube de Portugal") vira alias, sem busca
    by_norm = {norm_name(k): k for k, v in mapping.items() if v.get("ok")}
    for i, (name, league) in enumerate(todo.items(), 1):
        print(f"[{i}/{len(todo)}] {name} ({league})... ", end="", flush=True)
        twin = by_norm.get(norm_name(name))
        if twin:
            mapping[name] = {**mapping[twin], "league": league}
            print(f"→ alias de {twin}")
            MAPPING_PATH.write_text(json.dumps(mapping, ensure_ascii=False, indent=2))
            continue
        slug, tid = search_tm(name, LEAGUE_NATIONS.get(league))
        if slug:
            print(f"→ {slug} / {tid}")
            mapping[name] = {"tm_slug": slug, "tm_id": tid, "league": league, "ok": True}
            by_norm[norm_name(name)] = name
        else:
            print("→ não encontrado")
            mapping[name] = {"tm_slug": None, "tm_id": None, "league": league, "ok": False}

        MAPPING_PATH.write_text(json.dumps(mapping, ensure_ascii=False, indent=2))
        time.sleep(DELAY)

    ok = sum(1 for v in mapping.values() if v["ok"])
    print(f"\nConcluído: {ok}/{len(mapping)} mapeados com sucesso.")
    print(f"Revise os 'ok: false' em {MAPPING_PATH} e corrija manualmente se necessário.")
    print("Reinicie a API para carregar o novo mapeamento.")


if __name__ == "__main__":
    main()
