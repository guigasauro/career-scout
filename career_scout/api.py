"""API FastAPI — career-scout."""
import csv
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from statistics import mean, median

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from career_scout.extract.transfermarkt import get_arrivals
from career_scout.match.sofifa import league_names, load_sofifa, rank_candidates
from career_scout.models import Transfer
from career_scout.profile.aggregate import build_profiles, load_transfers

BASE = Path(__file__).parent.parent / "data"

LEAGUE_COUNTRY: dict[str, str] = {
    "English Premier League":          "England",
    "English League Championship":     "England",
    "English League One":              "England",
    "English League Two":              "England",
    "English National League":         "England",
    "Spain Primera Division":          "Spain",
    "Spanish Segunda División":        "Spain",
    "French Ligue 1":                  "France",
    "French Ligue 2":                  "France",
    "German 1. Bundesliga":            "Germany",
    "German 2. Bundesliga":            "Germany",
    "German 3. Bundesliga":            "Germany",
    "Italian Serie A":                 "Italy",
    "Italian Serie B":                 "Italy",
    "Holland Eredivisie":              "Netherlands",
    "Portuguese Liga ZON SAGRES":      "Portugal",
    "Belgian Jupiler Pro League":      "Belgium",
    "Turkish Süper Lig":               "Turkey",
    "Russian Premier League":          "Russia",
    "Scottish Premiership":            "Scotland",
    "Scottish Championship":           "Scotland",
    "USA Major League Soccer":         "USA",
    "Mexican Liga MX":                 "Mexico",
    "Campeonato Brasileiro Série A":   "Brazil",
    "Campeonato Brasileiro Série B":   "Brazil",
    "Argentina Primera División":      "Argentina",
    "Japanese J. League Division 1":   "Japan",
    "Korean K League 1":               "South Korea",
    "Chinese Super League":            "China",
    "Australian Hyundai A-League":     "Australia",
    "Austrian Football Bundesliga":    "Austria",
    "Czech Republic Gambrinus Liga":   "Czech Republic",
    "Polish T-Mobile Ekstraklasa":     "Poland",
    "Ukrainian Premier League":        "Ukraine",
    "Danish Superliga":                "Denmark",
    "Swedish Allsvenskan":             "Sweden",
    "Norwegian Eliteserien":           "Norway",
    "Finnish Veikkausliiga":           "Finland",
    "Greek Super League":              "Greece",
    "Swiss Super League":              "Switzerland",
    "Romanian Liga I":                 "Romania",
    "Croatian Prva HNL":               "Croatia",
    "Hungarian Nemzeti Bajnokság I":   "Hungary",
    "Saudi Abdul L. Jameel League":    "Saudi Arabia",
    "UAE Arabian Gulf League":         "UAE",
    "Indian Super League":             "India",
    "South African Premier Division":  "South Africa",
    "Colombian Liga Postobón":         "Colombia",
    "Ecuadorian Serie A":              "Ecuador",
    "Chilian Campeonato Nacional":     "Chile",
    "Paraguayan Primera División":     "Paraguay",
    "Uruguayan Primera División":      "Uruguay",
    "Peruvian Primera División":       "Peru",
    "Venezuelan Primera División":     "Venezuela",
    "Liga de Fútbol Profesional Boliviano": "Bolivia",
    "Cypriot First Division":          "Cyprus",
    "Rep. Ireland Airtricity League":  "Ireland",
    "Rest of World":                   "Outros",
}

# Overrides manuais: prevalecem sobre o club_mapping.json (para correções de nome)
_OVERRIDES: list[dict] = [
    {"name": "PSG", "slug": "paris-saint-germain", "id": 583,
     "sofifa_name": "Paris Saint-Germain", "league": "French Ligue 1"},
]


def _load_clubs() -> list[dict]:
    """Carrega clubes do mapping JSON (se existir) + overrides manuais."""
    path = BASE / "club_mapping.json"
    if not path.exists():
        return _OVERRIDES

    mapping: dict = json.loads(path.read_text())
    by_sofifa = {c["sofifa_name"]: c for c in _OVERRIDES}

    clubs = list(_OVERRIDES)  # overrides primeiro
    seen = {c["sofifa_name"] for c in _OVERRIDES}
    for sofifa_name, info in mapping.items():
        if not info.get("ok") or sofifa_name in seen:
            continue
        clubs.append({
            "name": sofifa_name,
            "slug": info["tm_slug"],
            "id": info["tm_id"],
            "sofifa_name": sofifa_name,
            "league": info["league"],
        })
        seen.add(sofifa_name)
    return clubs


# Carregado uma vez na inicialização; reiniciar a API após novo seed
CLUBS_DB: list[dict] = _load_clubs()

app = FastAPI(title="career-scout")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent.parent / "index.html")


@app.get("/fifa-years")
def fifa_years():
    """Retorna as edições FIFA disponíveis (baseado nos CSVs em data/raw/)."""
    return sorted(
        int(p.stem.split("_")[1])
        for p in (BASE / "raw").glob("players_*.csv")
    )


@app.get("/countries")
def countries(edition: int):
    csv_path = BASE / "raw" / f"players_{edition}.csv"
    if not csv_path.exists():
        raise HTTPException(404, f"Dataset FIFA {edition} não encontrado")
    league_set = league_names(csv_path)
    found = sorted({LEAGUE_COUNTRY.get(l, "Outros") for l in league_set})
    # "Outros" sempre por último
    return [c for c in found if c != "Outros"] + (["Outros"] if "Outros" in found else [])


@app.get("/leagues")
def leagues(edition: int, country: str | None = None):
    csv_path = BASE / "raw" / f"players_{edition}.csv"
    if not csv_path.exists():
        raise HTTPException(404, f"Dataset FIFA {edition} não encontrado")
    all_leagues = sorted(league_names(csv_path))
    if country:
        all_leagues = [l for l in all_leagues if LEAGUE_COUNTRY.get(l, "Outros") == country]
    return all_leagues


@app.get("/clubs")
def clubs(league: str | None = None):
    if league:
        return [c for c in CLUBS_DB if c.get("league") == league]
    return CLUBS_DB


class ScoutRequest(BaseModel):
    club_id: int
    club_slug: str
    club_name: str
    fifa_edition: int   # ex.: 22 para FIFA 22; mapeia para players_22.csv e seasons até 2021
    history: int = 5
    top_n: int = 20


def _save_transfers(transfers: list[Transfer], path: Path) -> None:
    rows = [asdict(t) for t in transfers]
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)


def _extract_or_load(req: ScoutRequest) -> list[Transfer]:
    """Estágio 1: usa cache se existir, raspa o TM caso contrário."""
    arrivals_path = BASE / "processed" / f"arrivals_{req.club_id}_{req.fifa_edition}.csv"
    if arrivals_path.exists():
        return load_transfers(arrivals_path)
    season_ceil = 2000 + req.fifa_edition - 1
    seasons = list(range(season_ceil - req.history + 1, season_ceil + 1))
    transfers = get_arrivals(
        club_slug=req.club_slug,
        club_id=req.club_id,
        club_name=req.club_name,
        seasons=seasons,
    )
    arrivals_path.parent.mkdir(parents=True, exist_ok=True)
    _save_transfers(transfers, arrivals_path)
    return transfers


@app.post("/overview")
def overview(req: ScoutRequest):
    transfers = _extract_or_load(req)
    profiles  = build_profiles(transfers)

    fees = [t.fee for t in transfers if t.fee is not None and t.fee > 0]
    ages = [t.age for t in transfers if t.age is not None]
    permanent = [t for t in transfers if t.transfer_type == "permanent"]
    loans     = [t for t in transfers if t.transfer_type == "loan"]
    free      = [t for t in transfers if t.transfer_type == "free"]

    by_season   = dict(sorted(Counter(t.season for t in transfers).items(), reverse=True))
    by_window   = dict(Counter(t.window for t in transfers))
    by_pos      = dict(Counter(t.position_norm or "?" for t in transfers).most_common())
    by_pos_raw  = dict(Counter(t.position_raw for t in transfers if t.position_raw).most_common())
    by_nat      = dict(Counter(t.nationality for t in transfers if t.nationality).most_common())
    by_league   = dict(Counter(t.from_league for t in transfers if t.from_league).most_common())
    by_club     = dict(Counter(t.from_club for t in transfers if t.from_club).most_common(20))

    perm_fees = [t.fee for t in permanent if t.fee is not None and t.fee > 0]

    return {
        "club": req.club_name,
        "fifa_edition": req.fifa_edition,
        "cached": (BASE / "processed" / f"arrivals_{req.club_id}_{req.fifa_edition}.csv").exists(),
        # totais
        "total": len(transfers),
        "n_permanent": len(permanent),
        "n_loan": len(loans),
        "n_free": len(free),
        # distribuições
        "by_season":      by_season,
        "by_window":      by_window,
        "by_position":    by_pos,
        "by_position_raw": by_pos_raw,
        "by_nationality": by_nat,
        "by_from_league": by_league,
        "by_from_club":   by_club,
        # stats de fee (só contratações com fee conhecida)
        "fee_stats": {
            "n":      len(fees),
            "mean":   round(mean(fees))   if fees else None,
            "median": round(median(fees)) if fees else None,
            "min":    round(min(fees))    if fees else None,
            "max":    round(max(fees))    if fees else None,
            "total":  round(sum(fees))    if fees else None,
            "perm_mean":   round(mean(perm_fees))   if perm_fees else None,
            "perm_median": round(median(perm_fees)) if perm_fees else None,
        },
        "age_stats": {
            "mean": round(mean(ages), 1) if ages else None,
            "min":  min(ages)            if ages else None,
            "max":  max(ages)            if ages else None,
        },
        # listas brutas
        "profiles":  [asdict(p) for p in profiles],
        "arrivals":  [asdict(t) for t in sorted(transfers, key=lambda t: (-t.season, t.window))],
    }


@app.post("/scout")
def scout(req: ScoutRequest):
    sofifa_csv = BASE / "raw" / f"players_{req.fifa_edition}.csv"
    if not sofifa_csv.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Dataset FIFA {req.fifa_edition} não encontrado. Baixe players_{req.fifa_edition}.csv em data/raw/",
        )

    transfers = _extract_or_load(req)
    profiles  = build_profiles(transfers)
    players = load_sofifa(sofifa_csv)

    club_info = next((c for c in CLUBS_DB if c["id"] == req.club_id), None)
    sofifa_name = club_info["sofifa_name"] if club_info else None

    positions = []
    for profile in profiles:
        if not profile.age_mean:
            continue
        candidates = rank_candidates(profile, players, top_n=req.top_n, exclude_club=sofifa_name)
        positions.append({
            "profile": asdict(profile),
            "candidates": [asdict(c) for c in candidates],
        })

    return {
        "club": req.club_name,
        "fifa_edition": req.fifa_edition,
        "positions": positions,
    }
