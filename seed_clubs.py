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


def search_tm(club_name: str) -> tuple[str, int] | tuple[None, None]:
    """Busca no TM; retorna (slug, id) do primeiro resultado de clube ou (None, None)."""
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

    for a in BeautifulSoup(resp.text, "lxml").find_all("a", href=True):
        m = re.search(r'/([a-z0-9-]+)/startseite/verein/(\d+)', a["href"])
        if m:
            return m.group(1), int(m.group(2))
    return None, None


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

    for i, (name, league) in enumerate(todo.items(), 1):
        print(f"[{i}/{len(todo)}] {name} ({league})... ", end="", flush=True)
        slug, tid = search_tm(name)
        if slug:
            print(f"→ {slug} / {tid}")
            mapping[name] = {"tm_slug": slug, "tm_id": tid, "league": league, "ok": True}
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
