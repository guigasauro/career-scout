"""Pivô analytics — passo 2: deficiências de um time na temporada.

Cada métrica do time vira valor por jogo, percentil na liga e distância (em desvios-padrão
da liga) até a média do patamar-alvo — por padrão o top 4, não só o campeão, que tem outro
estilo e outro orçamento.
"""
import argparse
import csv
from dataclasses import dataclass
from pathlib import Path

OUT_DIR = Path("data/processed")


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    better: int          # +1 = maior é melhor; −1 = menor é melhor (números "contra")
    lines: tuple[str, ...]  # linhas que mais influenciam a métrica (deficiência → posição)
    group: str = ""      # attack / creation / defense — só agrupa a tabela na tela


def _per_match(t: dict, k: str) -> float:
    return float(t[k]) / float(t["matches"])


def _padj(t: dict, k: str) -> float:
    # ações defensivas ajustadas pela posse: escala para 50% de posse do adversário
    # (time que fica sem a bola defende mais só por isso)
    opp_poss = 1 - float(t["passes_share"])
    return _per_match(t, k) * 0.5 / opp_poss if opp_poss else 0.0


METRICS: list[tuple[Metric, callable]] = [
    (Metric("npxg", "xG sem pênaltis", +1, ("ATT", "MID"), "attack"), lambda t: _per_match(t, "npxg")),
    (Metric("shots", "Chutes", +1, ("ATT",), "attack"), lambda t: _per_match(t, "shots")),
    (Metric("xg_per_shot", "xG por chute (qualidade da chance)", +1, ("ATT", "MID"), "attack"),
     lambda t: float(t["npxg"]) / float(t["shots"]) if float(t["shots"]) else 0.0),
    (Metric("xa", "xA (chances criadas)", +1, ("MID", "ATT"), "creation"), lambda t: _per_match(t, "xa")),
    (Metric("passes_into_box", "Passes para a área", +1, ("MID", "ATT", "DEF"), "creation"), lambda t: _per_match(t, "passes_into_box")),
    (Metric("progressive_passes", "Passes progressivos", +1, ("MID", "DEF"), "creation"), lambda t: _per_match(t, "progressive_passes")),
    (Metric("pass_pct", "Passes certos (%)", +1, ("MID", "DEF"), "creation"),
     lambda t: 100 * float(t["passes_completed"]) / float(t["passes"]) if float(t["passes"]) else 0.0),
    (Metric("dribbles_completed", "Dribles certos", +1, ("ATT",), "attack"), lambda t: _per_match(t, "dribbles_completed")),
    (Metric("possession", "Posse (fatia dos passes, %)", +1, ("MID",), "creation"), lambda t: 100 * float(t["passes_share"])),
    (Metric("npxg_against", "xG sofrido sem pênaltis", -1, ("DEF", "MID", "GK"), "defense"), lambda t: _per_match(t, "npxg_against")),
    (Metric("shots_against", "Chutes sofridos", -1, ("DEF", "MID"), "defense"), lambda t: _per_match(t, "shots_against")),
    (Metric("box_entries_against", "Passes do adversário para a área", -1, ("DEF",), "defense"), lambda t: _per_match(t, "passes_into_box_against")),
    (Metric("prog_against", "Passes progressivos do adversário", -1, ("MID", "ATT"), "defense"), lambda t: _per_match(t, "progressive_passes_against")),
    (Metric("padj_pressures", "Pressões (ajust. posse)", +1, ("MID", "ATT"), "defense"), lambda t: _padj(t, "pressures")),
    (Metric("padj_tackles_int", "Desarmes + interceptações (ajust. posse)", +1, ("DEF", "MID"), "defense"),
     lambda t: _padj(t, "tackles_won") + _padj(t, "interceptions")),
    (Metric("aerials_won", "Duelos aéreos ganhos", +1, ("DEF", "ATT"), "defense"), lambda t: _per_match(t, "aerials_won")),
]


def load_teams(season: str) -> list[dict]:
    with open(OUT_DIR / f"sb_{season}_teams.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def deficiencies(teams: list[dict], team: str, target: tuple[int, int] = (1, 4)) -> list[dict]:
    """Uma linha por métrica, da maior deficiência para a maior força.

    `gap` = (time − média do patamar-alvo) / desvio da liga, com sinal de "melhor":
    negativo = o time está abaixo do alvo naquilo. `pct` = percentil na liga (100 = melhor).
    """
    me = next(t for t in teams if t["team"] == team)
    tier = [t for t in teams if target[0] <= int(t["rank"]) <= target[1]]
    rows = []
    for m, fn in METRICS:
        vals = [fn(t) for t in teams]
        mine, tier_mean = fn(me), sum(fn(t) for t in tier) / len(tier)
        mean = sum(vals) / len(vals)
        std = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5 or 1.0
        # percentil: fração da liga que o time supera no sentido de "melhor"
        beats = sum(1 for v in vals if (mine - v) * m.better > 0)
        rows.append({
            "metric": m.key, "label": m.label, "lines": m.lines, "better": m.better, "group": m.group,
            "value": mine, "target": tier_mean, "league_mean": mean,
            "pct": round(100 * beats / (len(vals) - 1)),
            "gap": round((mine - tier_mean) * m.better / std, 2),
        })
    return sorted(rows, key=lambda r: r["gap"])


def main() -> None:
    ap = argparse.ArgumentParser(description="Deficiências de um time na temporada (StatsBomb Open Data)")
    ap.add_argument("season")
    ap.add_argument("team")
    ap.add_argument("--target", default="1-4", help="faixa da tabela usada como patamar-alvo (ex.: 1-4, 5-7)")
    args = ap.parse_args()
    lo, hi = map(int, args.target.split("-"))
    teams = load_teams(args.season)
    me = next(t for t in teams if t["team"] == args.team)
    print(f"{args.team}: {me['rank']}º, {me['points']} pts — alvo: {lo}º–{hi}º\n")
    print(f"{'métrica':42} {'time':>7} {'alvo':>7} {'pct':>4} {'gap':>6}  linhas")
    for r in deficiencies(teams, args.team, (lo, hi)):
        print(f"{r['label']:42} {r['value']:7.2f} {r['target']:7.2f} {r['pct']:4d} {r['gap']:+6.2f}  {'/'.join(r['lines'])}")


if __name__ == "__main__":
    main()
