from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Transfer:
    club_name: str
    season: int          # ano de início da temporada (saison_id)
    window: str          # "Summer" | "Winter"
    player_name: str
    player_url: str
    position_raw: str
    position_norm: Optional[str]
    age: Optional[int]
    nationality: Optional[str]
    from_club: Optional[str]
    from_league: Optional[str]
    transfer_type: str              # "permanent" | "loan" | "free"
    fee: Optional[float]            # EUR; None = desconhecido, 0 = sem taxa (free/loan sem custo)


@dataclass
class PositionProfile:
    position_norm: str
    n: int                          # total de chegadas (permanent + loan + free)
    n_permanent: int                # só permanentes + free (base do fee_mean)
    age_mean: Optional[float]
    fee_mean: Optional[float]       # média da fee paga em contratações definitivas (EUR; livres fora)
    nationality_mode: Optional[str]
    from_league_mode: Optional[str]
    from_club_mode: Optional[str]
    is_most_frequent: bool = False  # posição com maior n_permanent
