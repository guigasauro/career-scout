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

from career_scout.analytics.budget import load_budgets as _load_budgets
from career_scout.analytics.deficiencies import deficiencies as _deficiencies, load_teams as _load_sb_teams
from career_scout.analytics.recommend import recommend as _recommend
from career_scout.extract.transfermarkt import get_arrivals
from career_scout.match.sofifa import (
    available_rosters, club_leagues, league_levels, league_names, roster_csv, line_of_pos, load_sofifa, rank_candidates, team_line_overall,
)
from career_scout.models import Transfer
from career_scout.profile.aggregate import build_profiles, load_transfers

BASE = Path(__file__).parent.parent / "data"

LEAGUE_COUNTRY: dict[str, str] = {
    "English Premier League":          "England",
    "English League Championship":     "England",
    "English League One":              "England",
    "English League Two":              "England",
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


def _load_sofifa_league_country() -> dict[str, str]:
    """League_name→país pras edições raspadas ao vivo (FIFA 23+): nomes vêm no
    estilo do próprio site ('Premier League'), não no estilo Kaggle usado em
    LEAGUE_COUNTRY ('English Premier League') — mapa separado, gerado por
    `sofifa_scraper.fetch_league_catalog` e cacheado em sofifa_leagues.json."""
    p = BASE / "raw" / "sofifa_leagues.json"
    if not p.exists():
        return {}
    raw = json.loads(p.read_text(encoding="utf-8"))
    return {
        f"{c['value']} ({c['nationName']})" if c.get("nationName") else c["value"]: c.get("nationName", "Outros")
        for group in raw["data"]
        for c in group["childs"]
    }


SOFIFA_LEAGUE_COUNTRY: dict[str, str] = _load_sofifa_league_country()


def _load_sofifa_league_level() -> dict[str, int]:
    """Divisão das ligas raspadas (CSVs sem `league_level`). O catálogo do SoFIFA
    lista as ligas de cada país da 1ª para baixo (grupo TOP 5 antes do A-Z),
    então a posição dentro do país = divisão. Rótulo igual ao gravado no CSV."""
    from career_scout.match.sofifa_scraper import league_label
    p = BASE / "raw" / "sofifa_leagues.json"
    if not p.exists():
        return {}
    levels: dict[str, int] = {}
    per_nation: Counter = Counter()
    for group in json.loads(p.read_text(encoding="utf-8"))["data"]:
        for c in group["childs"]:
            nation = c.get("nationName", "")
            per_nation[nation] += 1
            levels[league_label(c["value"], nation)] = per_nation[nation]
    return levels


SOFIFA_LEAGUE_LEVEL: dict[str, int] = _load_sofifa_league_level()

# Ligas que o CSV Kaggle rotula mas que não existem como liga jogável no FIFA
# (ex.: Wrexham marcado como National League no FIFA 22 — no jogo fica em Resto do Mundo).
HIDDEN_LEAGUES: set[str] = {"English National League"}

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
    # players_22.csv e players_22_latest.csv são a mesma edição
    return sorted({int(p.stem.split("_")[1]) for p in (BASE / "raw").glob("players_*.csv")})


def _edition_csv(edition: int, roster: str | None = None) -> Path:
    """CSV da versão de elenco pedida; sem versão, a base (ou a única que existir)."""
    rosters = available_rosters(BASE / "raw", edition)
    if roster not in rosters:
        if roster or not rosters:
            raise HTTPException(404, f"Dataset FIFA {edition} ({roster or 'qualquer versão'}) não encontrado em data/raw/")
        roster = rosters[0]
    return roster_csv(BASE / "raw", edition, roster)


def _league_country(league_name: str) -> str:
    return LEAGUE_COUNTRY.get(league_name) or SOFIFA_LEAGUE_COUNTRY.get(league_name, "Outros")


# Data do update XX0002 de onde vêm os CSVs do Kaggle (lista de updates do SoFIFA, conferida em 2026-10-12).
# São 1–16 dias antes do lançamento oficial; o FIFA 19 é a exceção (5 semanas antes).
KAGGLE_UPDATES = {15: "Sep 18, 2014", 16: "Sep 21, 2015", 17: "Sep 20, 2016", 18: "Sep 18, 2017",
                  19: "Aug 21, 2018", 20: "Sep 19, 2019", 21: "Sep 23, 2020", 22: "Sep 23, 2021"}


@app.get("/data-info")
def data_info():
    """Versões de elenco de cada edição, com origem e data (seletor "Elenco" e "Como funciona")."""
    p = BASE / "raw" / "sofifa_versions.json"
    scraped = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    def info(e: int, roster: str) -> dict:
        v = scraped.get(roster_csv(BASE / "raw", e, roster).stem)
        # sem registro de coleta = CSV do Kaggle (FIFA 15–22, elenco de lançamento: update XX0002)
        return {"roster": roster, "source": "sofifa" if v else "kaggle",
                "update": v["date"] if v else KAGGLE_UPDATES.get(e)}

    return [{"edition": e, "rosters": [info(e, r) for r in available_rosters(BASE / "raw", e)]}
            for e in fifa_years()]


@app.get("/countries")
def countries(edition: int):
    csv_path = _edition_csv(edition)
    league_set = league_names(csv_path) - HIDDEN_LEAGUES
    found = sorted({_league_country(l) for l in league_set})
    # "Outros" sempre por último
    return [c for c in found if c != "Outros"] + (["Outros"] if "Outros" in found else [])


@app.get("/leagues")
def leagues(edition: int, country: str | None = None):
    csv_path = _edition_csv(edition)
    levels = league_levels(csv_path) or SOFIFA_LEAGUE_LEVEL
    # Ordena por divisão (1ª, 2ª…) e depois por nome; sem nível conhecido vai pro fim.
    all_leagues = sorted(league_names(csv_path) - HIDDEN_LEAGUES,
                         key=lambda l: (levels.get(l, 99), l))
    if country:
        all_leagues = [l for l in all_leagues if _league_country(l) == country]
    return all_leagues


@app.get("/clubs")
def clubs(league: str | None = None, edition: int | None = None):
    if edition is None:
        return [c for c in CLUBS_DB if c.get("league") == league] if league else CLUBS_DB
    # liga vem do CSV da edição, não do mapping (que guarda a liga da 1ª edição em que o clube apareceu)
    csv_path = _edition_csv(edition)
    in_ed = club_leagues(csv_path)
    return [{**c, "league": in_ed[c["sofifa_name"]]} for c in CLUBS_DB
            if c["sofifa_name"] in in_ed and (league is None or in_ed[c["sofifa_name"]] == league)]


class ScoutRequest(BaseModel):
    club_id: int
    club_slug: str
    club_name: str
    fifa_edition: int   # ex.: 22 para FIFA 22; mapeia para players_22.csv e seasons até 2021
    history: int = 5
    top_n: int = 10
    potential_weight: float = 0.0   # 0 = ignora potencial; >0 prioriza promessas
    fee_discount: float = 0.8       # D2: value_eur alvo = fee_mean × α (prêmio embutido na fee)
    realism: bool = False           # modo reforço: ancora no overall titular do clube
    level_offset: int = 0           # ambição: 0 similar, +3 upgrade, -3 aposta barata
    sort_by: str = "score"          # "score" (encaixe) | "overall" (melhores jogadores)
    score_threshold: float = 0.0    # rol acima do threshold (0 = backend usa default no modo reforço)
    value_log: bool = False         # eixo de valor em escala log (teste A/B)
    roster: str | None = None       # versão do elenco: "launch" | "latest" (None = base da edição)


def _save_transfers(transfers: list[Transfer], path: Path) -> None:
    rows = [asdict(t) for t in transfers]
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)


def _arrivals_path(req: ScoutRequest) -> Path:
    # history entra na chave: a janela muda o conjunto de chegadas (e o dedup cross-season)
    return BASE / "processed" / f"arrivals_{req.club_id}_{req.fifa_edition}_h{req.history}.csv"


def _extract_or_load(req: ScoutRequest) -> list[Transfer]:
    """Estágio 1: usa cache se existir, raspa o TM caso contrário."""
    arrivals_path = _arrivals_path(req)
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
    cached = _arrivals_path(req).exists()
    transfers = _extract_or_load(req)
    profiles  = build_profiles(transfers)

    fees = [t.fee for t in transfers if t.fee is not None and t.fee > 0]
    ages = [t.age for t in transfers if t.age is not None]
    permanent = [t for t in transfers if t.transfer_type == "permanent"]
    loans     = [t for t in transfers if t.transfer_type == "loan"]
    free      = [t for t in transfers if t.transfer_type == "free"]

    by_season   = dict(sorted(Counter(t.season for t in transfers).items(), reverse=True))
    by_pos      = dict(Counter(t.position_norm or "?" for t in transfers).most_common())
    by_pos_raw  = dict(Counter(t.position_raw for t in transfers if t.position_raw).most_common())
    by_nat      = dict(Counter(t.nationality for t in transfers if t.nationality).most_common())
    by_league   = dict(Counter(t.from_league for t in transfers if t.from_league).most_common())
    by_club     = dict(Counter(t.from_club for t in transfers if t.from_club).most_common(20))

    perm_fees = [t.fee for t in permanent if t.fee is not None and t.fee > 0]

    return {
        "club": req.club_name,
        "fifa_edition": req.fifa_edition,
        "cached": cached,
        # totais
        "total": len(transfers),
        "n_permanent": len(permanent),
        "n_loan": len(loans),
        "n_free": len(free),
        # distribuições
        "by_season":      by_season,
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
    sofifa_csv = _edition_csv(req.fifa_edition, req.roster)

    transfers = _extract_or_load(req)
    profiles  = build_profiles(transfers)
    players = load_sofifa(sofifa_csv)

    # mesmo id TM pode ter vários nomes SoFIFA ("Arsenal" no Kaggle, "Arsenal FC" no FC 26): usar o da edição
    in_ed = club_leagues(sofifa_csv)
    same_id = [c for c in CLUBS_DB if c["id"] == req.club_id]
    club_info = next((c for c in same_id if c["sofifa_name"] in in_ed), same_id[0] if same_id else None)
    sofifa_name = club_info["sofifa_name"] if club_info else None

    team_levels = team_line_overall(players, sofifa_name) if req.realism else {}
    threshold = req.score_threshold or (0.4 if req.realism else 0.0)
    # "overall" só faz sentido junto do modo reforço (ordena por nível bruto,
    # não por encaixe no perfil histórico) — sem isso, sort_by="overall" vazado
    # de um toggle anterior do frontend faz o /scout parecer que ignora
    # completamente o histórico de contratações do clube.
    sort_by = req.sort_by if req.realism else "score"

    positions = []
    for profile in profiles:
        if not profile.age_mean:
            continue
        team_overall = team_levels.get(line_of_pos(profile.position_norm)) if req.realism else None
        targets = {}
        candidates = rank_candidates(profile, players, top_n=None,
                                     exclude_club=sofifa_name,
                                     potential_weight=req.potential_weight,
                                     fee_discount=req.fee_discount,
                                     team_overall=team_overall,
                                     level_offset=req.level_offset,
                                     score_threshold=threshold,
                                     sort_by=sort_by,
                                     value_log=req.value_log,
                                     targets=targets)
        positions.append({
            "profile": asdict(profile),
            "team_overall": team_overall,
            "target_overall": team_overall + req.level_offset if team_overall else None,
            "targets": targets,         # alvos e pesos (%) de cada eixo do score
            "total": len(candidates),   # tamanho do rol; a lista vem cortada em top_n
            "candidates": [asdict(c) for c in candidates[:req.top_n]],
        })

    return {
        "club": req.club_name,
        "fifa_edition": req.fifa_edition,
        "realism": req.realism,
        "level_offset": req.level_offset if req.realism else 0,
        "team_levels": team_levels,
        "positions": positions,
    }


# ── Analytics (pivô §18): deficiências do time e candidatos por função, StatsBomb Open Data ──
def _sb_seasons() -> list[str]:
    return sorted(p.name[3:-10] for p in (BASE / "processed").glob("sb_*_teams.csv"))


def _sb_check(season: str, team: str | None = None) -> list[dict]:
    # season vira nome de arquivo: só aceita as que existem em disco
    if season not in _sb_seasons():
        raise HTTPException(404, f"Temporada {season} não encontrada")
    teams = _load_sb_teams(season)
    if team is not None and team not in {t["team"] for t in teams}:
        raise HTTPException(404, f"Time {team} não encontrado em {season}")
    return teams


def _target(target: str) -> tuple[int, int]:
    try:
        lo, hi = map(int, target.split("-"))
    except ValueError:
        raise HTTPException(422, "target deve ser no formato 1-4")
    return lo, hi


@app.get("/analytics/seasons")
def analytics_seasons():
    return _sb_seasons()


@app.get("/analytics/teams")
def analytics_teams(season: str):
    teams = _sb_check(season)
    return sorted(({"team": t["team"], "rank": int(t["rank"]), "points": int(t["points"])} for t in teams), key=lambda t: t["rank"])


@app.get("/analytics/team")
def analytics_team(season: str, team: str, target: str = "1-4"):
    teams = _sb_check(season, team)
    me = next(t for t in teams if t["team"] == team)
    return {
        "team": team, "rank": int(me["rank"]), "points": int(me["points"]), "matches": int(me["matches"]),
        "goals_for": int(me["goals_for"]), "goals_conceded": int(me["goals_conceded"]),
        "budget": _load_budgets(season).get(team),  # None se o orçamento da temporada não foi calculado
        "deficiencies": _deficiencies(teams, team, _target(target)),
    }


@app.get("/analytics/recommend")
def analytics_recommend(season: str, team: str, target: str = "1-4", max_gap: float = -0.5,
                        max_age: int | None = None, max_value: float | None = None, top: int = 10,
                        all_leagues: bool = True, strength: float = 0.3, budget: bool = False):
    _sb_check(season, team)
    return _recommend(season, team, _target(target), max_gap, min(top, 30), max_age, max_value, all_leagues,
                      min(max(strength, 0.0), 1.0), budget=budget)
