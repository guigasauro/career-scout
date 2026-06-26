"""Estágio 3 — matching de jogadores SoFIFA contra perfis do Estágio 2."""
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from career_scout.models import PositionProfile

# Pesos padrão (configuráveis via CLI)
# Expande posições de linha (fallback do estágio 2) para posições finas do SoFIFA
_LINE_MEMBERS: dict[str, list[str]] = {
    "ATT": ["ST", "LW", "RW", "CF"],
    "DEF": ["CB", "LB", "RB", "LWB", "RWB"],
    "MID": ["CDM", "CM", "CAM", "LM", "RM"],
    "GK":  ["GK"],
}

DEFAULT_WEIGHTS = {
    "value":       0.40,
    "age":         0.30,
    "nationality": 0.20,
    "league":      0.10,
}


@dataclass
class Candidate:
    sofifa_id: str
    short_name: str
    club_name: str
    league_name: str
    nationality: str
    age: int
    value_eur: Optional[float]
    overall: int
    player_positions: list[str]
    score: float = 0.0


def load_sofifa(csv_path: Path) -> list[dict]:
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _parse_positions(raw: str) -> list[str]:
    return [p.strip() for p in raw.split(",") if p.strip()]


def _normalize_league(league: str) -> str:
    """Normaliza nomes de liga para casar TM ↔ SoFIFA."""
    aliases = {
        "LaLiga":         "Spain Primera Division",
        "La Liga":        "Spain Primera Division",
        "Ligue 1":        "French Ligue 1",
        "Premier League": "English Premier League",
        "Bundesliga":     "German 1. Bundesliga",
        "Serie A":        "Italian Serie A",
        "Eredivisie":     "Holland Eredivisie",
    }
    return aliases.get(league, league)


def rank_candidates(
    profile: PositionProfile,
    players: list[dict],
    top_n: int = 20,
    weights: dict[str, float] | None = None,
    exclude_club: str | None = None,
) -> list[Candidate]:
    w = weights or DEFAULT_WEIGHTS

    # expande linha (ATT/DEF/MID) para as posições finas equivalentes
    target_positions = set(_LINE_MEMBERS.get(profile.position_norm, [profile.position_norm]))

    pool = [
        p for p in players
        if target_positions & set(_parse_positions(p.get("player_positions", "")))
        and p.get("club_name") != exclude_club
    ]
    if not pool:
        return []

    # valores para normalização (z-score simples)
    ages   = [int(p["age"])       for p in pool if p.get("age")]
    values = [float(p["value_eur"]) for p in pool if p.get("value_eur") and p["value_eur"]]

    age_mean   = sum(ages)   / len(ages)   if ages   else 0
    age_std    = (sum((a - age_mean)**2 for a in ages) / len(ages)) ** 0.5 or 1
    val_mean   = sum(values) / len(values) if values else 0
    val_std    = (sum((v - val_mean)**2 for v in values) / len(values)) ** 0.5 or 1

    target_league = _normalize_league(profile.from_league_mode) if profile.from_league_mode else None

    results: list[Candidate] = []
    for p in pool:
        score = 0.0

        # similaridade de valor (1 - distância z normalizada → [0,1])
        if profile.fee_mean and p.get("value_eur") and p["value_eur"]:
            v = float(p["value_eur"])
            # ponytail: comparar value_eur do SoFIFA contra fee_mean do TM (ver D2)
            dist = abs(v - profile.fee_mean) / val_std
            score += w["value"] * max(0.0, 1 - dist / 3)

        # similaridade de idade
        if profile.age_mean and p.get("age"):
            a = int(p["age"])
            dist = abs(a - profile.age_mean) / age_std
            score += w["age"] * max(0.0, 1 - dist / 3)

        # bônus categóricos (match binário)
        if profile.nationality_mode and p.get("nationality_name") == profile.nationality_mode:
            score += w["nationality"]
        if target_league and p.get("league_name") == target_league:
            score += w["league"]

        results.append(Candidate(
            sofifa_id=p.get("sofifa_id", ""),
            short_name=p.get("short_name", p.get("long_name", "")),
            club_name=p.get("club_name", ""),
            league_name=p.get("league_name", ""),
            nationality=p.get("nationality_name", ""),
            age=int(p["age"]) if p.get("age") else 0,
            value_eur=float(p["value_eur"]) if p.get("value_eur") and p["value_eur"] else None,
            overall=int(p["overall"]) if p.get("overall") else 0,
            player_positions=_parse_positions(p.get("player_positions", "")),
            score=round(score, 4),
        ))

    results.sort(key=lambda c: -c.score)
    return results[:top_n]


def save_results(results: list[Candidate], csv_path: Path) -> None:
    if not results:
        return
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["position", "rank", "short_name", "club", "league", "nationality",
                    "age", "value_eur", "overall", "score"])
        for i, c in enumerate(results, 1):
            w.writerow([c.player_positions[0] if c.player_positions else "",
                        i, c.short_name, c.club_name, c.league_name,
                        c.nationality, c.age,
                        c.value_eur and int(c.value_eur), c.overall, c.score])


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Matching SoFIFA × perfis TM")
    parser.add_argument("--year", type=int, default=22, help="Edição FIFA (ex: 22 para FIFA 22)")
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args()

    base = Path(__file__).parent.parent.parent / "data"
    sofifa_csv = base / "raw" / f"players_{args.year}.csv"
    if not sofifa_csv.exists():
        print(f"Dataset não encontrado: {sofifa_csv}")
        print("Baixe com: kaggle datasets download -d stefanoleone992/fifa-22-complete-player-dataset -p data/raw/ --unzip")
        sys.exit(1)

    profiles: list[PositionProfile] = []
    with open(base / "processed" / "profiles.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            profiles.append(PositionProfile(
                position_norm=row["position_norm"],
                n=int(row["n"]),
                n_permanent=int(row["n_permanent"]),
                age_mean=float(row["age_mean"]) if row["age_mean"] else None,
                fee_mean=float(row["fee_mean"]) if row["fee_mean"] else None,
                nationality_mode=row["nationality_mode"] or None,
                from_league_mode=row["from_league_mode"] or None,
                from_club_mode=row["from_club_mode"] or None,
                is_most_frequent=row["is_most_frequent"] == "True",
            ))

    players = load_sofifa(sofifa_csv)
    print(f"FIFA {args.year}: {len(players)} jogadores\n")

    all_results: list[Candidate] = []
    for profile in profiles:
        if not profile.age_mean:
            continue
        top = rank_candidates(profile, players, top_n=args.top)
        all_results.extend(top)
        if top:
            fee_str = f"{profile.fee_mean/1e6:.0f}M" if profile.fee_mean else "-"
            print(f"=== {profile.position_norm} (n={profile.n}, fee≈{fee_str}, "
                  f"nac={profile.nationality_mode}, liga={profile.from_league_mode}) ===")
            for c in top[:5]:
                print(f"  {c.score:.3f}  {c.short_name:20s}  {c.club_name:25s}  "
                      f"{c.nationality:15s}  age={c.age}  €{c.value_eur and c.value_eur/1e6:.1f}M  OVR={c.overall}")
            print()

    out = base / "processed" / "candidates.csv"
    save_results(all_results, out)
    print(f"Salvo em {out}")
