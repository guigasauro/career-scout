"""Pivô analytics — passo 3: candidatos para cada deficiência do time.

Deficiência (métrica do time com gap ≤ limite) → funções que mais a resolvem
(função + estatísticas do jogador por 90 com peso) → candidatos ranqueados pelo percentil
médio ponderado dessas estatísticas entre os jogadores da mesma função **na liga dele**,
multiplicado pela força da liga (dá para buscar nas 5 grandes ligas da mesma temporada).
Mesma lógica de score do modo FIFA: [0,1] com detalhe por estatística (pontos/máximo).
"""
import argparse
import csv
from pathlib import Path

from career_scout.analytics.deficiencies import deficiencies, load_teams
from career_scout.analytics.market import load_market

OUT_DIR = Path("data/processed")
MIN_MINUTES = 900  # ~10 jogos completos: abaixo disso o "por 90" é ruído
MIN_ROLE_SHARE = 0.3  # entra no pool da função quem jogou ≥30% dos minutos nela

# Força da liga: coeficiente de país da UEFA ao fim de 2015/16 (soma de 2011/12 a 2015/16,
# comp.uefa.com seasonYear=2016). Mede o desempenho dos clubes nas copas europeias, não a
# profundidade da liga inteira.
LEAGUE_COEF = {"la-liga": 105.713, "bundesliga": 80.177, "premier-league": 76.284, "serie-a": 70.439, "ligue-1": 52.749}
# shortcut: fator = 1 − peso × (1 − coef/coef_máx); com o padrão 0,3 → Espanha 1,00 … França 0,85.
# O peso é escolha do usuário (0 desliga); calibrar com jogadores que trocaram de liga quando houver
# mais de uma temporada.
STRENGTH_WEIGHT = 0.3


def league_factor(league: str, weight: float = STRENGTH_WEIGHT) -> float:
    coef = LEAGUE_COEF.get(league)
    return 1 - weight * (1 - coef / max(LEAGUE_COEF.values())) if coef else 1.0


def split_season(season: str) -> tuple[str, str]:
    """"premier-league-2015-16" → ("premier-league", "2015-16")."""
    league, y1, y2 = season.rsplit("-", 2)
    return league, f"{y1}-{y2}"


def sibling_seasons(season: str) -> list[str]:
    """Temporadas de outras ligas no mesmo ano com CSV de jogadores em disco (inclui a própria)."""
    year = split_season(season)[1]
    return sorted(p.name[3:-12] for p in OUT_DIR.glob(f"sb_*-{year}_players.csv"))

_DEF_ACTIONS = {"tackles_won": 1, "interceptions": 1, "clearances": 1, "blocks": 1, "aerials_won": 1}
_DM_ACTIONS = {"tackles_won": 1, "interceptions": 1, "recoveries": 1, "pressures": 1}

# métrica do time → [(função, {estatística do jogador: peso})]
ROLES: dict[str, list[tuple[str, dict[str, float]]]] = {
    "npxg_against":        [("CB", _DEF_ACTIONS), ("DM", _DM_ACTIONS)],
    "shots_against":       [("CB", _DEF_ACTIONS), ("DM", _DM_ACTIONS)],
    "box_entries_against": [("CB", _DEF_ACTIONS), ("FB", {"tackles_won": 1, "interceptions": 1, "blocks": 1})],
    "prog_against":        [("DM", _DM_ACTIONS), ("W", {"pressures": 1})],
    "padj_pressures":      [("CM", {"pressures": 2, "recoveries": 1}), ("W", {"pressures": 1})],
    "padj_tackles_int":    [("CB", {"tackles_won": 1, "interceptions": 1}), ("DM", {"tackles_won": 1, "interceptions": 1})],
    "aerials_won":         [("CB", {"aerials_won": 2, "clearances": 1}), ("ST", {"aerials_won": 1})],
    "npxg":                [("ST", {"npxg": 2, "shots": 1}), ("W", {"npxg": 2, "shots": 1})],
    "shots":               [("ST", {"npxg": 2, "shots": 1}), ("W", {"npxg": 2, "shots": 1})],
    "xg_per_shot":         [("ST", {"xg_per_shot": 2, "npxg": 1})],
    "xa":                  [("AM", {"xa": 2, "key_passes": 1, "passes_into_box": 1}),
                            ("W", {"xa": 2, "key_passes": 1, "dribbles_completed": 1})],
    "passes_into_box":     [("AM", {"xa": 2, "key_passes": 1, "passes_into_box": 1}), ("FB", {"passes_into_box": 2, "progressive_passes": 1})],
    "progressive_passes":  [("CM", {"progressive_passes": 2, "pass_pct": 1}), ("CB", {"progressive_passes": 2, "pass_pct": 1})],
    "pass_pct":            [("CM", {"progressive_passes": 2, "pass_pct": 1}), ("CB", {"progressive_passes": 2, "pass_pct": 1})],
    "dribbles_completed":  [("W", {"xa": 2, "key_passes": 1, "dribbles_completed": 1})],
    "possession":          [("CM", {"passes": 1, "pass_pct": 1, "progressive_passes": 1})],
}
ROLE_LABEL = {"GK": "Goleiro", "CB": "Zagueiro", "FB": "Lateral", "DM": "Volante", "CM": "Meia central",
              "AM": "Meia ofensivo", "W": "Ponta", "ST": "Centroavante"}

# ações defensivas dependem de quanto tempo o time fica sem a bola: ajusta pela posse
_PADJ = {"tackles_won", "interceptions", "clearances", "blocks", "recoveries", "pressures"}


def role_of(position: str) -> str:
    """Posição do StatsBomb ("Left Center Back", "Right Wing"...) → função (chave de ROLE_LABEL)."""
    if position == "Goalkeeper":
        return "GK"
    if "Center Back" in position:
        return "CB"
    if "Back" in position:  # laterais e alas
        return "FB"
    if "Defensive Midfield" in position:
        return "DM"
    if "Attacking Midfield" in position:
        return "AM"
    if "Wing" in position or position in ("Left Midfield", "Right Midfield"):
        return "W"
    if "Forward" in position or "Striker" in position:
        return "ST"
    return "CM"


def roles_of(p: dict) -> dict[str, float]:
    """Fração dos minutos do jogador em cada função (CSV antigo sem `positions`: só a principal)."""
    spans = [x.rsplit(":", 1) for x in p.get("positions", "").split(";") if x] or [(p["position"], 1)]
    total = sum(float(m) for _, m in spans) or 1.0
    out: dict[str, float] = {}
    for pos, m in spans:
        out[role_of(pos)] = out.get(role_of(pos), 0.0) + float(m) / total
    return out


def load_players(season: str) -> list[dict]:
    with open(OUT_DIR / f"sb_{season}_players.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def per90(p: dict, k: str, team_share: float) -> float:
    if k == "pass_pct":
        return 100 * float(p["passes_completed"]) / float(p["passes"]) if float(p["passes"]) else 0.0
    if k == "xg_per_shot":
        return float(p["npxg"]) / float(p["shots"]) if float(p["shots"]) else 0.0
    v = float(p[k]) * 90 / float(p["minutes"])
    return v * 0.5 / (1 - team_share) if k in _PADJ and team_share < 1 else v


def rank_role(players: list[dict], share: dict[str, float], role: str, weights: dict[str, float],
              exclude_team: str | None = None, top_n: int = 10, market: dict[str, dict] | None = None,
              max_age: int | None = None, max_value: float | None = None,
              strength_weight: float = STRENGTH_WEIGHT) -> tuple[list[dict], list[dict]]:
    """Jogadores da função (≥ MIN_MINUTES) ranqueados pelo percentil ponderado nas estatísticas da função.

    O percentil é calculado entre os jogadores da função **na mesma liga** (inclui o próprio
    time) e o score é multiplicado pela força da liga (`league_factor`), então o score dos
    jogadores atuais do clube é comparável ao dos candidatos de qualquer liga. Idade/valor (TM)
    só filtram a lista de candidatos; quem não tem o dado no TM passa pelo filtro.
    """
    market = market or {}
    pool = [p for p in players if roles_of(p).get(role, 0) >= MIN_ROLE_SHARE and float(p["minutes"]) >= MIN_MINUTES]
    by_league: dict[str, list[dict]] = {}
    for p in pool:
        by_league.setdefault(p.get("league", ""), []).append(p)
    vals = {(lg, k): sorted(per90(p, k, share[p["team"]]) for p in ps) for lg, ps in by_league.items() for k in weights}
    total = sum(weights.values())
    out = []
    for p in pool:
        lg, n = p.get("league", ""), len(by_league[p.get("league", "")])
        breakdown, score = {}, 0.0
        for k, w in weights.items():
            v = per90(p, k, share[p["team"]])
            pct = sum(1 for x in vals[(lg, k)] if x < v) / max(1, n - 1)
            score += w * pct
            breakdown[k] = {"per90": round(v, 2), "pct": round(100 * pct)}
        m = market.get(p["player_id"], {})
        out.append({"player_id": p["player_id"], "player": p["player"], "team": p["team"], "league": lg,
                    "position": p["position"], "minutes": round(float(p["minutes"])),
                    "score": round(score / total * league_factor(lg, strength_weight), 3), "stats": breakdown,
                    "age": int(m["age"]) if m.get("age") else None, "value": float(m["value"]) if m.get("value") else None,
                    "tm_player_id": m.get("tm_player_id") or None})
    out.sort(key=lambda c: -c["score"])
    current = [c for c in out if c["team"] == exclude_team]
    cands = [c for c in out if c["team"] != exclude_team
             and not (max_age and c["age"] and c["age"] > max_age)
             and not (max_value and c["value"] and c["value"] > max_value)]
    return cands[:top_n], current


def recommend(season: str, team: str, target: tuple[int, int] = (1, 4), max_gap: float = -0.5, top_n: int = 10,
              max_age: int | None = None, max_value: float | None = None, all_leagues: bool = True,
              strength_weight: float = STRENGTH_WEIGHT) -> list[dict]:
    """Funções a reforçar, da maior deficiência para a menor, cada uma com as deficiências
    que resolve e seus candidatos. Deficiências que pedem a mesma função viram uma entrada só.

    As deficiências são sempre medidas na liga do time; `all_leagues` só amplia onde procurar."""
    teams = load_teams(season)
    players, share, market = [], {}, {}
    for s in (sibling_seasons(season) if all_leagues else [season]):
        league = split_season(s)[0]
        players += [{**p, "league": league} for p in load_players(s)]
        share.update({t["team"]: float(t["passes_share"]) for t in load_teams(s)})
        market.update(load_market(s))
    out: dict[tuple, dict] = {}
    for d in deficiencies(teams, team, target):
        if d["gap"] > max_gap:
            break  # lista vem da maior deficiência para a maior força
        for role, weights in ROLES.get(d["metric"], []):
            key = (role, tuple(weights.items()))
            if key not in out:
                cands, current = rank_role(players, share, role, weights, exclude_team=team, top_n=top_n,
                                           market=market, max_age=max_age, max_value=max_value,
                                           strength_weight=strength_weight)
                out[key] = {"role": role, "weights": weights, "addresses": [], "candidates": cands, "current": current}
            out[key]["addresses"].append({k: d[k] for k in ("metric", "label", "value", "target", "gap")})
    return list(out.values())


def main() -> None:
    ap = argparse.ArgumentParser(description="Candidatos para as deficiências de um time (StatsBomb Open Data)")
    ap.add_argument("season")
    ap.add_argument("team")
    ap.add_argument("--target", default="1-4")
    ap.add_argument("--max-gap", type=float, default=-0.5, help="só deficiências com gap ≤ este valor")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--max-age", type=int, help="idade máxima na janela seguinte (TM)")
    ap.add_argument("--max-value", type=float, help="valor de mercado máximo em milhões de euros (TM)")
    ap.add_argument("--same-league", action="store_true", help="buscar só na liga do time")
    ap.add_argument("--strength", type=float, default=STRENGTH_WEIGHT, help="peso da força da liga (0 desliga)")
    args = ap.parse_args()
    lo, hi = map(int, args.target.split("-"))
    max_value = args.max_value * 1e6 if args.max_value else None
    for r in recommend(args.season, args.team, (lo, hi), args.max_gap, args.top, args.max_age, max_value, not args.same_league, args.strength):
        cols = list(r["weights"])
        fixes = "; ".join(f"{a['label']} {a['gap']:+.2f}" for a in r["addresses"])
        mine = ", ".join(f"{c['player']} {c['score']:.0%}" for c in r["current"][:3]) or "—"
        print(f"\n■ {ROLE_LABEL[r['role']]} ({' + '.join(cols)})\n  resolve: {fixes}\n  atuais: {mine}")
        for i, c in enumerate(r["candidates"], 1):
            stats = "  ".join(f"{k}={c['stats'][k]['per90']}" for k in cols)
            tm = f"{c['age'] or '?':>2}a €{c['value'] / 1e6:5.1f}M" if c["value"] else f"{c['age'] or '?':>2}a      ?"
            print(f"   {i:2}. {c['player'][:26]:26} {c['team'][:20]:20} {c['league'][:14]:14} {tm} {c['minutes']:5}' {c['score']:5.0%}  {stats}")


if __name__ == "__main__":
    main()
