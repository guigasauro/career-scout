"""CLI principal — career-scout."""
import argparse
import sys
from pathlib import Path

import pandas as pd

from career_scout.extract.transfermarkt import get_arrivals
from career_scout.models import Transfer


def transfers_to_df(transfers: list[Transfer]) -> pd.DataFrame:
    return pd.DataFrame([t.__dict__ for t in transfers])


def cmd_extract(args: argparse.Namespace) -> None:
    seasons = list(range(args.fifa_year - args.history, args.fifa_year + 1))
    print(f"Coletando {args.club_name} | temporadas {seasons[0]}–{seasons[-1]}...")

    transfers = get_arrivals(
        club_slug=args.club_slug,
        club_id=args.club_id,
        club_name=args.club_name,
        seasons=seasons,
    )

    df = transfers_to_df(transfers)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"{len(df)} chegadas salvas em {out}")
    print(df[["season", "player_name", "position_norm", "age", "nationality", "transfer_type", "fee"]].to_string(index=False))


def main() -> None:
    parser = argparse.ArgumentParser(prog="career-scout")
    sub = parser.add_subparsers(dest="cmd", required=True)

    ext = sub.add_parser("extract", help="Estágio 1 — extrair chegadas do Transfermarkt")
    ext.add_argument("--club-slug",  default="paris-saint-germain")
    ext.add_argument("--club-id",    type=int, default=583)
    ext.add_argument("--club-name",  default="PSG")
    ext.add_argument("--fifa-year",  type=int, default=2021,
                     help="Ano do FIFA (teto das temporadas; FIFA 22 = 2021)")
    ext.add_argument("--history",    type=int, default=7,
                     help="Quantos anos de histórico (D5)")
    ext.add_argument("--output",     default="data/processed/arrivals.csv")
    ext.set_defaults(func=cmd_extract)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
