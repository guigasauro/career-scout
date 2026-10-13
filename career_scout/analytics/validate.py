"""Pivô analytics — passo 5: o método teria recomendado as contratações reais?

Para cada contratação do verão seguinte (Transfermarkt, janela de verão) feita por um time da
temporada, de um jogador que jogou ≥ MIN_MINUTES em alguma das ligas carregadas:
  1. posição: a função dele está entre as que o método mandou reforçar?
  2. lista: ele aparece no top-N de algum perfil recomendado para aquele time?
  3. perfil: ele fica mais bem colocado nos perfis escolhidos pela deficiência do que nos
     outros perfis da mesma função (média × média)?
Cada taxa vem com a do acaso (um jogador qualquer do mesmo pool) para comparar.
"""
import argparse
import csv
import re
from statistics import mean

from career_scout.analytics.budget import season_budgets
from career_scout.analytics.deficiencies import deficiencies, load_teams
from career_scout.analytics.market import TEAM_ALIASES, club_index, load_market
from career_scout.analytics.recommend import (
    MIN_MINUTES, MIN_ROLE_SHARE, PROFILES, STRENGTH_WEIGHT, load_players, plan, rank_role, roles_of,
    sibling_seasons, split_season,
)
from career_scout.extract.transfermarkt import fetch_html, parse_arrivals
from seed_clubs import norm_name

OUT = "data/processed/validation_{year}.csv"


def summer_signings(season: str) -> list[dict]:
    """Chegadas da janela de verão seguinte de cada time da temporada (sem retornos de empréstimo)."""
    start = int(re.search(r"(\d{4})-\d{2}$", season)[1])
    clubs = club_index()
    out = []
    for t in load_teams(season):
        club = clubs.get(norm_name(TEAM_ALIASES.get(t["team"], t["team"])))
        if club is None:
            print(f"  sem mapeamento TM: {t['team']}")
            continue
        slug, tm_id = club
        html = fetch_html(f"https://www.transfermarkt.com/{slug}/transfers/verein/{tm_id}/saison_id/{start + 1}/pos//detailpos/0/w_s/s")
        for a in parse_arrivals(html, t["team"], start + 1, "s"):
            out.append({"team": t["team"], "season": season, "tm_player_id": a.player_url.rstrip("/").split("/")[-1],
                        "player": a.player_name, "transfer_type": a.transfer_type, "fee": a.fee})
    return out


def _rank_of(ranked: list[dict], player_id: str) -> int | None:
    return next((i for i, c in enumerate(ranked, 1) if c["player_id"] == player_id), None)


def evaluate(year: str, target=(1, 4), max_gap=-0.5, strength_weight=STRENGTH_WEIGHT, tops=(10, 30),
             mode="tier", top_k=None, leagues=None, budget=False) -> tuple[list[dict], dict]:
    """`leagues`: só os times dessas ligas são avaliados (separação desenvolvimento × teste);
    o pool de candidatos continua sendo todas as ligas da temporada.
    `budget`: listas e acaso só com jogadores que o clube pode pagar (valor de mercado ≤ teto do
    orçamento histórico; sem valor no TM conta como pagável). Contratação acima do teto = erro."""
    seasons = sibling_seasons(f"x-{year}")
    players, share, market, by_tm = [], {}, {}, {}
    for s in seasons:
        league = split_season(s)[0]
        ps = [{**p, "league": league} for p in load_players(s)]
        players += ps
        share.update({t["team"]: float(t["passes_share"]) for t in load_teams(s)})
        m = load_market(s)
        market.update(m)
        by_id = {p["player_id"]: p for p in ps}
        for pid, r in m.items():
            if r.get("tm_player_id") and pid in by_id:
                by_tm[r["tm_player_id"]] = by_id[pid]

    rows = []
    for season in seasons:
        if leagues and split_season(season)[0] not in leagues:
            continue
        teams = load_teams(season)
        signings = summer_signings(season)
        caps = season_budgets(season) if budget else {}
        for team in sorted({s["team"] for s in signings}):
            needed = plan(deficiencies(teams, team, target, mode), max_gap, top_k)
            cap = caps.get(team, {}).get("cap")
            rank_cache: dict[tuple, list[dict]] = {}
            affordable = lambda pid: not cap or not market.get(pid, {}).get("value") or float(market[pid]["value"]) <= cap

            def ranked(role, profile):
                if (role, profile) not in rank_cache:
                    rank_cache[(role, profile)], _ = rank_role(players, share, role, PROFILES[(role, profile)],
                                                               exclude_team=team, top_n=None, market=market,
                                                               strength_weight=strength_weight, max_value=cap)
                return rank_cache[(role, profile)]

            # acaso: um jogador qualquer do pool (fora do time) cai numa posição pedida / no top-N?
            pool = [p for p in players if p["team"] != team and float(p["minutes"]) >= MIN_MINUTES and affordable(p["player_id"])]
            pool_roles = [{r for r, sh in roles_of(p).items() if sh >= MIN_ROLE_SHARE} for p in pool]
            base_role = mean(bool(rs & set(needed)) for rs in pool_roles) if pool else 0.0
            top_ids = {n: {c["player_id"] for role, profs in needed.items() for prof in profs for c in ranked(role, prof)[:n]}
                       for n in tops}
            base_top = {n: len(top_ids[n]) / len(pool) if pool else 0.0 for n in tops}

            for s in (x for x in signings if x["team"] == team):
                p = by_tm.get(s["tm_player_id"])
                row = {**s, "in_pool": False, "roles": "", "role_match": "", "best_rank": "", "pct_needed": "",
                       "pct_other": "", "base_role": round(base_role, 3), "cap": cap or "", "affordable": "",
                       **{f"hit{n}": "" for n in tops}, **{f"base_top{n}": round(base_top[n], 3) for n in tops}}
                if p is None or p["team"] == team or float(p["minutes"]) < MIN_MINUTES:
                    rows.append(row)  # veio de fora das ligas carregadas, jogou pouco ou já era do time
                    continue
                roles = {r for r, sh in roles_of(p).items() if sh >= MIN_ROLE_SHARE}
                if not roles:
                    rows.append(row)
                    continue
                row.update(in_pool=True, roles="/".join(sorted(roles)), role_match=bool(roles & set(needed)),
                           affordable=affordable(p["player_id"]))
                # posição relativa (0 = topo, 1 = fim) nos perfis pedidos × nos outros perfis da função
                need_pct, other_pct, best = [], [], None
                for (role, prof) in PROFILES:
                    if role not in roles:
                        continue
                    lst = ranked(role, prof)
                    r = _rank_of(lst, p["player_id"])
                    if r is None:
                        continue
                    rel = (r - 1) / max(1, len(lst) - 1)
                    if prof in needed.get(role, {}):
                        need_pct.append(rel)
                        best = r if best is None else min(best, r)
                    else:
                        other_pct.append(rel)
                if need_pct:
                    row.update(best_rank=best, pct_needed=round(mean(need_pct), 3))
                if other_pct:
                    row["pct_other"] = round(mean(other_pct), 3)
                for n in tops:
                    row[f"hit{n}"] = best is not None and best <= n
                rows.append(row)

    ev = [r for r in rows if r["in_pool"]]
    prof = [r for r in ev if r["pct_needed"] != "" and r["pct_other"] != ""]  # tem os dois lados pra comparar
    summary = {
        "signings": len(rows), "in_pool": len(ev),
        "role_match": mean(r["role_match"] for r in ev) if ev else 0, "role_base": mean(r["base_role"] for r in ev) if ev else 0,
        **{f"hit{n}": mean(r[f"hit{n}"] for r in ev) if ev else 0 for n in tops},
        **{f"hit{n}_base": mean(r[f"base_top{n}"] for r in ev) if ev else 0 for n in tops},
        "profile_n": len(prof),
        "pct_needed": mean(r["pct_needed"] for r in prof) if prof else 0,
        "pct_other": mean(r["pct_other"] for r in prof) if prof else 0,
        "affordable": mean(r["affordable"] for r in ev) if ev else 0,
    }
    return rows, summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Valida as recomendações contra as contratações reais do verão seguinte")
    ap.add_argument("year", help="ex.: 2015-16 (usa todas as ligas com CSV dessa temporada)")
    ap.add_argument("--target", default="1-4")
    ap.add_argument("--max-gap", type=float, default=-0.5)
    ap.add_argument("--strength", type=float, default=STRENGTH_WEIGHT)
    ap.add_argument("--mode", choices=("tier", "relative"), default="tier")
    ap.add_argument("--top-k", type=int, help="usar só as K maiores deficiências")
    ap.add_argument("--leagues", help="avaliar só os times destas ligas, ex.: premier-league,serie-a")
    ap.add_argument("--budget", action="store_true", help="filtrar pelo orçamento histórico do clube")
    args = ap.parse_args()
    lo, hi = map(int, args.target.split("-"))
    leagues = set(args.leagues.split(",")) if args.leagues else None
    rows, s = evaluate(args.year, (lo, hi), args.max_gap, args.strength, mode=args.mode, top_k=args.top_k, leagues=leagues, budget=args.budget)
    path = OUT.format(year=args.year)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"\n{s['signings']} contratações de verão; {s['in_pool']} de jogadores avaliáveis (≥{MIN_MINUTES} min nas ligas carregadas)")
    print(f"posição pedida pelo método: {s['role_match']:.0%}   (acaso: {s['role_base']:.0%})")
    for n in (10, 30):
        print(f"no top {n} de um perfil pedido: {s[f'hit{n}']:.0%}   (acaso: {s[f'hit{n}_base']:.0%})")
    print(f"posição relativa nos perfis pedidos: {s['pct_needed']:.2f} × nos outros perfis da função: {s['pct_other']:.2f}"
          f"   (0 = topo; n={s['profile_n']})")
    if args.budget:
        print(f"contratações dentro do teto do orçamento: {s['affordable']:.0%}")
    print(f"detalhe → {path}")


if __name__ == "__main__":
    main()
