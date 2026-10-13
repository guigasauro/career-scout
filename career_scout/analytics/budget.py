"""Pivô analytics — orçamento do clube pelo histórico de valores pagos (Transfermarkt).

Liga os dois módulos: o histórico de contratações que o modo FIFA raspa vira o teto de preço
das recomendações. Só usa temporadas até a analisada (2015/16 → janelas 2013/14 a 2015/16):
nada do verão seguinte, que é o que a validação tenta prever.
"""
import csv
import math
import re
from pathlib import Path

from career_scout.analytics.deficiencies import load_teams
from career_scout.analytics.market import TEAM_ALIASES, club_index
from career_scout.extract.transfermarkt import get_arrivals
from seed_clubs import norm_name

OUT_DIR = Path("data/processed")
HISTORY = 3            # temporadas de histórico
BUDGET_PCT = 0.9       # orçamento = percentil 90 dos valores pagos (a compra cara "normal", não o recorde)
MARGIN = 1.25          # folga sobre o orçamento: o clube às vezes estica
MIN_FEES = 3           # menos que isso: usa o maior valor pago


def percentile(xs: list[float], q: float) -> float:
    """Percentil por posição mais próxima (sem interpolar): sempre um valor que de fato foi pago."""
    s = sorted(xs)
    return s[max(0, math.ceil(q * len(s)) - 1)]


def club_budget(fees: list[float]) -> float | None:
    """Valores pagos (compras definitivas com valor > 0) → orçamento; None sem nenhuma compra paga."""
    if not fees:
        return None
    return percentile(fees, BUDGET_PCT) if len(fees) >= MIN_FEES else max(fees)


def load_budgets(season: str) -> dict[str, dict]:
    """Orçamentos já calculados (CSV); {} se ainda não foram — nunca raspa (seguro para a API)."""
    path = OUT_DIR / f"sb_{season}_budget.csv"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return {r["team"]: {"budget": float(r["budget"]) if r["budget"] else None,
                            "cap": float(r["cap"]) if r["cap"] else None, "n_fees": int(r["n_fees"])}
                for r in csv.DictReader(f)}


def season_budgets(season: str) -> dict[str, dict]:
    """Time → {budget, cap, n_fees}; calcula pelo TM e grava data/processed/sb_{season}_budget.csv."""
    if cached := load_budgets(season):
        return cached
    path = OUT_DIR / f"sb_{season}_budget.csv"
    start = int(re.search(r"(\d{4})-\d{2}$", season)[1])
    clubs = club_index()
    out = {}
    for t in load_teams(season):
        club = clubs.get(norm_name(TEAM_ALIASES.get(t["team"], t["team"])))
        if club is None:
            continue
        arrivals = get_arrivals(club[0], club[1], t["team"], list(range(start - HISTORY + 1, start + 1)))
        fees = [a.fee for a in arrivals if a.transfer_type == "permanent" and a.fee]
        b = club_budget(fees)
        out[t["team"]] = {"budget": b, "cap": b * MARGIN if b else None, "n_fees": len(fees)}
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["team", "budget", "cap", "n_fees"])
        for team, v in out.items():
            w.writerow([team, v["budget"] or "", v["cap"] or "", v["n_fees"]])
    return out
