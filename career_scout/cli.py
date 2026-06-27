"""CLI principal — career-scout."""
import argparse
import csv
from dataclasses import asdict
from pathlib import Path

from career_scout.extract.transfermarkt import get_arrivals
from career_scout.models import Transfer


def save_transfers(transfers: list[Transfer], out: Path) -> None:
    rows = [asdict(t) for t in transfers]
    if not rows:
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)


def seasons_for(fifa_edition: int, history: int) -> list[int]:
    """Janela de temporadas para uma edição FIFA. Espelha api.py (D5)."""
    season_ceil = 2000 + fifa_edition - 1
    return list(range(season_ceil - history + 1, season_ceil + 1))


def cmd_extract(args: argparse.Namespace) -> None:
    seasons = seasons_for(args.fifa_edition, args.history)
    print(f"Coletando {args.club_name} | temporadas {seasons[0]}–{seasons[-1]}...")

    transfers = get_arrivals(
        club_slug=args.club_slug,
        club_id=args.club_id,
        club_name=args.club_name,
        seasons=seasons,
    )

    out = Path(args.output)
    save_transfers(transfers, out)
    print(f"{len(transfers)} chegadas salvas em {out}")
    cols = ["season", "player_name", "position_norm", "age", "nationality", "transfer_type", "fee"]
    print("  ".join(cols))
    for t in transfers:
        d = asdict(t)
        print("  ".join(str(d.get(c, "")) for c in cols))


def main() -> None:
    parser = argparse.ArgumentParser(prog="career-scout")
    sub = parser.add_subparsers(dest="cmd", required=True)

    ext = sub.add_parser("extract", help="Estágio 1 — extrair chegadas do Transfermarkt")
    ext.add_argument("--club-slug",  default="paris-saint-germain")
    ext.add_argument("--club-id",    type=int, default=583)
    ext.add_argument("--club-name",  default="PSG")
    ext.add_argument("--fifa-edition", type=int, default=22,
                     help="Edição FIFA (22 = FIFA 22). Teto = 2000 + edição - 1.")
    ext.add_argument("--history",    type=int, default=5,
                     help="Quantos anos de histórico (D5)")
    ext.add_argument("--output",     default="data/processed/arrivals.csv")
    ext.set_defaults(func=cmd_extract)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
