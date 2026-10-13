"""Pivô analytics — passo 4: idade e valor de mercado (Transfermarkt) dos jogadores do StatsBomb.

Lê o elenco de cada clube na temporada (uma página por clube, não uma busca por jogador)
e casa os nomes por semelhança dentro do clube. O TM não mostra contrato em temporadas
passadas, então ficam idade, valor da época, altura e pé.
"""
import argparse
import csv
import json
import re
import unicodedata
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

from bs4 import BeautifulSoup

from career_scout.extract.transfermarkt import _parse_value, fetch_html
from seed_clubs import norm_name

OUT_DIR = Path("data/processed")
MAPPING = Path("data/club_mapping.json")
MIN_NAME_SCORE = 0.6

# nomes do StatsBomb que o mapeamento do modo FIFA não tem: {nome StatsBomb: nome no club_mapping}
TEAM_ALIASES: dict[str, str] = {"Real Betis": "Real Betis Balompié", "Sporting Gijón": "Real Sporting de Gijón"}


def club_index() -> dict[str, tuple[str, int]]:
    """Nome normalizado → (tm_slug, tm_id), a partir do mapeamento do modo FIFA."""
    out = {}
    for name, v in json.loads(MAPPING.read_text(encoding="utf-8")).items():
        if v.get("ok"):
            out.setdefault(norm_name(name), (v["tm_slug"], v["tm_id"]))
    return out


def parse_squad(html: str) -> list[dict]:
    """Página /kader/.../plus/1 → jogadores com nascimento, valor, altura e pé."""
    table = BeautifulSoup(html, "lxml").select_one("table.items")
    if table is None:
        return []
    heads = [th.get_text(" ", strip=True) for th in table.select("thead th")]
    col = {h: i for i, h in enumerate(heads)}
    out = []
    for tr in table.select("tbody > tr"):
        tds = tr.find_all("td", recursive=False)
        link = tr.select_one("td.hauptlink a")
        if len(tds) != len(heads) or link is None:
            continue
        born = re.search(r"(\d{2})/(\d{2})/(\d{4})", tds[col["Date of birth/Age"]].get_text())
        out.append({
            "tm_player_id": int(link["href"].rstrip("/").split("/")[-1]),
            "tm_name": link.get_text(strip=True),
            "birth": date(int(born[3]), int(born[2]), int(born[1])) if born else None,
            "value": _parse_value(tds[col["Market value"]].get_text()),
            "height": tds[col["Height"]].get_text(strip=True).replace(",", ".").rstrip("m") or None,
            "foot": tds[col["Foot"]].get_text(strip=True) or None,
        })
    return out


def _tokens(s: str) -> list[str]:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.findall(r"[a-z]+", s)


def name_score(a: str, b: str) -> float:
    """Semelhança de nomes dentro do mesmo elenco.

    Sobrenome em comum vale mais que primeiro nome: "Timothy Michael Krul" × "Tim Krul" casa,
    "Leon Osman" × "Leon Schaffran" não.
    """
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    seq = SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio()
    if ta[-1] not in tb and tb[-1] not in ta:
        return seq if seq >= 0.85 else 0.0  # sem sobrenome em comum: só grafia quase idêntica
    if ta[0][0] == tb[0][0]:  # mesmo sobrenome e mesma inicial; o resto desempata (Jonathan × Jonny/Jerome Williams)
        return 0.9 + 0.1 * seq
    return max(seq, len(set(ta) & set(tb)) / min(len(set(ta)), len(set(tb))))


def match_squad(players: list[dict], squad: list[dict]) -> dict[str, dict]:
    """player_id do StatsBomb → entrada do elenco do TM (só casamentos com nome parecido)."""
    out = {}
    for p in players:
        best = max(squad, key=lambda s: name_score(p["player"], s["tm_name"]), default=None)
        if best and name_score(p["player"], best["tm_name"]) >= MIN_NAME_SCORE:
            out[p["player_id"]] = best
    return out


def season_market(season: str) -> list[dict]:
    """Uma linha por jogador do StatsBomb com os dados do TM (vazia onde não casou)."""
    start = int(re.search(r"(\d{4})-\d{2}$", season)[1])  # "premier-league-2015-16" → 2015
    ref = date(start + 1, 7, 1)  # idade na janela de verão seguinte
    with open(OUT_DIR / f"sb_{season}_players.csv", encoding="utf-8") as f:
        players = list(csv.DictReader(f))
    clubs = club_index()
    rows = []
    for team in sorted({p["team"] for p in players}):
        club = clubs.get(norm_name(TEAM_ALIASES.get(team, team)))
        if club is None:
            print(f"  sem mapeamento TM: {team}")
            continue
        slug, tm_id = club
        squad = parse_squad(fetch_html(f"https://www.transfermarkt.com/{slug}/kader/verein/{tm_id}/saison_id/{start}/plus/1"))
        matched = match_squad([p for p in players if p["team"] == team], squad)
        for p in players:
            if p["team"] != team:
                continue
            m = matched.get(p["player_id"])
            b = m["birth"] if m else None
            rows.append({
                "player_id": p["player_id"], "player": p["player"], "team": team,
                "tm_player_id": m["tm_player_id"] if m else "", "tm_name": m["tm_name"] if m else "",
                "age": ref.year - b.year - ((ref.month, ref.day) < (b.month, b.day)) if b else "",
                "value": m["value"] if m and m["value"] is not None else "",
                "height": m["height"] if m else "", "foot": m["foot"] if m else "",
            })
    return rows


def load_market(season: str) -> dict[str, dict]:
    """player_id → linha do mercado; {} se o CSV ainda não foi gerado."""
    path = OUT_DIR / f"sb_{season}_market.csv"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return {r["player_id"]: r for r in csv.DictReader(f)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Idade e valor de mercado (TM) dos jogadores de uma temporada do StatsBomb")
    ap.add_argument("season")
    args = ap.parse_args()
    rows = season_market(args.season)
    path = OUT_DIR / f"sb_{args.season}_market.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{sum(1 for r in rows if r['tm_player_id'])}/{len(rows)} jogadores casados → {path}")


if __name__ == "__main__":
    main()
