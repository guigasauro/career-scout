"""Pivô analytics — dados de evento do StatsBomb Open Data → estatísticas por jogador e por time.

Fonte: github.com/statsbomb/open-data (uso livre não comercial, com crédito ao StatsBomb).
Cobertura útil: temporada 2015/16 completa de Premier League, La Liga e Serie A; Ligue 1 com
377 de 380 jogos. A Bundesliga 2015/16 do repositório tem só os 34 jogos do Leverkusen — fora.
Parsing (`aggregate_match`) separado de fetching (`fetch_json`), como no scraper do TM.
"""
import argparse
import csv
import gzip
import json
import time
from collections import defaultdict
from pathlib import Path

import requests

BASE_URL = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
CACHE_DIR = Path("data/raw/statsbomb")
OUT_DIR = Path("data/processed")

# (competition_id, season_id) das temporadas completas
SEASONS = {
    "premier-league-2015-16": (2, 27),
    "la-liga-2015-16": (11, 27),
    "serie-a-2015-16": (12, 27),
    "ligue-1-2015-16": (7, 27),
}

# contadores somados por jogador; o time soma os dos seus jogadores
STATS = [
    "shots", "goals", "xg", "npxg", "xa", "key_passes", "assists",
    "passes", "passes_completed", "progressive_passes", "passes_into_box",
    "dribbles", "dribbles_completed", "pressures", "tackles", "tackles_won",
    "interceptions", "recoveries", "clearances", "blocks", "aerials_won",
    "npg", "box_receptions", "carries_into_box",
]


def fetch_json(path: str) -> list | dict:
    """Busca um JSON do repositório com cache gzip em disco (um jogo cru tem ~4MB)."""
    cache = CACHE_DIR / (path + ".gz")
    if cache.exists():
        with gzip.open(cache, "rt", encoding="utf-8") as f:
            return json.load(f)
    resp = requests.get(f"{BASE_URL}/{path}", timeout=60)
    resp.raise_for_status()
    cache.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(cache, "wt", encoding="utf-8") as f:
        f.write(resp.text)
    time.sleep(0.2)
    return resp.json()


def _clock(s: str) -> float:
    m, sec = s.split(":")
    return int(m) + int(sec) / 60


def _minutes(lineups: list[dict], match_end: float) -> dict[int, tuple[float, str]]:
    """player_id → (minutos jogados, posição em que mais jogou), pelos intervalos da escalação."""
    out = {}
    for team in lineups:
        for p in team["lineup"]:
            spans = defaultdict(float)
            for pos in p["positions"]:
                end = _clock(pos["to"]) if pos["to"] else match_end
                spans[pos["position"]] += max(0.0, end - _clock(pos["from"]))
            if spans:
                out[p["player_id"]] = (sum(spans.values()), max(spans, key=spans.get))
    return out


def _in_box(loc) -> bool:
    # área adversária no campo StatsBomb 120×80: x ≥ 102, 18 ≤ y ≤ 62
    return loc[0] >= 102 and 18 <= loc[1] <= 62


def aggregate_match(events: list[dict], lineups: list[dict]) -> tuple[dict, dict]:
    """Um jogo → (stats por jogador, stats por time).

    Por time vêm os números a favor (soma dos jogadores) e contra (`*_against`),
    mais `passes_share` (fatia dos passes do jogo, proxy de posse).
    """
    match_end = max(e["minute"] + e["second"] / 60 for e in events)
    mins = _minutes(lineups, match_end)
    xg_by_shot = {e["id"]: e["shot"]["statsbomb_xg"] for e in events if e["type"]["name"] == "Shot"}

    players: dict[int, dict] = {}
    for team in lineups:
        for p in team["lineup"]:
            if p["player_id"] in mins:
                minutes, pos = mins[p["player_id"]]
                players[p["player_id"]] = {
                    "player_id": p["player_id"], "player": p["player_nickname"] or p["player_name"],
                    "team": team["team_name"], "position": pos, "minutes": minutes,
                    "country": p["country"]["name"] if p.get("country") else "",
                    **dict.fromkeys(STATS, 0.0),
                }

    for e in events:
        pid = e.get("player", {}).get("id")
        if pid not in players:
            continue
        s, kind = players[pid], e["type"]["name"]
        if kind == "Shot":
            sh = e["shot"]
            s["shots"] += 1
            s["xg"] += sh["statsbomb_xg"]
            if sh["type"]["name"] != "Penalty":
                s["npxg"] += sh["statsbomb_xg"]
            if sh["outcome"]["name"] == "Goal":
                s["goals"] += 1
                if sh["type"]["name"] != "Penalty":
                    s["npg"] += 1
        elif kind == "Pass":
            ps = e["pass"]
            # escanteio/lateral/falta contam como passe; tiro de meta e saída de bola não
            if ps.get("type", {}).get("name") in ("Goal Kick", "Kick Off"):
                continue
            s["passes"] += 1
            if "assisted_shot_id" in ps:
                s["key_passes"] += 1
                s["xa"] += xg_by_shot.get(ps["assisted_shot_id"], 0.0)
            if ps.get("goal_assist"):
                s["assists"] += 1
            if "outcome" not in ps:  # sem outcome = passe completo
                s["passes_completed"] += 1
                # shortcut: progressivo = avança ≥10 jardas rumo ao gol adversário; não usa a regra da Opta (25% da distância)
                if ps["end_location"][0] - e["location"][0] >= 10:
                    s["progressive_passes"] += 1
                if _in_box(ps["end_location"]) and not _in_box(e["location"]):
                    s["passes_into_box"] += 1
        elif kind == "Ball Receipt*":
            # passe recebido já dentro da área adversária: sinal de infiltração
            if "ball_receipt" not in e and _in_box(e["location"]):
                s["box_receptions"] += 1
        elif kind == "Carry":
            if _in_box(e["carry"]["end_location"]) and not _in_box(e["location"]):
                s["carries_into_box"] += 1
        elif kind == "Dribble":
            s["dribbles"] += 1
            if e["dribble"]["outcome"]["name"] == "Complete":
                s["dribbles_completed"] += 1
        elif kind == "Pressure":
            s["pressures"] += 1
        elif kind == "Duel":
            d = e["duel"]
            if d["type"]["name"] == "Tackle":
                s["tackles"] += 1
                if d.get("outcome", {}).get("name") in ("Won", "Success", "Success In Play", "Success Out"):
                    s["tackles_won"] += 1
        elif kind == "Interception":
            s["interceptions"] += 1
        elif kind == "Ball Recovery":
            s["recoveries"] += 1
        elif kind == "Clearance":
            s["clearances"] += 1
        elif kind == "Block":
            s["blocks"] += 1
        # duelo aéreo ganho vem como flag no próprio evento (passe, chute, corte, domínio)
        if e.get(kind.lower().replace(" ", "_"), {}).get("aerial_won"):
            s["aerials_won"] += 1

    teams: dict[str, dict] = {}
    for p in players.values():
        t = teams.setdefault(p["team"], {"team": p["team"], "matches": 1, **dict.fromkeys(STATS, 0.0)})
        for k in STATS:
            t[k] += p[k]
    names = list(teams)
    total_passes = sum(t["passes"] for t in teams.values()) or 1
    for name in names:
        t, opp = teams[name], next(teams[n] for n in names if n != name)
        t["passes_share"] = t["passes"] / total_passes
        t["opponent"] = opp["team"]
    for name in names:  # a favor do adversário = contra este time
        t, opp = teams[name], teams[teams[name]["opponent"]]
        for k in ("shots", "goals", "xg", "npxg", "passes_into_box", "progressive_passes"):
            t[f"{k}_against"] = opp[k]
    return players, teams


def season_tables(comp_id: int, season_id: int) -> tuple[list[dict], list[dict]]:
    """Temporada inteira → (jogadores somados na temporada, times somados na temporada)."""
    players: dict[int, dict] = {}
    teams: dict[str, dict] = {}
    matches = fetch_json(f"matches/{comp_id}/{season_id}.json")
    for i, m in enumerate(matches, 1):
        mid = m["match_id"]
        # o nome do time nas escalações muda de jogo para jogo ("Olympique de Marseille" × "Marseille"):
        # vale o nome da lista de jogos, casado pelo id
        name_by_id = {m[f"{side}_team"][f"{side}_team_id"]: m[f"{side}_team"][f"{side}_team_name"] for side in ("home", "away")}
        lineups = [{**t, "team_name": name_by_id.get(t["team_id"], t["team_name"])} for t in fetch_json(f"lineups/{mid}.json")]
        p_match, t_match = aggregate_match(fetch_json(f"events/{mid}.json"), lineups)
        for pid, s in p_match.items():
            acc = players.setdefault(pid, {**s, **dict.fromkeys(STATS + ["minutes"], 0.0), "matches": 0, "_pos": defaultdict(float)})
            acc["team"] = s["team"]  # transferido no meio da temporada: fica o último clube
            acc["matches"] += 1
            acc["_pos"][s["position"]] += s["minutes"]
            for k in STATS + ["minutes"]:
                acc[k] += s[k]
        for name, s in t_match.items():
            acc = teams.setdefault(name, {"team": name, "matches": 0, "passes_share": 0.0,
                                          **{k: 0.0 for k in s if k not in ("team", "opponent", "matches", "passes_share")}})
            acc["matches"] += 1
            acc["passes_share"] += s["passes_share"]
            for k, v in s.items():
                if k not in ("team", "opponent", "matches", "passes_share"):
                    acc[k] += v
        # classificação pelo placar oficial (inclui gols contra, que os chutes não pegam)
        for side, other in (("home", "away"), ("away", "home")):
            t = teams[m[f"{side}_team"][f"{side}_team_name"]]
            gf, ga = m[f"{side}_score"], m[f"{other}_score"]
            t["points"] = t.get("points", 0) + (3 if gf > ga else gf == ga)
            t["goals_for"] = t.get("goals_for", 0) + gf
            t["goals_conceded"] = t.get("goals_conceded", 0) + ga
        if i % 50 == 0:
            print(f"  {i}/{len(matches)} jogos", flush=True)
    for acc in players.values():
        acc["position"] = max(acc["_pos"], key=acc["_pos"].get)
        # minutos por posição ("Center Attacking Midfield:1800;Left Wing:900"): o jogador entra
        # em mais de uma função na recomendação (ex.: meia que também joga de ponta)
        acc["positions"] = ";".join(f"{k}:{round(v)}" for k, v in sorted(acc["_pos"].items(), key=lambda kv: -kv[1]))
        del acc["_pos"]
    for acc in teams.values():
        acc["passes_share"] /= acc["matches"]  # média por jogo = posse aproximada
    table = sorted(teams.values(), key=lambda t: (-t["points"], -(t["goals_for"] - t["goals_conceded"]), -t["goals_for"]))
    for rank, t in enumerate(table, 1):
        t["rank"] = rank
    return list(players.values()), table


def save_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        for r in rows:
            w.writerow({k: round(v, 4) if isinstance(v, float) else v for k, v in r.items()})


def main() -> None:
    ap = argparse.ArgumentParser(description="StatsBomb Open Data → CSV de jogadores e times por temporada")
    ap.add_argument("season", choices=SEASONS)
    args = ap.parse_args()
    players, teams = season_tables(*SEASONS[args.season])
    save_csv(players, OUT_DIR / f"sb_{args.season}_players.csv")
    save_csv(teams, OUT_DIR / f"sb_{args.season}_teams.csv")
    print(f"{len(players)} jogadores, {len(teams)} times → {OUT_DIR}/sb_{args.season}_*.csv")


if __name__ == "__main__":
    main()
