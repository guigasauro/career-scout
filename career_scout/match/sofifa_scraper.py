"""Scraper do SoFIFA — lista versões disponíveis e baixa jogadores por versão.

sofifa.com passou a exigir passar por um desafio Cloudflare (Turnstile) que
nem requests puro nem browser automation (soccerdata/seleniumbase undetected)
conseguem resolver sozinhos neste projeto — testado ao vivo, os dois caem na
página "Performing security verification". Solução adotada: o dev resolve o
desafio uma vez num navegador normal e exporta os cookies da sessão (ver
`COOKIE_INSTRUCTIONS` abaixo); o scraper reusa esses cookies via requests.
Cookie expira (tipicamente horas) — precisa renovar manualmente de vez em
quando; ver `_looks_like_challenge`.
"""
import csv
import json
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from career_scout.match.sofifa import roster_csv

BASE = "https://sofifa.com"
PAGE_SIZE = 60

COOKIE_INSTRUCTIONS = """\
Cookies do SoFIFA ausentes ou expirados (data/raw/sofifa_cookies.json).

Como renovar:
  1. Abra https://sofifa.com/players num navegador normal e espere passar
     pela verificação Cloudflare.
  2. DevTools → Application/Storage → Cookies → sofifa.com. Copie pelo menos
     o valor de `cf_clearance` (e quaisquer outros cookies presentes).
  3. DevTools → Network → clique numa request → Headers → copie o
     `User-Agent` exato usado por esse navegador.
  4. Salve em data/raw/sofifa_cookies.json:
     {
       "cookies": {"cf_clearance": "...", "outro_cookie": "..."},
       "user_agent": "Mozilla/5.0 ..."
     }
"""


def _load_cookie_file(data_dir: Path) -> dict:
    p = data_dir / "raw" / "sofifa_cookies.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def _make_session(data_dir: Path) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://sofifa.com/",
    })
    auth = _load_cookie_file(data_dir)
    if auth.get("user_agent"):
        s.headers["User-Agent"] = auth["user_agent"]
    if auth.get("cookies"):
        s.cookies.update(auth["cookies"])
    # força inglês antes de qualquer request — posições e nomes ficam em inglês.
    # best-effort: se o cookie estiver ruim, quem detecta e explica é o _fetch
    # da primeira request de verdade, não vale duplicar a checagem aqui.
    try:
        s.get(f"{BASE}/?hl=en-US", timeout=20)
    except requests.RequestException:
        pass
    return s


# --- I/O com cache -----------------------------------------------------------

def _looks_like_challenge(html: str) -> bool:
    """Detecta a página de verificação Cloudflare (cookie ausente/expirado)."""
    return "cf-chl-widget" in html or "Performing security verification" in html or "<title>Just a moment...</title>" in html


def _fetch(session: requests.Session, url: str, cache: Path, delay: float = 1.5) -> str:
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    time.sleep(delay)
    for attempt in range(3):
        try:
            resp = session.get(url, timeout=20)
            # desafio do Cloudflare vem com 403: avisa pra renovar o cookie em vez de um HTTPError genérico
            if _looks_like_challenge(resp.text):
                raise RuntimeError(COOKIE_INSTRUCTIONS)
            resp.raise_for_status()
            break
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(delay * (attempt + 1))  # backoff simples: timeout de rede é transitório
    cache.write_text(resp.text, encoding="utf-8")
    return resp.text


# --- Versões -----------------------------------------------------------------

def _extract_r(value: str) -> str | None:
    m = re.search(r"[?&]r=(\d{6})", value)
    return m.group(1) if m else None


def edition_number(label: str) -> int | None:
    """'FIFA 23' → 23 | 'FC 24' → 24 | 'FC 26' → 26"""
    m = re.search(r"(\d+)", label)
    return int(m.group(1)) if m else None


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


# Lançamento mundial oficial (edição padrão). O elenco "de lançamento" é o último update
# com data ≤ esta: os primeiros updates de cada edição (XX0001, agosto) são dados de
# beta/revelação de ratings, e há elencos especiais sem data ("World Cup 2022", "UEFA Euro 2024").
RELEASE_DATES: dict[int, date] = {
    14: date(2013, 9, 24), 15: date(2014, 9, 23), 16: date(2015, 9, 22), 17: date(2016, 9, 27),
    18: date(2017, 9, 29), 19: date(2018, 9, 28), 20: date(2019, 9, 27), 21: date(2020, 10, 9),
    22: date(2021, 10, 1), 23: date(2022, 9, 30), 24: date(2023, 9, 29), 25: date(2024, 9, 27),
    26: date(2025, 9, 26), 27: date(2026, 9, 25),
}


def pick_update(rosters: list[tuple[str, str]], edition: int, roster: str) -> tuple[str, str]:
    """(r, data) do update certo: "latest" = mais recente; "launch" = vigente no lançamento."""
    dated = []
    for r, label in rosters:
        try:
            dated.append((datetime.strptime(label, "%b %d, %Y").date(), r, label))
        except ValueError:
            continue  # elenco especial de torneio, sem data
    if roster == "launch":
        if edition not in RELEASE_DATES:
            raise ValueError(f"Sem data de lançamento cadastrada para a edição {edition} (RELEASE_DATES).")
        dated = [d for d in dated if d[0] <= RELEASE_DATES[edition]]
    if not dated:
        raise ValueError(f"Nenhum update da edição {edition} serve para '{roster}'.")
    _, r, label = max(dated)
    return r, label


def fetch_rosters(session: requests.Session, edition_r: str, data_dir: Path) -> list[tuple[str, str]]:
    url = f"{BASE}/players?r={edition_r}&set=true"
    cache = data_dir / "raw" / f"sofifa_edition_{edition_r}.html"
    html = _fetch(session, url, cache, delay=1.0)
    return _parse_select(BeautifulSoup(html, "lxml"), "roster")


# --- Liga por clube (league_name não vem na listagem de players) -------------
#
# /api/league dá o catálogo (id, nome, país) — independente de edição.
# /teams?lg={id}&r={r_key} dá os clubes de uma liga numa edição específica.
# Cruzando os dois: club_name → league_name, pra preencher o que o scraper de
# listagem deixa em branco. Ver `enrich_league_names`.

# Ligas fora do catálogo atual do SoFIFA mas presentes em edições antigas (ids conferidos em /teams?lg=…&r=220069)
RETIRED_LEAGUES = [
    {"id": 349, "value": "J1 League", "nationName": "Japan"},
    {"id": 347, "value": "Premier Division", "nationName": "South Africa"},
]


def fetch_league_catalog(session: requests.Session, data_dir: Path) -> list[dict]:
    """[{'league_id': int, 'league_name': str, 'nation_name': str}, ...]"""
    cache = data_dir / "raw" / "sofifa_leagues.json"
    if cache.exists():
        raw = json.loads(cache.read_text(encoding="utf-8"))
    else:
        time.sleep(1.0)
        resp = session.get(f"{BASE}/api/league", timeout=20)
        resp.raise_for_status()
        raw = resp.json()
    # o catálogo é o atual: ligas que saíram do jogo somem dele, mas ainda existem nas edições antigas
    known = {c["id"] for g in raw["data"] for c in g["childs"]}
    missing = [c for c in RETIRED_LEAGUES if c["id"] not in known]
    if missing or not cache.exists():
        raw["data"][-1]["childs"].extend(missing)
        cache.write_text(json.dumps(raw), encoding="utf-8")
    return [
        {"league_id": c["id"], "league_name": c["value"], "nation_name": c.get("nationName", "")}
        for group in raw["data"]
        for c in group["childs"]
    ]


def _parse_teams_page(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    if not table or not table.find("tbody"):
        return []
    names = []
    for tr in table.find("tbody").find_all("tr"):
        a = tr.find("a", href=re.compile(r"^/team/\d+"))
        if a:
            names.append(a.get_text(strip=True))
    return names


_KAGGLE_PREFIX = {"England": "English", "Spain": "Spain", "France": "French",
                  "Germany": "German", "Italy": "Italian", "Netherlands": "Holland"}


def league_label(league_name: str, nation_name: str) -> str:
    """Nome de liga pra gravar no CSV. As 5 grandes ligas usam o alias Kaggle
    já existente em sofifa.py::_normalize_league — é o nome que CLUBS_DB (e
    portanto /clubs) espera, então casa com o clube sem precisar duplicar essa
    tabela. As outras ~47 ligas do catálogo SoFIFA não têm clube nenhum em
    CLUBS_DB mesmo (projeto cobre só as 5 grandes — ver CLAUDE.md), então só
    precisam ficar únicas pra /countries e /leagues navegarem: sufixo de país
    resolve ('Premier League' existe na Inglaterra E na Ucrânia, por exemplo)."""
    from career_scout.match.sofifa import _normalize_league
    kaggle_name = _normalize_league(league_name)
    # só aplica o alias no país certo: "Bundesliga" também é a da Áustria,
    # "Premier League" a da Ucrânia, "Serie A" a do Equador.
    if kaggle_name != league_name and kaggle_name.startswith(_KAGGLE_PREFIX.get(nation_name, "\0")):
        return kaggle_name
    return f"{league_name} ({nation_name})" if nation_name else league_name


def build_club_league_map(session: requests.Session, r_key: str, data_dir: Path) -> dict[str, str]:
    """club_name → league_label (desambiguado por país) pra uma edição."""
    club_to_league: dict[str, str] = {}
    for league in fetch_league_catalog(session, data_dir):
        lid = league["league_id"]
        cache = data_dir / "raw" / f"sofifa_teams_{lid}_{r_key}.html"
        url = f"{BASE}/teams?lg={lid}&r={r_key}&set=true"
        html = _fetch(session, url, cache, delay=1.0)
        label = league_label(league["league_name"], league["nation_name"])
        for team_name in _parse_teams_page(html):
            club_to_league[team_name] = label
    return club_to_league


def enrich_league_names(session: requests.Session, r_key: str, csv_path: Path, data_dir: Path) -> None:
    """Reabre o CSV já salvo e preenche league_name via clube→liga."""
    club_to_league = build_club_league_map(session, r_key, data_dir)
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    filled = 0
    for row in rows:
        league = club_to_league.get(row["club_name"])
        if league:
            row["league_name"] = league
            filled += 1
    save_csv(rows, csv_path)
    print(f"  league_name preenchido em {filled}/{len(rows)} jogadores "
          f"({len(club_to_league)} clubes mapeados em {len(fetch_league_catalog(session, data_dir))} ligas)")


# --- Parser de página --------------------------------------------------------

def _parse_value(text: str) -> float | None:
    """'€90.5M' → 90_500_000.0 | '€500K' → 500_000.0"""
    text = text.replace("€", "").replace(",", "").strip()
    m = re.match(r"^([\d.]+)([MK]?)$", text)
    if not m:
        return None
    n = float(m.group(1))
    return n * 1_000_000 if m.group(2) == "M" else n * 1_000 if m.group(2) == "K" else n


def _parse_page(html: str, r_key: str) -> tuple[list[dict], int]:
    """r_key: versão sendo raspada. Em offsets altos o SoFIFA reembaralha o pool
    (ver STALE_PAGE_LIMIT) e chega a intercalar linhas inteiras de OUTRA edição
    (ex.: Eden Hazard, aposentado, com o elenco do Real Madrid da FIFA 23) nas
    páginas da edição atual. O link do jogador termina em /{versão}/ — se não
    bate com r_key, a linha inteira é de outra edição: descartar, não só limpar
    o texto (o <em>NN</em> de squad number que gruda no nome é só o sintoma
    visível, não a causa).

    Retorna (linhas_da_edição_certa, total_de_linhas_na_página) — o total bruto
    é usado por `_paginate` pra saber se a página veio cheia (não pode ser o
    filtrado: uma página cheia de linhas contaminadas ficaria menor que
    PAGE_SIZE e pareceria a última página por engano)."""
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    if not table or not table.find("tbody"):
        return [], 0

    # a ordem Value/Wage muda entre edições (FC 26+ põe Wage antes): achar pelo cabeçalho
    heads = [th.get_text(strip=True) for th in table.find("thead").find_all("th")] if table.find("thead") else []
    value_col = heads.index("Value") if "Value" in heads else 6

    rows = []
    raw_count = 0
    for tr in table.find("tbody").find_all("tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) <= value_col:
            continue

        # td[1]: nome, posições (em inglês com hl=en-US), nacionalidade
        td1 = tds[1]
        player_a = td1.find("a", href=re.compile(r"^/player/\d+"))
        if not player_a:
            continue
        raw_count += 1
        parts = player_a["href"].rstrip("/").split("/")
        sofifa_id = parts[2] if len(parts) > 2 else ""
        href_version = parts[-1] if len(parts) > 3 else ""
        if href_version != r_key:
            continue
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

        value_eur = _parse_value(tds[value_col].get_text(strip=True))

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
    return rows, raw_count


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

# ponytail: sofifa.com não devolve página curta no fim — passado um certo offset
# (~24k testado ao vivo em FC26) ele reembaralha o mesmo pool de ~19k jogadores
# em vez de parar. Detecção real de fim: N páginas seguidas sem nenhum id novo.
STALE_PAGE_LIMIT = 5


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
    seen: set[str] = set()
    stale = 0
    offset = 0
    while True:
        params = {**base_params, "offset": offset}
        cache  = data_dir / "raw" / f"sofifa_{cache_prefix}_{offset:06d}.html"
        url    = f"{BASE}/players"
        html   = _fetch(session, url + "?" + "&".join(f"{k}={v}" for k, v in params.items()), cache, delay)
        page, raw_count = _parse_page(html, r_key)
        if raw_count == 0:
            break

        new_rows = [r for r in page if r["sofifa_id"] not in seen]
        for r in new_rows:
            seen.add(r["sofifa_id"])
        players.extend(new_rows)
        print(f"  offset={offset:6d}: +{len(new_rows)} novos ({len(players)} únicos totais)")

        stale = 0 if new_rows else stale + 1
        if stale >= STALE_PAGE_LIMIT:
            print(f"  {STALE_PAGE_LIMIT} páginas seguidas sem jogador novo — encerrando.")
            break
        if raw_count < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return players


def scrape_players(
    session: requests.Session,
    r_key: str,
    data_dir: Path,
    delay: float = 1.5,
) -> list[dict]:
    """Modo COMPLETO — baixa todos os jogadores da versão (cache por offset).

    `col=oa&sort=desc` (dev testou ao vivo e confirmou a contagem: 19.370
    jogadores distintos no FC 26) — sem ordenação explícita, `/players` pagina
    de forma instável e intercala linhas de edições antigas (ver `_parse_page`).
    """
    session.get(f"{BASE}/players?r={r_key}&set=true", timeout=20)
    return _paginate(session, {"r": r_key, "col": "oa", "sort": "desc"}, r_key, r_key, data_dir, delay)


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


def save_version(data_dir: Path, csv_path: Path, r_key: str, date_label: str) -> None:
    """Registra qual update do SoFIFA gerou o CSV (chave = nome sem extensão; mostrado no "Como funciona")."""
    p = data_dir / "raw" / "sofifa_versions.json"
    versions = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    versions[csv_path.stem] = {"r": r_key, "date": date_label}
    p.write_text(json.dumps(versions, indent=2), encoding="utf-8")


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
    parser.add_argument("--edition", type=int, default=None,
                        help="Edição não-interativa (ex.: 26 = FC 26). Usa sempre o update mais recente.")
    parser.add_argument("--enrich-league", action="store_true",
                        help="Só preenche league_name num players_{edition}.csv já existente (requer --edition).")
    parser.add_argument("--roster", choices=("latest", "launch"), default="latest",
                        help="Com --edition: latest = update mais recente; launch = vigente na data de lançamento.")
    args = parser.parse_args()

    data_dir = Path(__file__).parent.parent.parent / "data"
    session  = _make_session(data_dir)

    # seleção de edição + roster (comum a ambos os modos)
    print("Buscando edições disponíveis no SoFIFA...")
    try:
        editions = fetch_editions(session, data_dir)
    except RuntimeError as e:
        print(e)
        sys.exit(1)
    if not editions:
        print("Não encontrou edições. Apague: data/raw/sofifa_index.html")
        sys.exit(1)

    if args.edition is not None:
        matches = [(k, label) for k, label in editions if edition_number(label) == args.edition]
        if not matches:
            print(f"Edição {args.edition} não encontrada. Disponíveis: "
                  f"{sorted({edition_number(l) for _, l in editions} - {None})}")
            sys.exit(1)
        edition_r, edition_label = matches[0]
    else:
        print()
        for i, (k, label) in enumerate(editions):
            print(f"  [{i:2d}] {label}  (r={k})")
        choice = input("\nEdição (Enter = 0): ").strip()
        edition_r, edition_label = editions[int(choice) if choice.isdigit() else 0]

    print(f"\nBuscando updates de {edition_label}...")
    try:
        rosters = fetch_rosters(session, edition_r, data_dir)
    except RuntimeError as e:
        print(e)
        sys.exit(1)

    if args.edition is not None:
        try:
            r_key, date_label = pick_update(rosters, args.edition, args.roster)
        except ValueError as e:
            print(e)
            sys.exit(1)
    else:
        print()
        for i, (k, date) in enumerate(rosters):
            print(f"  [{i:2d}] {date}  (r={k})")
        choice = input("\nUpdate (Enter = 0 = mais recente): ").strip()
        r_key, date_label = rosters[int(choice) if choice.isdigit() else 0]

    print(f"\nVersão: {edition_label} — {date_label}  (r={r_key})")

    if args.enrich_league:
        edition = edition_number(edition_label)
        out_csv = roster_csv(data_dir / "raw", edition, args.roster) if edition else None
        if out_csv is None or not out_csv.exists():
            print(f"{out_csv} não existe — rode o modo completo primeiro.")
            sys.exit(1)
        print(f"\n[ENRICH] preenchendo league_name em {out_csv}...\n")
        enrich_league_names(session, r_key, out_csv, data_dir)
        sys.exit(0)

    if not args.fast:
        # --- MODO COMPLETO ---
        edition = edition_number(edition_label)
        if edition is None:
            print(f"Não consegui extrair o número da edição de {edition_label!r}.")
            sys.exit(1)
        out_csv = roster_csv(data_dir / "raw", edition, args.roster)
        if out_csv.exists():
            print(f"Já existe: {out_csv} — apague para refazer.")
            sys.exit(0)
        print(f"\n[COMPLETO] baixando todos os jogadores...\n")
        try:
            players = scrape_players(session, r_key, data_dir)
        except RuntimeError as e:
            print(e)
            sys.exit(1)
        save_csv(players, out_csv)
        save_version(data_dir, out_csv, r_key, date_label)
        print(f"\n{len(players)} jogadores → {out_csv}")
        enrich_league_names(session, r_key, out_csv, data_dir)

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
