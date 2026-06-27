"""Estágio 2 — perfilagem estatística das chegadas por posição."""
import csv
import logging
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from statistics import mean
from typing import Optional

from career_scout.models import PositionProfile, Transfer
from career_scout.normalize.positions import POS_TO_LINE

logger = logging.getLogger(__name__)


def _mode(values: list[str], min_support: int = 2) -> Optional[str]:
    """Moda com suporte mínimo; None se nenhum valor atinge o limiar."""
    if not values:
        return None
    top, count = Counter(values).most_common(1)[0]
    return top if count >= min_support else None


def build_profiles(
    transfers: list[Transfer],
    min_sample: int = 3,
    min_support: int = 2,
) -> list[PositionProfile]:
    """Agrupa chegadas por posição e calcula perfil estatístico."""
    by_pos: dict[str, list[Transfer]] = {}
    unmapped = 0
    for t in transfers:
        pos = t.position_norm
        if pos is None:
            unmapped += 1
            continue
        by_pos.setdefault(pos, []).append(t)
    if unmapped:
        logger.warning(
            "build_profiles: %d chegada(s) com posição não mapeada descartada(s)",
            unmapped,
        )

    # fallback: posições com amostra pequena somam-se à linha
    for pos, group in list(by_pos.items()):
        if len(group) < min_sample:
            line = POS_TO_LINE.get(pos)
            if line and line != pos:
                by_pos.setdefault(line, []).extend(group)

    profiles: list[PositionProfile] = []
    for pos, group in by_pos.items():
        if len(group) < min_sample:
            continue

        permanent = [t for t in group if t.transfer_type in ("permanent", "free")]
        fees = [t.fee for t in permanent if t.fee is not None]
        ages = [t.age for t in group if t.age is not None]

        profiles.append(PositionProfile(
            position_norm=pos,
            n=len(group),
            n_permanent=len(permanent),
            age_mean=round(mean(ages), 1) if ages else None,
            fee_mean=round(mean(fees)) if fees else None,
            nationality_mode=_mode([t.nationality for t in group if t.nationality], min_support),
            from_league_mode=_mode([t.from_league for t in group if t.from_league], min_support),
            from_club_mode=_mode([t.from_club for t in group if t.from_club], min_support),
        ))

    if profiles:
        most_freq = max(profiles, key=lambda p: p.n_permanent)
        most_freq.is_most_frequent = True

    return sorted(profiles, key=lambda p: -p.n)


def load_transfers(csv_path: Path) -> list[Transfer]:
    transfers = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            transfers.append(Transfer(
                club_name=row["club_name"],
                season=int(row["season"]),
                window=row["window"],
                player_name=row["player_name"],
                player_url=row["player_url"],
                position_raw=row["position_raw"],
                position_norm=row["position_norm"] or None,
                age=int(row["age"]) if row["age"] else None,
                nationality=row["nationality"] or None,
                from_club=row["from_club"] or None,
                from_league=row["from_league"] or None,
                transfer_type=row["transfer_type"],
                fee=float(row["fee"]) if row["fee"] else None,
            ))
    return transfers


def save_profiles(profiles: list[PositionProfile], csv_path: Path) -> None:
    if not profiles:
        return
    fields = list(asdict(profiles[0]).keys())
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(asdict(p) for p in profiles)


if __name__ == "__main__":
    # ponytail: self-check rápido com os dados reais do PSG
    base = Path(__file__).parent.parent.parent / "data"
    transfers = load_transfers(base / "processed" / "arrivals.csv")
    profiles = build_profiles(transfers)
    for p in profiles:
        flag = " ★" if p.is_most_frequent else ""
        fee_str = f"{p.fee_mean/1e6:.1f}M" if p.fee_mean else "-"
        print(f"{p.position_norm:4s} n={p.n:2d}  idade={p.age_mean}  fee={fee_str}  "
              f"nac={p.nationality_mode}  liga={p.from_league_mode}{flag}")
    out = base / "processed" / "profiles.csv"
    save_profiles(profiles, out)
    print(f"\nSalvo em {out}")
