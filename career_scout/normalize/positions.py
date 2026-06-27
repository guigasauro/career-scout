# Mapa TM (inglês, mirror .com) → FIFA/SoFIFA
TM_TO_FIFA: dict[str, str] = {
    "Goalkeeper":          "GK",
    "Centre-Back":         "CB",
    "Left-Back":           "LB",
    "Right-Back":          "RB",
    "Defensive Midfield":  "CDM",
    "Central Midfield":    "CM",
    "Attacking Midfield":  "CAM",
    "Left Midfield":       "LM",
    "Right Midfield":      "RM",
    "Left Winger":         "LW",
    "Right Winger":        "RW",
    "Second Striker":      "CF",
    "Centre-Forward":      "ST",
    # rótulos genéricos do TM → códigos de linha (já tratados como fallback)
    "Defender":            "DEF",
    "Sweeper":             "DEF",
    "Midfield":            "MID",
    "midfielder":          "MID",
    "Forward":             "ATT",
    "Striker":             "ATT",
}

# fallback: posição fina → linha
POS_TO_LINE: dict[str, str] = {
    "GK":  "GK",
    "CB":  "DEF", "LB": "DEF", "RB": "DEF",
    "CDM": "MID", "CM": "MID", "CAM": "MID", "LM": "MID", "RM": "MID",
    "LW":  "ATT", "RW": "ATT", "CF": "ATT", "ST": "ATT",
}


def normalize(position_raw: str) -> str | None:
    return TM_TO_FIFA.get(position_raw)


def to_line(position_norm: str) -> str | None:
    return POS_TO_LINE.get(position_norm)
