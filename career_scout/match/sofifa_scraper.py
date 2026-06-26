"""Scraper do SoFIFA — lista versões disponíveis e baixa jogadores por versão."""
import csv
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = "https://sofifa.com"
PAGE_SIZE = 60


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://sofifa.com/",
    })
    # força inglês antes de qualquer request — posições e nomes ficam em inglês
    s.get(f"{BASE}/?hl=en-US", timeout=20)
    return s


# --- I/O com cache -----------------------------------------------------------

def _fetch(session: requests.Session, url: str, cache: Path, delay: float = 1.5) -> str:
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    time.sleep(delay)
    resp = session.get(url, timeout=20)
    resp.raise_for_status()
    cache.write_text(resp.text, encoding="utf-8")
    return resp.text


# --- Versões -----------------------------------------------------------------

def _extract_r(value: str) -> str | None:
    m = re.search(r"[?&]r=(\d{6})", value)
    return m.group(1) if m else None


def _parse_select(soup: BeautifulSoup, name: str) -> list[tuple[str, str]]:
    sel = soup.find("select", {"name": name})
    if not sel:
        return []
    return [
        (r, opt.get_text(strip=True))
        for opt in sel.find_all("option")
        if (r := _extract_r(opt.get("value", "")))
    ]


def fetch_editions(session: requests.Session, data_dir: Path) -> list[tuple[str, str]]:
    html = _fetch(session, f"{BASE}/players", data_dir / "raw" / "sofifa_index.html", delay=1.0)
    return _parse_select(BeautifulSoup(html, "lxml"), "version")


def fetch_rosters(session: requests.Session, edition_r: str, data_dir: Path) -> list[tuple[str, str]]:
    url = f"{BASE}/players?r={edition_r}&set=true"
    cache = data_dir / "raw" / f"sofifa_edition_{edition_r}.html"
    html = _fetch(session, url, cache, delay=1.0)
    return _parse_select(BeautifulSoup(html, "lxml"), "roster")


# --- Parser de página --------------------------------------------------------

def _parse_value(text: str) -> float | None:
    """'€90.5M' → 90_500_000.0 | '€500K' → 500_000.0"""
    text = text.replace("€", "").replace(",", "").strip()
    m = re.match(r"^([\d.]+)([MK]?)$", text)
    if not m:
        return None
    n = float(m.group(1))
    return n * 1_000_000 if m.group(2) == "M" else n * 1_000 if m.group(2) == "K" else n


def _parse_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    if not table or not table.find("tbody"):
        return []

    rows = []
    for tr in table.find("tbody").find_all("tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 7:
            continue

        # td[1]: nome, posições (em inglês com hl=en-US), nacionalidade
        td1 = tds[1]
        player_a = td1.find("a", href=re.compile(r"^/player/\d+"))
        if not player_a:
            continue
        parts = player_a["href"].split("/")
        sofifa_id = parts[2] if len(parts) > 2 else ""
        short_name = player_a.get_text(strip=True)

        pos_spans = td1.find_all("span", class_=re.compile(r"\bpos\b"))
        positions = ",".join(s.get_text(strip=True) for s in pos_spans)

        # primeira flag = nacionalidade principal
        nat_img = td1.find("img", class_="flag")
        nationality = (nat_img.get("title") or "") if nat_img else ""

        # td[2]: age | td[3]: overall | td[4]: potential
        age_text = tds[2].get_text(strip=True)
        age = int(age_text) if age_text.isdigit() else None
        ovr = tds[3].get_text(strip=True)
        overall = int(ovr) if ovr.isdigit() else 0
        pot = tds[4].get_text(strip=True)
        potential = int(pot) if pot.isdigit() else 0

        # td[5]: clube (liga não aparece na listagem)
        club_a = tds[5].find("a", href=re.compile(r"^/team/"))
        club_name = club_a.get_text(strip=True) if club_a else ""

        # td[6]: valor de mercado
        value_eur = _parse_value(tds[6].get_text(strip=True))

        rows.append({
            "sofifa_id":        sofifa_id,
            "short_name":       short_name,
            "player_positions": positions,
            "nationality_name": nationality,
            "age":              age,
            "overall":          overall,
            "potential":        potential,
            "club_name":        club_name,
            "league_name":      "",   # não disponível na listagem
            "value_eur":        value_eur,
        })
    return rows


# --- Lookups (posição pn= e nacionalidade na=) --------------------------------

# extraído dos HTMLs cacheados; atualizar se o sofifa mudar
POS_TO_PN: dict[str, int] = {
    "GK": 0, "RWB": 2, "RB": 3, "CB": 5, "LB": 7, "LWB": 8,
    "CDM": 10, "RM": 12, "CM": 14, "LM": 16, "CAM": 18,
    "CF": 21, "RW": 23, "ST": 25, "LW": 27,
}


def load_nat_map(data_dir: Path) -> dict[str, int]:
    """Carrega mapa nome→na_code do JSON gerado pelo scrape completo."""
    import json
    p = data_dir / "raw" / "sofifa_lookups.json"
    if not p.exists():
        return {}
    return json.load(open(p))["nationality"]


# --- Scraping paginado — modo COMPLETO ----------------------------------------

def _paginate(
    session: requests.Session,
    base_params: dict,
    r_key: str,
    cache_prefix: str,
    data_dir: Path,
    delay: float,
) -> list[dict]:
    """Paginação genérica; cache_prefix identifica o conjunto de params."""
    players: list[dict] = []
    offset = 0
    while True:
        params = {**base_params, "offset": offset}
        cache  = data_dir / "raw" / f"sofifa_{cache_prefix}_{offset:06d}.html"
        url    = f"{BASE}/players"
        html   = _fetch(session, url + "?" + "&".join(f"{k}={v}" for k, v in params.items()), cache, delay)
        page   = _parse_page(html)
        if not page:
            break
        players.extend(page)
        print(f"  offset={offset:5d}: +{len(page)} ({len(players)} total)")
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return players


def scrape_players(
    session: requests.Session,
    r_key: str,
    data_dir: Path,
    delay: float = 1.5,
) -> list[dict]:
    """Modo COMPLETO — baixa todos os jogadores da versão (cache por offset)."""
    session.get(f"{BASE}/players?r={r_key}&set=true", timeout=20)
    return _paginate(session, {"r": r_key}, r_key, r_key, data_dir, delay)


# --- Scraping por perfil — modo RÁPIDO ----------------------------------------

def scrape_by_profile(
    session: requests.Session,
    position_norm: str,
    r_key: str,
    data_dir: Path,
    age_mean: float | None = None,
    nat_code: int | None = None,
    fee_mean: float | None = None,
    age_window: int = 5,
    value_mult: float = 1.6,  # ponytail: fee TM ≈ 1.6× value_eur SoFIFA; ajustar se necessário
    delay: float = 1.5,
) -> list[dict]:
    """Modo RÁPIDO — query filtrada por posição + idade (+ valor máximo se disponível)."""
    pn = POS_TO_PN.get(position_norm)
    if pn is None:
        return []

    session.get(f"{BASE}/players?r={r_key}&set=true", timeout=20)

    params: dict = {"r": r_key, "pn": pn}

    if age_mean:
        params["ael"] = max(15, int(age_mean) - age_window)
        params["aeh"] = int(age_mean) + age_window

    # vlh = valor máximo em € (sem escala); fee_mean do TM ≈ prémio sobre valor de mercado
    if fee_mean:
        params["vlh"] = int(fee_mean * value_mult)

    # na[] = filtro de nacionalidade (opcional — amplia pool se omitido)
    if nat_code is not None:
        params["na[]"] = nat_code

    # cache_prefix codifica os parâmetros de forma compacta
    pn_str  = f"pn{pn}"
    age_str = f"a{params.get('ael',0)}-{params.get('aeh',99)}"
    nat_str = f"na{nat_code}" if nat_code is not None else "naALL"
    val_str = f"vl{int(fee_mean/1e6) if fee_mean else 0}M"
    prefix  = f"{r_key}_{pn_str}_{age_str}_{nat_str}_{val_str}"

    print(f"  params: pn={pn} age={params.get('ael')}-{params.get('aeh')} "
          f"vlh={params.get('vlh') and params['vlh']//1_000_000}M nat_code={nat_code}")

    return _paginate(session, params, r_key, prefix, data_dir, delay)


def save_csv(players: list[dict], path: Path) -> None:
    if not players:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(players[0].keys()))
        w.writeheader()
        w.writerows(players)


# --- CLI ---------------------------------------------------------------------

if __name__ == "__main__":
    import argparse, csv as _csv

    parser = argparse.ArgumentParser(description="Scraper SoFIFA")
    parser.add_argument("--fast", action="store_true",
                        help="Modo rápido: filtra por perfil em vez de baixar tudo")
    parser.add_argument("--profiles", default="data/processed/profiles.csv",
                        help="CSV de perfis (necessário para --fast)")
    args = parser.parse_args()

    data_dir = Path(__file__).parent.parent.parent / "data"
    session  = _make_session()

    # seleção de edição + roster (comum a ambos os modos)
    print("Buscando edições disponíveis no SoFIFA...")
    editions = fetch_editions(session, data_dir)
    if not editions:
        print("Não encontrou edições. Apague: data/raw/sofifa_index.html")
        sys.exit(1)

    print()
    for i, (k, label) in enumerate(editions):
        print(f"  [{i:2d}] {label}  (r={k})")
    choice = input("\nEdição (Enter = 0): ").strip()
    edition_r, edition_label = editions[int(choice) if choice.isdigit() else 0]

    print(f"\nBuscando updates de {edition_label}...")
    rosters = fetch_rosters(session, edition_r, data_dir)
    print()
    for i, (k, date) in enumerate(rosters):
        print(f"  [{i:2d}] {date}  (r={k})")
    choice = input("\nUpdate (Enter = 0 = mais recente): ").strip()
    r_key, date_label = rosters[int(choice) if choice.isdigit() else 0]

    print(f"\nVersão: {edition_label} — {date_label}  (r={r_key})")

    if not args.fast:
        # --- MODO COMPLETO ---
        out_csv = data_dir / "processed" / f"sofifa_{r_key}.csv"
        if out_csv.exists():
            print(f"Já existe: {out_csv} — apague para refazer.")
            sys.exit(0)
        print(f"\n[COMPLETO] baixando todos os jogadores...\n")
        players = scrape_players(session, r_key, data_dir)
        save_csv(players, out_csv)
        print(f"\n{len(players)} jogadores → {out_csv}")

    else:
        # --- MODO RÁPIDO ---
        from career_scout.models import PositionProfile

        profiles_path = Path(args.profiles)
        if not profiles_path.exists():
            print(f"Perfis não encontrados: {profiles_path}")
            sys.exit(1)

        profiles: list[PositionProfile] = []
        with open(profiles_path, newline="", encoding="utf-8") as f:
            for row in _csv.DictReader(f):
                profiles.append(PositionProfile(
                    position_norm=row["position_norm"],
                    n=int(row["n"]),
                    n_permanent=int(row["n_permanent"]),
                    age_mean=float(row["age_mean"]) if row["age_mean"] else None,
                    fee_mean=float(row["fee_mean"]) if row["fee_mean"] else None,
                    nationality_mode=row["nationality_mode"] or None,
                    from_league_mode=row["from_league_mode"] or None,
                    from_club_mode=row["from_club_mode"] or None,
                    is_most_frequent=row["is_most_frequent"] == "True",
                ))

        nat_map = load_nat_map(data_dir)
        all_players: list[dict] = []

        print(f"\n[RÁPIDO] {len(profiles)} perfis × query filtrada\n")
        for profile in profiles:
            if not profile.age_mean:
                continue
            nat_code = nat_map.get(profile.nationality_mode) if profile.nationality_mode else None
            print(f"→ {profile.position_norm}")
            players = scrape_by_profile(
                session, profile.position_norm, r_key, data_dir,
                age_mean=profile.age_mean,
                nat_code=None,           # ponytail: sem filtro hard de nac — mantém pool amplo
                fee_mean=profile.fee_mean,
            )
            all_players.extend(players)

        # deduplica por sofifa_id (mesmo jogador pode aparecer em múltiplos perfis)
        seen: set[str] = set()
        unique = [p for p in all_players if not (p["sofifa_id"] in seen or seen.add(p["sofifa_id"]))]  # type: ignore[func-returns-value]

        out_csv = data_dir / "processed" / f"sofifa_{r_key}_fast.csv"
        save_csv(unique, out_csv)
        print(f"\n{len(unique)} jogadores únicos → {out_csv}")
