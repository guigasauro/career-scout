# CLAUDE.md — Career Mode Scout (TM × SoFIFA)

> Título de trabalho: **career-scout**. Ferramenta de scouting para o Modo Carreira do FIFA/EA FC.
> Esta é a fonte de verdade do projeto. Leia tudo antes de escrever ou alterar código.
> **Pivô em andamento (2026-10): scouting por estatísticas avançadas — ver §18.** Status do modo FIFA: **Frontend operacional** — pipeline completo (estágios 1–3) exposto via FastAPI + interface web. 150 clubes das 5 grandes ligas mapeados TM ↔ SoFIFA. Limpeza de dados de chegadas implementada (dedup cross-season, filtro de retornos de empréstimo e promoções internas). Overview do clube em painel enxuto + modal detalhado. Score de matching com normalização por eixos ativos, knob de potencial, desconto D2 e **modo reforço** (ancoragem no overall titular do elenco). Scraper SoFIFA (`sofifa_scraper.py`) cobre FIFA 23+/FC 24-26 via cookies manuais (Cloudflare bloqueia requests puro e soccerdata — ver §4 D6). Próximo: seletor de versão de elenco (parâmetro `?r=` SoFIFA); expansão para mais ligas.

---

## 1. O que o sistema faz (em uma frase)

Aprende o *padrão histórico de contratação* de um clube no Transfermarkt e usa esse perfil para sugerir, no SoFIFA, jogadores parecidos disponíveis na edição certa do FIFA que o usuário está jogando — funcionando como um "olheiro baseado no histórico do clube".

### Exemplo concreto (caso de uso guia)
Se nos últimos 5–10 anos o clube X contratou **zagueiros franceses, com ~23 anos de idade e valor de mercado médio de ~€10M**, o sistema deve buscar no SoFIFA jogadores com esse perfil (posição CB, nacionalidade França, idade próxima de 23, valor de mercado próximo de €10M) na edição do FIFA selecionada, e ranqueá-los por semelhança ao perfil.

---

## 2. Pipeline em 3 estágios

```
┌─────────────────────┐   ┌──────────────────────┐   ┌─────────────────────┐
│ ESTÁGIO 1           │   │ ESTÁGIO 2            │   │ ESTÁGIO 3           │
│ Extração            │ → │ Perfilagem           │ → │ Matching            │
│ (Transfermarkt)     │   │ (análise estatística)│   │ (SoFIFA)            │
└─────────────────────┘   └──────────────────────┘   └─────────────────────┘
  contratações brutas       perfil por posição          candidatos ranqueados
  (1 linha / jogador)       (médias, modas, filtros)    (por distância ao perfil)
```

1. **Extração (Transfermarkt):** dado um clube + janela de temporadas (limitada pelo ano do FIFA), coletar todas as *chegadas* (arrivals) com: nacionalidade, idade, posição, liga de origem, clube de origem, **valor de mercado** e **taxa de transferência paga**.
2. **Perfilagem:** agrupar por posição e calcular:
   - média dos campos numéricos (idade, valor de mercado, taxa);
   - moda dos campos categóricos (nacionalidade, liga, clube de origem);
   - posição mais frequentemente contratada;
   - **filtro:** se um categórico não tiver moda clara (empate/sem repetição), descartar aquele parâmetro para aquela posição.
3. **Matching (SoFIFA):** para cada perfil de posição, buscar jogadores da edição correta do FIFA e ranquear por distância ao perfil (ver [Lógica de matching](#7-lógica-de-matching-estágio-3)).

---

## 3. Stack e setup

- **Linguagem:** Python 3.11+
- **Libs em uso:** `requests`, `beautifulsoup4`/`lxml` (scraper TM), `csv` stdlib (I/O), `fastapi[standard]` (API + servidor).
- **Saída de dados:** CSV locais em `data/processed/`. Cache de HTML cru em `data/raw/`.
- **Interface:** FastAPI + frontend HTML single-page (`index.html` servido pelo próprio FastAPI em `/`).

### Comandos principais
```bash
# Ativar venv (obrigatório)
source transfer-advisor-venv/bin/activate

# Seed do mapeamento TM ↔ SoFIFA (rodar uma vez; aceita filtro por liga)
python seed_clubs.py "French Ligue 1" "English Premier League" "Spain Primera Division" "German 1. Bundesliga" "Italian Serie A"

# Iniciar API + frontend
fastapi dev career_scout/api.py
# Abre http://localhost:8000
```

CLIs dos estágios individuais ainda funcionam para debug:
```bash
python -m career_scout.extract.transfermarkt --club-id 583 --club-slug paris-saint-germain --fifa-year 22 --history 7
python -m career_scout.profile.aggregate
python -m career_scout.match.sofifa --year 22 --top 20
```

### Layout de repositório
```
transfer-advisor/
├── CLAUDE.md
├── pyproject.toml
├── index.html                 # Frontend single-page (servido em GET /)
├── seed_clubs.py              # Script one-time: mapeia clubes Kaggle → TM
├── career_scout/
│   ├── api.py                 # FastAPI: endpoints /overview /scout /clubs /leagues /countries
│   ├── extract/
│   │   └── transfermarkt.py   # Estágio 1 — scraper TM (requests + BS4)
│   ├── profile/
│   │   └── aggregate.py       # Estágio 2 — perfilagem por posição
│   ├── match/
│   │   ├── sofifa.py          # Estágio 3 — matching via Kaggle CSV
│   │   └── sofifa_scraper.py  # fallback: scraper SoFIFA para FC 24+
│   ├── normalize/
│   │   └── positions.py       # mapa TM → FIFA/SoFIFA + fallback por linha
│   └── models.py              # dataclasses Transfer e PositionProfile
├── data/
│   ├── raw/                   # HTML cacheado (TM) + CSVs Kaggle (players_NN.csv)
│   ├── processed/             # arrivals_{club_id}_{edition}_h{history}.csv (cache por clube+edição+histórico)
│   └── club_mapping.json      # mapeamento sofifa_name → {tm_slug, tm_id, league, ok}
└── tests/
```

---

## 4. Decisões pendentes

> **Estas decisões moldam tudo. Não assuma silenciosamente — confirme com o dev. Cada uma traz a recomendação atual, mas é apenas recomendação.**

### D1 — Lib pronta vs scraper próprio
- **Opção A (rápida):** usar libs prontas — `soccerdata` para SoFIFA (tem seletor de versão do FIFA embutido) e `ScraperFC`/`transfermarkt-api` para Transfermarkt.
- **Opção B (controle total):** `requests` + BeautifulSoup na mão, do jeito que o dev já domina.
- **Recomendação:** dar um *spike* na Opção A primeiro (~15–30 min) e só cair pra B se as libs não entregarem os campos necessários ou estiverem quebradas/desatualizadas. Risco de A: dependência de terceiros que quebra quando o HTML do site muda.

### D2 — Valor de transferência vs valor de mercado (⚠️ a mais importante)
O Transfermarkt expõe **dois** valores por transferência:
- **Valor de mercado (Marktwert / `market value`):** estimativa de quanto o jogador *vale*.
- **Taxa de transferência (Ablöse / `fee`):** quanto foi *efetivamente pago* (inclui loan, free, inflação por cláusula/leilão/urgência).

O campo `value` / `value_eur` do **SoFIFA é conceitualmente equivalente ao valor de mercado do TM**, não à taxa paga.
- **Recomendação:** para o *matching*, casar **valor de mercado (TM) ↔ value_eur (SoFIFA)** diretamente. Guardar a **taxa de transferência como sinal secundário** (ex.: "este clube costuma pagar X% acima do valor de mercado") — não usá-la como eixo principal de semelhança.
- Isso resolve de forma limpa a ideia original de "baixar a taxa pra normalizar": em vez de escalar a taxa, simplesmente use o campo de valor de mercado que já existe.

### D3 — Granularidade de posição
Agrupar por **linha** (GK / DEF / MID / ATT) ou por **posição fina** (CB, LB, CDM, ST…)?
- Posição fina = perfis mais precisos, mas **menos amostra por grupo** (a moda fica frágil).
- **Recomendação:** começar com posição fina mas com *fallback* para a linha quando a amostra da posição fina for pequena (ex.: < 3 contratações). Definir o limiar como config.

### D4 — Robustez da moda com amostra pequena
Um clube costuma contratar só **2–4 jogadores por posição em 5 anos**. A moda de nacionalidade é ruidosa; a moda de *clube de origem* quase sempre será única (cai no filtro de descarte — esperado).
- **Recomendação:** tratar a moda como **suporte mínimo** (só conta se aparecer ≥2× ou em ≥X% do grupo) e como **prior suave** (peso no ranqueamento), não como filtro rígido binário.

### D5 — Janela de temporadas
Quantos anos para trás (5? 10?) e como alinhar ao ano do FIFA jogado.
- **Recomendação:** parâmetro configurável `anos_historico` (default 7). A temporada-teto = ano do FIFA selecionado. Ex.: jogando FIFA 22 → considerar transferências até `saison_id` 2021/2022.

### D6 — Scraping ao vivo vs datasets prontos (SoFIFA)
Para **edições antigas** do FIFA (15–23), existem datasets completos prontos (Kaggle/HuggingFace) com ~110 atributos por jogador — pode dispensar scraping do SoFIFA.
- **Recomendação:** se o usuário joga uma edição coberta por dataset pronto, usar o dataset (mais rápido, mais gentil com o site). Scraping ao vivo só para as edições mais recentes (FC 25/26) ou se precisar de um recorte que o dataset não tem.
- **Atualização (edições pós-FIFA 22):** sofifa.com passou a exigir um desafio Cloudflare (Turnstile) em `/players`. Testado ao vivo: **nem `requests` puro nem `soccerdata` (que usa seleniumbase em modo undetected — a lib de referência do ecossistema) conseguem passar**, mesmo rodando de máquina real (não só sandbox) — os dois caem na página "Performing security verification". `soccerdata` foi cogitado e descartado por esse motivo (não instalar de novo sem re-testar). Solução adotada: **cookies manuais** — o dev resolve o desafio uma vez num navegador normal, exporta `cf_clearance` + User-Agent para `data/raw/sofifa_cookies.json` (gitignored via `data/raw/`), e `sofifa_scraper.py` reusa esses cookies via `requests`. Cookie expira (horas) — renovar manualmente quando `_looks_like_challenge` disparar o erro com instruções.
- **Bug encontrado (2026-07-12): `/players?r=...` sem ordenação explícita pagina de forma instável e intercala linhas de OUTRA edição.** Sintoma: jogadores aposentados/fora do elenco aparecendo com nome colado a um número (`"23E. Hazard"` — na verdade `<em>23</em>` de squad number de uma página antiga, o link do jogador aponta pra um `r=` diferente do pedido). Detectado no scrape do FC 26: ~11.301/19.103 jogadores da base eram lixo de edições antigas; a paginação nunca convergia (chegou a rodar até offset ~1M reembaralhando o mesmo pool). **Fix: usar `/players?r=...&col=oa&sort=desc`** — com ordenação explícita a paginação fica estável (60/60 por página, sem repetição/contaminação). `_parse_page` também descarta defensivamente qualquer linha cujo link do jogador não termine no `r_key` pedido. `scrape_players` já usa `col=oa&sort=desc` por padrão — não regredir isso se mexer no scraper.

---

## 5. Modelos de dados (schemas)

### 5.1 — Saída do Estágio 1 (extração TM): uma linha por contratação
| campo            | tipo   | origem TM                  | notas |
|------------------|--------|----------------------------|-------|
| `club_name`      | str    | clube de destino           | o clube alvo da análise |
| `season`         | int    | `saison_id`                | ano da janela |
| `window`         | str    | "Summer"/"Winter"          | janela de transferência |
| `transfer_type`  | str    | "Arrivals"/"Departures"    | **filtrar só "Arrivals"** |
| `player_name`    | str    |                            | |
| `player_url`     | str    |                            | chave p/ enriquecer depois |
| `position_raw`   | str    | ex.: "Centre-Back"         | rótulo bruto do TM |
| `position_norm`  | str    | derivado                   | ver [mapa de posições](#53--mapa-de-posições-tm--fifasofifa) |
| `age`            | int    |                            | idade na transferência |
| `nationality`    | str    |                            | |
| `from_league`    | str    | liga de origem             | pode exigir passo extra |
| `from_club`      | str    | clube de origem (`club_2`) | |
| `market_value`   | float  | valor de mercado (EUR)     | **eixo principal de valor** |
| `fee`            | float  | taxa paga (EUR)            | sinal secundário; loans/free viram 0/NaN |

> Referência de schema: a função `tm_team_transfers()` do pacote R **worldfootballR** retorna exatamente essas colunas (team_name, league, country, season, transfer_type, player_name, player_url, player_position, player_age, player_nationality, club_2, fee, window…). Útil como espelho mesmo implementando em Python.

### 5.2 — Saída do Estágio 2 (perfil por posição)
Um registro por `position_norm` que teve contratação:
```python
{
  "position_norm": "CB",
  "n": 4,                       # tamanho da amostra
  "age_mean": 23.0,
  "market_value_mean": 10_000_000,
  "fee_mean": 12_500_000,       # secundário
  "nationality_mode": "France", # None se sem moda → descartado
  "from_league_mode": "Ligue 1",
  "from_club_mode": None,       # tipicamente descartado (amostra única)
  "is_most_frequent": False,    # True na posição mais contratada
}
```

### 5.3 — Mapa de posições (TM → FIFA/SoFIFA)
Usar como tabela de normalização (`normalize/positions.py`). Rótulos do TM vêm em inglês no mirror `.com`.
| Transfermarkt              | FIFA/SoFIFA |
|----------------------------|-------------|
| Goalkeeper                 | GK          |
| Centre-Back                | CB          |
| Left-Back                  | LB          |
| Right-Back                 | RB          |
| Defensive Midfield         | CDM         |
| Central Midfield           | CM          |
| Attacking Midfield         | CAM         |
| Left Midfield              | LM          |
| Right Midfield             | RM          |
| Left Winger                | LW          |
| Right Winger               | RW          |
| Second Striker             | CF          |
| Centre-Forward             | ST          |

Linhas (para o fallback de granularidade D3): `GK` → GK; `CB/LB/RB` → DEF; `CDM/CM/CAM/LM/RM` → MID; `LW/RW/CF/ST` → ATT.

### 5.4 — Campos relevantes do SoFIFA (estágio 3)
O dataset/scrape do SoFIFA traz ~110 colunas; para este projeto importam principalmente:
`player_id`/`sofifa_id`, `short_name`, `player_positions`, `overall`, `potential`, `value_eur`, `wage_eur`, `age`, `nationality_name`, `league_name`, `club_name` — além das colunas de rating por posição (`cb`, `lb`, `st`, `cam`, …) e dos atributos agregados (`pace`, `shooting`, `passing`, `dribbling`, `defending`, `physic`).

---

## 6. Fonte 1 — Transfermarkt

### Padrões de URL
- **Chegadas/saídas de um clube numa temporada:**
  `https://www.transfermarkt.com/{slug}/transfers/verein/{club_id}/saison_id/{ano}`
  Ex.: PSG → `/paris-saint-germain/transfers/verein/583/saison_id/2025`
- **Página inicial/elenco do clube:**
  `https://www.transfermarkt.com/{slug}/startseite/verein/{club_id}/saison_id/{ano}`
- O parâmetro de temporada é sempre `saison_id` (ano de início da temporada).
- Códigos de competição úteis: Premier League `GB1`, La Liga `ES1`, Serie A `IT1`, Bundesliga `L1`, Ligue 1 `FR1`.

### Notas e armadilhas
- **Cada registro de transferência carrega taxa (fee) E valor de mercado da época, mais o tipo (loan / permanent / free) e a "fee description".** Mapear isso para `fee` e `market_value` (ver D2).
- **Mirror define o idioma dos rótulos.** IDs de jogador/clube são iguais em todos os mirrors; só os rótulos (posição, país, liga) mudam. Use `.com` para rótulos em inglês (combina com o [mapa de posições](#53--mapa-de-posições-tm--fifasofifa)); `.com.br` se quiser PT-BR (mas aí adapte o mapa).
- **Header obrigatório:** enviar `User-Agent` de navegador, senão o site bloqueia.
- `loan` e `free transfer` produzem `fee` = 0/NaN; tratar explicitamente para não poluir a média de taxa.
- Liga de origem (`from_league`) às vezes não está na tabela de transferências e exige seguir o `player_url` ou o link do clube de origem — passo extra opcional.

---

## 7. Fonte 2 — SoFIFA

### Seletor de versão do FIFA (peça-chave)
- A edição + a data de update são codificadas no parâmetro **`?r=`** da URL. Ex.: `?r=220019` corresponde a 9 de dezembro de 2021 → **FIFA 22**.
- Edições disponíveis no site: **FC 26, FC 25, FC 24, FIFA 23 … FIFA 07**, cada uma com vários updates datados.
- Para descobrir o código de uma versão: abrir a página de players, escolher edição/data no dropdown e ler o `?r=` resultante. Manter um dicionário `VERSION_KEYS` no código.
- Lista de jogadores: `https://sofifa.com/players` (paginação via `offset`), com filtros por query string (posição, nacionalidade, faixa de valor/idade/overall).

### Datasets prontos (alternativa ao scraping — ver D6)
- **Kaggle (stefanoleone992):** "FIFA 15–23 complete player dataset", ~110 atributos por jogador. **Os `players_XX.csv` que usamos são o elenco de lançamento** (todos os `player_url` terminam em `r=XX0002`; `club_joined` máximo = set. do ano de lançamento; transferências de janeiro, como Bruno Fernandes 2020 e Vlahović 2022, não aparecem). Verificado em 2026-10-12.
- **HuggingFace (`jsulz/FIFA23`)** e similares: mesmo schema.
- Útil quando a edição jogada é antiga: evita scraping inteiro.

### Ética/robots
- Conforme nota pública de datasets derivados do SoFIFA, o **`robots.txt` do sofifa.com não restringia a coleta** de dados de players/coaches/teams no momento daquelas coletas. Ainda assim: **rate-limit, cache local e User-Agent honesto** são obrigatórios. Reconferir o `robots.txt` atual antes de scrapar em volume.
- **Atualização:** o `robots.txt` atual bloqueia explicitamente crawlers de IA (`ClaudeBot`, `GPTBot`, `CCBot`, etc., `Content-Signal: ai-train=no`) e o site inteiro está atrás de um desafio Cloudflare Turnstile em `/players` — daí a necessidade de cookies manuais (ver D6). Uso segue pessoal/não-comercial (`use=reference` é permitido pelo Content-Signal).

---

## 8. Bibliotecas e recursos externos

| Recurso | Fonte | Uso | Link |
|---|---|---|---|
| **soccerdata** | `pip install soccerdata` | Scraper de SoFIFA com cache e seletor de versão (`versions`) | github.com/probberechts/soccerdata |
| **ScraperFC** | `pip install ScraperFC` (v4.5.x) | Scraper de Transfermarkt + FBref/Sofascore/Understat etc. | pypi.org/project/ScraperFC |
| **transfermarkt-api** | serviço FastAPI (popular) | Consumir TM via API em vez de scrapar HTML | github topic `transfermarkt` |
| **dcaribou/transfermarkt-scraper** | Crawlee/Python, saída JSON | Scraper TM hierárquico (competições→clubes→jogadores) | github.com/dcaribou/transfermarkt-scraper |
| **worldfootballR** | R | *Referência de schema* (`tm_team_transfers`), não para uso direto em Python | jaseziv.github.io/worldfootballR |
| **prashantghimire/sofifa-web-scraper** | Python/Playwright | Scraper SoFIFA (EA FC 25/26), ~18k jogadores | github.com/prashantghimire/sofifa-web-scraper |

> Antes de adotar qualquer lib: checar última atualização e se o HTML-alvo ainda bate (esses scrapers quebram quando o site muda o layout).

---

## 9. Lógica de perfilagem (Estágio 2)

```
para cada position_norm com ≥1 contratação:
    n = contagem
    numéricos (age, market_value, fee): média (considerar mediana se houver outliers)
    categóricos (nationality, from_league, from_club):
        moda = valor mais frequente
        se moda não atinge suporte_mínimo (ex.: <2 ocorrências) → descartar o parâmetro (None)
    marcar is_most_frequent na posição com maior n
```
- **Outliers:** uma contratação cara isolada distorce a média de valor; considerar mediana ou média aparada como config.
- **Saída:** lista de perfis (um por posição), com campos categóricos possivelmente `None` (descartados).

## 10. Lógica de matching (Estágio 3)

> **Princípio central: ranquear, não filtrar.** Filtrar por todos os critérios ao mesmo tempo ("zagueiro francês do Ligue 1, ~23 anos, ~10M") quase sempre retorna 0 resultados. Em vez disso:

```
para cada perfil de posição:
    candidatos = jogadores da edição-FIFA cuja posição ∈ posições da linha
    para cada candidato, somar termos [0,1] dos eixos ATIVOS:
        + match de nacionalidade (se moda existir)              × peso_nac (0.20)
        + match de liga (se moda existir)                       × peso_liga (0.10)
        + (1 - |idade - age_mean| / age_std / 3)                × peso_idade (0.30)
        + (1 - |value_eur - alvo_valor| / val_std / 3)          × peso_valor (0.40)
        [opc] + (potential/100)                                 × potential_weight
        [opc] + (1 - |overall - alvo_overall| / ovr_std / 3)    × OVERALL_WEIGHT (0.45)
    score = soma / Σ(pesos dos eixos ativos)     # normaliza para [0,1]
    aplicar threshold (modo reforço); ordenar por score ou overall; retornar top-N
```
Implementado em `match/sofifa.py::rank_candidates`. Pontos-chave:

- **Normalização por eixos ativos (crítico):** o score é dividido pela soma dos
  pesos dos eixos que o perfil consegue pontuar (tem `fee_mean`? `age_mean`? moda
  de nac/liga?). Isso mantém o score em `[0,1]` e **comparável entre posições** —
  perfil sem fee/nac não fica com teto menor. Sem isso, posições com menos sinais
  pareciam piores artificialmente.
- **Eixo de valor com desconto D2 (`fee_discount`, default 0.8):** o alvo é
  `fee_mean × α`, não a fee cheia. A fee paga embute prêmio (cláusula/leilão) e o
  `value_eur` do SoFIFA é market value — descontar casa as duas grandezas. `α=1.0`
  reproduz o comportamento sem desconto.
- **Knob de potencial (`potential_weight`, default 0):** eixo opcional que premia
  `potential` alto (Career Mode: promessas). 0 = não entra no score.
- **Modo reforço (`team_overall`/`level_offset`/`score_threshold`/`sort_by`):** ver §10.1.
- Parâmetros categóricos descartados no estágio 2 (moda `None`) **simplesmente não entram** no score (nem no numerador nem no denominador).
- `from_club_mode` raramente sobrevive ao filtro de moda — não depender dele.

### 10.1 — Modo reforço (ancoragem no nível do elenco)
Rótulo na UI: **"Ajustar ao elenco"** / "Match squad level" / "Ajustar a la plantilla" (no código continua `realism`).

Resolve "sugestões abaixo do nível do time": clubes que historicamente compram
barato (ex.: Milan pós-2010) viam o eixo de valor puxar jogadores fracos. Quando
ligado, adiciona um eixo de **proximidade ao overall dos titulares** da linha.

- **Baseline (`team_line_overall`):** overall médio dos titulares por linha
  (`club_position` ∉ {SUB, RES}). Fallback: top-3 por overall na linha quando não
  há XI marcado (raro no Kaggle; cobre edições futuras sem `club_position`).
- **`level_offset` (ambição):** desloca o overall-alvo — `0` reforço similar,
  `+3` upgrade, `−3` aposta barata.
- **Valor-alvo acompanha o offset:** com `level_offset ≠ 0`, o alvo de valor
  (`fee_mean × fee_discount`) é multiplicado pela razão de preço de mercado da
  posição — mediana de `value_eur` a ±1 do overall-alvo ÷ a ±1 do overall do
  elenco. Sem isso o eixo de valor (histórico barato) anulava o Upgrade.
- **`value_log` (toggle "Escala de valor"):** mede a distância de valor em log
  (razão, não euros). Default linear; em teste A/B.
- **`score_threshold` (tamanho do rol):** corte mínimo de score; retorna o **rol**
  acima do threshold em vez de top-N puro. Frontend expõe Estrito 0.6 / Médio 0.45
  / Amplo 0.3. É o que impede "vazamento de estrelas" no sort por overall.
- **`sort_by`:** `"score"` (melhor encaixe) ou `"overall"` (melhores jogadores do rol).
- **Peso `OVERALL_WEIGHT = 0.45`** — firme, mas ≤ `value` (decisão do dev: eixo
  adicional, não principal; OFF = 100% padrão histórico, o comportamento "realista").
- Default OFF → comportamento idêntico ao de antes.

---

## 11. Convenções de código

- Tudo tipado com `dataclasses`/`TypedDict`; schemas centralizados em `models.py`.
- **Cache obrigatório** de toda página/resposta crua em `data/raw/` (chave = URL+versão). Nunca refazer request se já há cache válido.
- Funções de scraping puras e idempotentes; parsing separado de fetching (facilita teste com HTML salvo).
- Valores monetários sempre em **EUR como `float` (unidade base, não "10M" string)** — converter na entrada.
- Nomes de coluna em `snake_case`, conforme schemas da seção 5.
- Comentários e docstrings podem ser em PT-BR (preferência do dev).

## 12. Ética e legal de scraping

- Uso **pessoal e não comercial** (ferramenta de modo carreira).
- **Rate-limit** com pausa entre requests, `User-Agent` honesto, **cache agressivo** para minimizar carga nos servidores.
- Reconferir `robots.txt` e ToS atuais de cada site antes de coletas em volume; preferir datasets prontos quando existirem (ver D6).
- Não redistribuir dados crus dos sites.

---

## 13. Ordem de implementação (roadmap)

1. ✅ **Fatia vertical do Estágio 1.** PSG + FIFA 22 (temporadas 2014–2021). 125 chegadas extraídas no schema 5.1. Schema travado.
2. ✅ **Normalização de posições** (`normalize/positions.py`) — mapa TM → FIFA/SoFIFA + fallback por linha.
3. ✅ **Estágio 2** (perfilagem) — `profile/aggregate.py`. Perfis por posição com moda + suporte mínimo.
4. ✅ **Estágio 3** — matching via dataset Kaggle `players_{year}.csv`. `league_name` disponível. `_normalize_league` mapeia nomes TM → Kaggle.
5. ✅ **API FastAPI + frontend** — `career_scout/api.py` expõe os 3 estágios. `index.html` com fluxo FIFA → País → Liga → Clube → overview → candidatos.
6. ✅ **Mapeamento TM ↔ SoFIFA** — `seed_clubs.py` raspa busca do TM para cada clube dos CSVs Kaggle, salva `data/club_mapping.json`. 150 clubes das 5 grandes ligas mapeados + correções manuais para mismatches do primeiro resultado de busca.
7. ✅ **Limpeza de chegadas** — `_dedup_arrivals`: descarte de retornos de empréstimo ("End of loan"), promoções internas (base própria) e dedup cross-season por jogador (permanent > free > loan, temporada mais recente em empate).
8. ✅ **Frontend refinado** — cores por linha de posição, "ver mais" expansível por posição com distribuições + lista de jogadores, paginação de chegadas (20 + carregar mais), nomenclatura "Valor pago", janela → data aproximada (Jul/Jan + ano).
9. ✅ **Overview em painel + modal** — ao selecionar o clube, painel enxuto (contratações/temporada, modas de nac/liga, idade média, valor médio/máximo pago) com "ver detalhes ↗" abrindo a visão geral completa no modal.
10. ✅ **Eixos de score** — normalização por eixos ativos, knob de potencial, desconto D2 (`fee_discount`) e **modo reforço** (ver §10.1). Cobertos por `tests/test_sofifa.py`.
13. ✅ **i18n do frontend (pt-BR / en / es)** — dicionário `I18N` + `t()` no `index.html`, seletor no cabeçalho (salvo em `localStorage`, default = idioma do navegador). Países/nacionalidades traduzidos via `Intl.DisplayNames` (mapa nome-inglês → ISO montado do próprio Intl + `COUNTRY_ISO_ALIAS` para nomes do SoFIFA/TM tipo "Korea Republic"; `COUNTRY_NON_ISO` para Inglaterra/Escócia/Gales/Irlanda do Norte). Siglas de posição traduzidas via `POS_I18N`/`posName` (pt: ZAG, VOL, MEI, PE, ATA…; es: DFC, MCD, MCO, EI, DC…; linhas de fallback DEF/MEIO/ATAQ e DEF/MED/DEL). Valores enviados à API continuam em inglês — só o rótulo traduz.
14. ✅ **Lista de observação** — estrela (☆/★) ao lado do nome de cada candidato; botão "Observados" no header abre a lista num modal (contador no botão). Salva no navegador (`localStorage['watchlist']`), chave `{edição}:{sofifa_id}` — o mesmo jogador em outra edição é outra entrada. Guarda um retrato do candidato (clube, valor, OVR/POT da edição), então a lista não depende de refazer a busca. Sem backend.
15. ✅ **Clubes em ordem alfabética** no seletor (ordenados no frontend com `localeCompare`, acentos não atrapalham).
16. ✅ **Janela de detalhes da posição** — botão "Detalhes" em cada cartão de posição: alvo e peso de cada critério do score (com a explicação do alvo de valor), perfil histórico completo e o score de cada candidato aberto por critério (pontos/máximo). Substitui o tooltip do score no celular.
17. ✅ **Clube e edição na barra fixa** — a barra das posições (que gruda no topo ao rolar os candidatos) mostra "Clube · Edição".
11. ✅ **Versões de elenco (Lançamento / Último update)** — `players_{N}.csv` é a versão base (Kaggle = lançamento até o 22; raspado = último update do 23 em diante) e a alternativa fica em `players_{N}_{launch|latest}.csv` (`sofifa.roster_csv`/`available_rosters`). Scraper: `--roster launch|latest`; "launch" = último update com data ≤ `RELEASE_DATES[edição]` (descarta `XX0001` de agosto = beta/revelação de ratings e elencos especiais sem data, ex.: "World Cup 2022"). API: `roster` no `/scout`, versões em `/data-info`; frontend: seletor "Elenco". Kaggle = update `XX0002`, 1–16 dias antes do lançamento (FIFA 19: 5 semanas antes) — datas em `api.KAGGLE_UPDATES`.
    - Ligas fora do catálogo atual do SoFIFA mas presentes em edições antigas (J-League 349, África do Sul 347) estão em `RETIRED_LEAGUES` no scraper; em edições sem elas a página de times volta vazia (sem risco de rótulo errado).
    - Sem `club_position` (CSVs raspados), `team_line_overall` usa os N melhores por linha num 4-4-2 (GK 1/DEF 4/MID 4/ATT 2), calibrado contra os titulares do Kaggle 22 (erro médio ≤1,4; o antigo top-3 errava o GK em 6,6).
12. ✅ **Scraping ao vivo do SoFIFA para FIFA 23/FC 24/25/26** — `sofifa_scraper.py`, autenticado via cookies manuais (Cloudflare bloqueia requests puro e soccerdata; ver D6). CLI gera `data/raw/players_{edition}.csv` no mesmo formato dos CSVs Kaggle, sem tocar em `api.py`/`sofifa.py`. O modo completo grava o update usado (`r` + data) em `data/raw/sofifa_versions.json`. `club_position` fica vazio de propósito — `team_line_overall` já tem fallback (top-3 por overall) pra isso.

---

## 14. Decisões tomadas

| Decisão | Escolha |
|---------|---------|
| **D1** — scraper TM | `requests` + BeautifulSoup direto (ScraperFC não tem método de transfers por clube) |
| **D2** — eixo de valor | **Fee paga** (não valor de mercado). `market_value` removido do schema. Desconto **implementado**: alvo no SoFIFA = `fee_mean × fee_discount` (default 0.8), casando `value_eur` (market value) ↔ fee descontada. `α=1.0` desliga o desconto. |
| **Score** — normalização | Score normalizado pela soma dos **pesos dos eixos ativos** do perfil → `[0,1]` comparável entre posições. Eixo ausente não penaliza nem infla o teto. |
| **Potencial** — knob | Eixo opcional `potential_weight` (default 0). Preferência do usuário (promessas), não padrão do clube. Frontend: Off/Baixo/Médio/Alto. |
| **Modo reforço** | Eixo opt-in ancorado no overall titular do elenco (`OVERALL_WEIGHT = 0.45`, ≤ value — **adicional, não principal**). OFF = 100% padrão histórico ("realista"). Controles: Nível-alvo (`level_offset`), Tamanho do rol (`score_threshold`), Ordenar por (`sort_by`). Ver §10.1. |
| **D3** — granularidade | Posição fina com fallback para linha (config `min_sample`, default 3) |
| **D5** — janela | **5 temporadas** de histórico (configurável via `--history`). Fórmula: `range(season_ceil - history + 1, season_ceil + 1)` onde `season_ceil = 2000 + fifa_edition - 1`. FIFA 17 → temporadas 2012/13–2016/17. |
| **D6** — SoFIFA | **Dataset Kaggle `players_{year}.csv`** para FIFA 15–22 (baixado em `data/raw/`). `sofifa_scraper.py` para FIFA 23+/FC 24-26, autenticado via cookies manuais (ver §4 D6 — Cloudflare bloqueia `requests` puro e `soccerdata`). Liga disponível via `league_name` no Kaggle — `_normalize_league` faz o mapeamento TM → Kaggle (ex.: "Ligue 1" → "French Ligue 1", "Eredivisie" → "Holland Eredivisie"). O scraper não preenche `league_name` (não disponível na listagem do SoFIFA). |
| **transfer_type** | Campo adicionado: `"permanent"` \| `"loan"` \| `"free"`. `fee_mean` no Estágio 2 considera só `permanent` com fee > 0 (livres ficam fora da média de valor, mas contam para idade/nac/liga e para `n_permanent`). `"loan_return"` é descartado no parser (retornos de empréstimo — "End of loan" no TM). |

## 15. Schema travado do Estágio 1 (Transfer)

```python
Transfer(
    club_name, season, window,
    player_name, player_url,
    position_raw, position_norm,   # ex.: "Centre-Back" → "CB"
    age, nationality,
    from_club, from_league,
    transfer_type,                 # "permanent" | "loan" | "free"
    fee,                           # EUR float | None (desconhecido)
)
```

Armadilhas resolvidas no parser:
- `find_all("td", recursive=False)` para não contar células de inline-tables internas
- `"End of loan30/06/YYYY"` — data colada → `transfer_type = "loan_return"`, descartado imediatamente
- `td.hauptlink` para pegar link do clube de origem (não o logo)
- `loan fee:` com valor numérico é empréstimo com taxa, não contratação definitiva

### Limpeza de chegadas (`_dedup_arrivals`)
Aplicada após scraping de todas as temporadas, antes de salvar o cache:
1. **Promoções internas** — `from_club` contém o nome do próprio clube ou marcadores de base (`u20`, `primavera`, `reserve`, etc.) → descartadas.
2. **Dedup cross-season** — chave = `player_name`; mesmo jogador em temporadas diferentes (ex.: loan 2013 + permanent 2015) → mantém só a entrada mais relevante: `permanent > free > loan`; em empate de tipo, temporada mais recente.

### Posições de linha como fallback (ATT / DEF / MID)
Quando `position_norm` fina (ex.: `ST`, `LW`) tem amostra < `min_sample`, o estágio 2 agrupa na linha (`ATT`, `DEF`, `MID`). O estágio 3 e o frontend expandem essas linhas de volta para as posições finas ao filtrar candidatos e chegadas:
- `ATT` → `["ST","LW","RW","CF"]`
- `DEF` → `["CB","LB","RB","LWB","RWB"]`
- `MID` → `["CDM","CM","CAM","LM","RM"]`

---

## 16. API FastAPI (`career_scout/api.py`)

### Endpoints
| Método | Rota | Descrição |
|--------|------|-----------|
| `GET`  | `/` | Serve `index.html` |
| `GET`  | `/fifa-years` | Edições disponíveis (baseado nos CSVs em `data/raw/`) |
| `GET`  | `/data-info` | Origem e versão dos jogadores por edição (Kaggle = elenco de lançamento; SoFIFA = data do update, de `data/raw/sofifa_versions.json`). Usado no "Como funciona" do header |
| `GET`  | `/countries?edition=N` | Países disponíveis para a edição (via `LEAGUE_COUNTRY`) |
| `GET`  | `/leagues?edition=N&country=X` | Ligas da edição, filtradas por país |
| `GET`  | `/clubs?league=X&edition=N` | Clubes com mapeamento TM válido na liga, naquela edição (liga vem do CSV da edição) |
| `POST` | `/overview` | Estágios 1+2: retorna chegadas + perfis + estatísticas agregadas |
| `POST` | `/scout` | Estágios 1+2+3: retorna candidatos ranqueados por posição |
| `GET`  | `/analytics/seasons` | Temporadas do StatsBomb com CSV em `data/processed/` (§18) |
| `GET`  | `/analytics/teams?season=` | Times da temporada com posição e pontos |
| `GET`  | `/analytics/team?season=&team=&target=1-4` | Classificação e as 16 métricas com percentil e `gap` (`deficiencies`) |
| `GET`  | `/analytics/recommend?season=&team=&target=&max_gap=&max_age=&max_value=&top=` | Funções a reforçar com candidatos (`recommend`); `season`/`team` validados contra o que existe em disco |

### Body de `/overview` e `/scout` (`ScoutRequest`)
```json
{ "club_id": 583, "club_slug": "paris-saint-germain", "club_name": "PSG",
  "fifa_edition": 22, "history": 7, "top_n": 20,
  "potential_weight": 0.0, "fee_discount": 0.8,
  "realism": false, "level_offset": 0, "sort_by": "score", "score_threshold": 0.0 }
```
- `fifa_edition` = número da edição (22 = FIFA 22); mapeia para `players_22.csv` e seasons até 2021 (`2000 + edition - 1`)
- Cache de chegadas em `data/processed/arrivals_{club_id}_{edition}_h{history}.csv` — segunda chamada não raspa o TM
- Campos de matching (só usados por `/scout`): `potential_weight` (knob de potencial), `fee_discount` (desconto D2), e o **modo reforço** — `realism` (liga a ancoragem no overall do elenco), `level_offset` (ambição: 0/+3/−3), `sort_by` (`score`|`overall`), `score_threshold` (corte do rol; 0 → backend usa 0.4 quando `realism`). Ver §10–10.1.
- Resposta de `/scout` inclui `team_levels` (overall titular por linha) e, por posição, `team_overall`, `targets` (alvo e peso % de cada eixo do score, preenchidos por `rank_candidates(targets=...)`) e `total` (tamanho do rol inteiro; `candidates` vem cortado em `top_n`). O frontend pede `top_n=50` e pagina 10 por vez dentro do cartão da posição; ordenar por coluna reordena os 50, não só a página. Resposta de `/overview` traz `by_season`, modas (`by_nationality`/`by_from_league`), `age_stats`, `fee_stats`, perfis e chegadas.

### Estrutura de clubes (`CLUBS_DB`)
Carregada na inicialização a partir de `data/club_mapping.json` + `_OVERRIDES` (lista manual em `api.py` que prevalece).  
Cada entrada: `{name, slug, id, sofifa_name, league}`.  
`sofifa_name` é usado para excluir jogadores do próprio clube do pool de matching (`exclude_club`).

### `LEAGUE_COUNTRY`
Dict hardcoded em `api.py` mapeando as 58 ligas dos CSVs Kaggle para países. "Outros" como fallback.  
Usado em `/countries` e `/leagues?country=X`.

---

## 17. Mapeamento TM ↔ SoFIFA (`seed_clubs.py` + `club_mapping.json`)

### Problema
Os CSVs Kaggle têm `club_name` (SoFIFA) mas não têm slug/id do Transfermarkt — necessários para raspar o histórico de contratações.

### Solução
`seed_clubs.py` faz busca no TM (`/schnellsuche/ergebnis/schnellsuche?query=...`) para cada clube único dos CSVs e extrai o slug/id do primeiro resultado. Salva em `data/club_mapping.json` incrementalmente (pode interromper e retomar).

```bash
# Seed parcial (recomendado primeiro)
python seed_clubs.py "French Ligue 1" "English Premier League" ...

# Seed completo (~1016 clubes, ~25 min)
python seed_clubs.py
```

### Cuidados com o seed
- O **primeiro resultado** da busca do TM frequentemente é errado (time sub-17, clube de nome similar de outro país, etc.).
- Após rodar, revisar entradas com `"ok": false` e os slugs suspeitos no JSON.
- Correções manuais: editar `club_mapping.json` diretamente (`ok: true`, `tm_slug`, `tm_id`) **ou** adicionar ao `_OVERRIDES` em `api.py` para correções permanentes que sobrevivam a re-seeds.
- Para achar slug/id correto: abrir a página do clube no TM e ler a URL — `/{tm_slug}/startseite/verein/{tm_id}`.
- PSG no seed veio como `fc-paris-saint-germain/583`; override em `_OVERRIDES` usa `paris-saint-germain/583` (slug correto).

### Busca mais segura (2026-10)
`search_tm` lê só a caixa **"Clubs"** da busca (links de clube da caixa de jogadores davam clube errado — ex.: Carpi → Burgos), pula times de base/B (`YOUTH`, exceto quando o próprio nome tem o marcador: "FC Barcelona B", "Willem II") e exige o país da liga (`LEAGUE_NATIONS`; Championship aceita Gales, MLS aceita Canadá, Segunda aceita Andorra). Nome que é variante de um clube já mapeado (`norm_name`: "Arsenal FC" = "Arsenal") vira alias sem busca. Testes em `tests/test_seed_clubs.py`.

### Estado atual
5 grandes ligas + Championship, La Liga 2, Serie B, 2. Bundesliga, Ligue 2, Portugal, Holanda, Argentina, MLS, Liga MX, Turquia e Arábia Saudita (Brasileirão de fora: não é licenciado no jogo). Todos os clubes dessas ligas em todas as edições (15–27, nas duas versões de elenco) mapeados. Mapeados à mão: `AC Arles Avignon` → `athletic-club-arlesien/11300` (o TM usa o nome original do clube) e `Al Riyadh` → `al-riyadh-sc/31008` (a busca do TM não acha). Nomes com patrocinador (ex.: "Yukatel Kayserispor") ou siglas pontuadas não são achados pela busca — foram mapeados à mão com buscas limpas e revisados.

**Auditoria (2026-10-13):** o título da página de cada id do TM foi comparado com o nome no mapeamento. 19 clubes do mapeamento antigo apontavam para **outro clube**: Everton (Hertha BSC II), Deportivo (Montpellier), Montpellier (id inexistente), Parma, Mainz, Nancy (Legia Varsóvia), Spezia, SPAL, Benevento, Brescia, Sassuolo, Arminia (Preußen Münster), Lecce, Sampdoria, Palermo, Pescara, Chicago Fire (time B), Castellammare di Stabia (clube amador; é o Juve Stabia, 5587), além do Bordeaux já corrigido antes — todos corrigidos; o modo FIFA mostrava o histórico de contratações do clube errado para eles. A auditoria (~540 páginas) fez o TM responder 403 por alguns minutos: espaçar coletas grandes. Renomeações legítimas (Arles-Avignon → Athlétic Club Arlésien, Llagostera → UE Costa Brava) aparecem com nome diferente e estão certas.

---

## 18. Pivô: scouting por estatísticas avançadas (portfólio)

> Decidido em 2026-10-13. O modo FIFA (§1–17) continua funcionando como módulo à parte. Objetivo do pivô: recomendar jogadores reais a partir das **deficiências estatísticas do clube na temporada**, não do padrão histórico de contratação. Uso: **portfólio** (não comercial) — por isso dados abertos agora, e a camada de dados isolada para trocar por fonte licenciada depois.

### 18.1 Fontes de dados (decisão)
| Fonte | Status | Motivo |
|---|---|---|
| **StatsBomb Open Data** | ✅ **base do protótipo** | Dados de evento completos (xG por chute, passes, pressões, duelos), uso livre não comercial com crédito. Temporada **2015/16 completa de Premier League, La Liga e Serie A**, Ligue 1 com 377/380 jogos (`SEASONS` em `analytics/statsbomb.py`). **A Bundesliga 2015/16 tem só os 34 jogos do Leverkusen** (idem 2023/24) — fora da análise: sem a liga inteira não há tabela nem percentil. Repositório: github.com/statsbomb/open-data |
| Transfermarkt | ✅ reaproveitado | Valor de mercado, idade, contrato e transferências (já raspado em §6) |
| FBref | ❌ | Perdeu xG e métricas avançadas em 20/01/2026 (Opta cortou o acesso e exigiu apagar o histórico). Só sobra estatística básica |
| Understat | ❌ | `robots.txt` com `Disallow: /` para todos (conferido em 2026-10-13) |
| Sofascore | ❌ | Sem API pública; termos proíbem coleta automática; anti-bot |
| Opta / StatsBomb / Wyscout pagos | futuro | O que clubes usam. Wyscout ~€15–30 mil/ano por clube; StatsBomb e Opta sob contrato, dezenas de milhares de euros/ano (estimativas públicas, sem preço oficial) |

**Limite assumido:** só 2015/16 (dados antigos). Vantagem: dá para **validar** — deficiências de 2015/16 × contratações reais do verão de 2016 (TM).

### 18.2 Método
1. **Estatísticas da temporada** (`analytics/statsbomb.py`): jogo a jogo → somas por jogador (minutos pela escalação) e por time (a favor e contra). CSVs em `data/processed/sb_{temporada}_{players|teams}.csv`.
2. **Deficiências do time:** métricas por 90 (defensivas ajustadas pela posse) em **percentil da liga** e comparadas com os times do **patamar-alvo** (ex.: 4º–7º para quem mira Europa), não com o campeão.
3. **Deficiência → posição/função:** ex.: xG contra alto → zaga/volante; pouco xA/passes na área → meias/pontas.
4. **Perfil-alvo da função:** métricas por 90 que importam nela (pesos por função).
5. **Ranking de candidatos:** semelhança ao perfil (mesma estrutura do `rank_candidates`: eixos ponderados, score [0,1], detalhe por eixo), com mínimo de minutos e ajuste pela força da liga.
6. **Filtros de realidade (TM):** idade, valor de mercado, contrato.
7. **Validação:** casos conhecidos de 2015/16 → verão de 2016.

### 18.3 Ordem do protótipo
1. ✅ Carregador StatsBomb + agregação por jogador/time (Premier League 2015/16). Testes em `tests/test_statsbomb.py`.
2. ✅ Relatório de deficiências (`analytics/deficiencies.py`): 16 métricas por jogo, percentil na liga e `gap` até a média do patamar-alvo (default top 4, `--target`), em desvios-padrão da liga; negativo = deficiência. Cada métrica aponta as linhas (DEF/MID/ATT) que mais pesam nela. CLI: `python -m career_scout.analytics.deficiencies premier-league-2015-16 Chelsea`.
3. ✅ Recomendação por deficiência (`analytics/recommend.py`), dentro da própria liga. Deficiências com `gap ≤ −0.5` (`--max-gap`) → **perfis** que as resolvem (`ROLES` aponta para `PROFILES[(função, perfil)]`: ex. zagueiro · marcação / jogo aéreo / construção, volante · desarmes / construção, ponta · finalização / criação / pressão — cada um com estatísticas por 90 e pesos) → candidatos pelo percentil ponderado no pool da função (≥900 min e ≥30% dos minutos na função). `plan()` agrupa: uma entrada por função, com os perfis pedidos (na ordem da maior deficiência); deficiências que pedem o mesmo perfil se juntam (Real Betis: 16 tabelas → 7 funções). Mostra também os jogadores atuais do clube na função, com o mesmo score. Ações defensivas ajustadas pela posse do time do jogador. CLI: `python -m career_scout.analytics.recommend premier-league-2015-16 Chelsea`.
   - Conferência manual: Chelsea (xG sofrido −1,14) → Kanté em 4º entre os volantes. Liverpool (xG por chute −1,25; dribles −0,46) → Mané só em 21º entre os pontas: a função "ponta" pede criação e drible, e o forte dele era finalizar. **Não ajustar pesos olhando casos conhecidos** — calibrar no passo 5, com muitas contratações.
   - Perfil **Meia ofensivo · Infiltração** (recepções na área, npxG, chutes, conduções até a área) para deficiências de xG/chutes/qualidade da chance. Com ele o Mané aparece em 3º para o Liverpool — mas o perfil foi criado sabendo que o Mané foi a contratação real, então **não conta como validação**.
4. ✅ Idade e valor do TM (`analytics/market.py`): lê o **elenco de cada clube na temporada** (`/kader/.../saison_id/{ano}/plus/1`, uma página por clube) e casa os nomes dentro do clube (`name_score`: sobrenome + inicial valem mais; sem sobrenome em comum só grafia quase idêntica). Premier League 2015/16: 548/550 casados. Idade = na janela de verão seguinte; valor = o da época. O TM não mostra contrato em temporadas passadas. Filtros `max_age`/`max_value` em `recommend` (quem não tem o dado passa). CLI: `python -m career_scout.analytics.market premier-league-2015-16` → `sb_{temporada}_market.csv`.
   - Casamento por liga (2015/16): Premier League 548/550, La Liga 531/539, Serie A 550/551, Ligue 1 573/574. Nomes do StatsBomb que diferem do mapeamento ficam em `TEAM_ALIASES` (`market.py`).
   - Achado no caminho: o **Everton** estava com o id 45 (Hertha BSC II) no `club_mapping.json` desde o primeiro mapeamento — corrigido para 29 (afetava o modo FIFA).
5. ✅ Validação (`analytics/validate.py`, `python -m career_scout.analytics.validate 2015-16`): contratações da **janela de verão de 2016** no TM (`.../saison_id/2016/pos//detailpos/0/w_s/s`) dos 78 times das 4 ligas, casadas com o pool do StatsBomb pelo `tm_player_id`. Detalhe em `data/processed/validation_2015-16.csv`. **Resultado (patamar Top 4, gap ≤ −0,5, força 0,3):**
   - 832 contratações; só **215 avaliáveis** (≥900 min nas 4 ligas em 2015/16). O resto veio de outras ligas (Bundesliga incluída — Xhaka, Matip), da base, ou jogou pouco.
   - Posição pedida pelo método: **84% × acaso 83%** — o método pede quase todas as posições (times fracos têm muitas deficiências contra o Top 4), então não discrimina.
   - No top 10 / top 30 de um perfil pedido: **6% × 8%** e **20% × 22%** — igual ao acaso.
   - Posição relativa nos perfis pedidos × nos outros perfis da mesma função (0 = topo): **0,45 × 0,50**, n=89; diferença 0,055, IC95% [−0,011; 0,119], teste dos sinais p=0,07 — **não significativo**.
   - Leitura: do jeito que está, o método **não prevê as contratações reais melhor que o acaso**. Kanté (13º, Chelsea) e Mané (3º, Liverpool) são exceções, e os dois influenciaram ajustes. Hipóteses a testar: (a) cortar nas K maiores deficiências em vez de gap ≤ −0,5; (b) patamar relativo à posição do time (Arsenal, 2º, não tinha deficiência de zagueiro contra o Top 4 e contratou o Mustafi); (c) filtro de preço pelo padrão de gastos do clube (o histórico de contratações do modo FIFA) — clubes compram dentro do orçamento; (d) a contratação real é um gabarito ruidoso (orçamento, disponibilidade, empresários).
   - **Experimento 1 (2026-10-13): patamar e foco.** Protocolo: desenvolvimento = times de Premier League + Serie A (117 contratações avaliáveis), teste = La Liga + Ligue 1 (98), critério fixado antes: maior ganho sobre o acaso no top 30.
     - Desenvolvimento: A tier Top 4 gap≤−0,5 −0,2 pts; **B tier Top 4 K=3 +3,6 pts** (vencedora); C relativo K=3 +0,7; D relativo K=5 −1,1. Média da liga (`target 1-20`, rodada antes, todos os times): também no acaso.
     - **Teste (uma vez):** A −3,4 pts (IC95% −11,4 a +4,8); **B −6,5 pts (IC95% −9,9 a −2,3)** — o ganho do desenvolvimento era ruído. Nenhuma variante supera o acaso.
     - Pista: em La Liga/Ligue 1 os contratados aparecem nas listas **menos** que um jogador qualquer — as listas premiam números altos (jogadores caros/de clube grande) e times médios compram dentro do orçamento → hipótese do filtro de preço.
     - **O conjunto de teste foi usado**: hipóteses novas medidas em La Liga/Ligue 1 são exploratórias, não confirmatórias. Teste limpo exige outra temporada.
   - **Experimento 2 (exploratório): orçamento** (`analytics/budget.py`: percentil 90 das compras pagas em 3 temporadas, teto ×1,25; `validate --budget`). 81% das contratações cabem no teto. Ganho no top 30 continua ≤ 0 (todos: −5,9 pts; La Liga/Ligue 1: −12,6). Sinal fraco: entre pagáveis, contratados ficam melhor nos perfis pedidos (0,41 × 0,50; IC95% [0,007; 0,160], p = 0,041, n = 70) — não confirmatório. Detalhes e tabela em `docs/notas-tcc.md` §5.2.
     - Ficou no código: `deficiencies(mode="tier"|"relative")`, `plan(top_k=)`, `validate --mode/--top-k/--leagues`. Padrão inalterado (Top 4, gap ≤ −0,5). Métricas de estilo (`Metric.style`: posse, % de passes) não viram pedido de reforço — escolha de princípio (Leicester campeão com pouca posse), sem efeito medido na validação.
6. ✅ Interface: modo **"Análise de dados"** no header (`setMode`, `#analise` na URL), ao lado do Modo Carreira. Seletores de temporada, time, patamar (Campeão / Top 4 / 5º–7º / 8º–12º), idade e valor máximos; tabela das 16 métricas agrupada em **Ataque / Criação / Defesa** (`Metric.group`), com valor do time + seta ▲/▼ contra a **média da liga** (cor = bom/ruim, já que nos números "contra" estar acima é ruim; sem seta quando iguais na precisão exibida), média da liga, alvo do patamar, percentil e distância; um cartão por função com **seletor de perfil** (`anRoleCard`; escolha guardada em `_anSel`), as deficiências que o perfil resolve, os jogadores atuais e os candidatos (idade, valor, minutos, score e as estatísticas por 90, com o percentil no tooltip). Cabeçalhos com nome explícito (`s_*`, ex.: "Desarmes certos", "Aéreos ganhos") e a definição completa no tooltip (`sf_*`, via `<abbr title>` em `anTh`), incluindo quais são ajustadas pela posse e quais não são por 90 (xG por chute, % de passes). pt/en/es.

### 18.4 Notas do carregador
- Cache cru em `data/raw/statsbomb/*.json.gz` (gzip: um jogo cru tem ~4MB; 380 jogos).
- Passe: tiro de meta e saída de bola não contam. Completo = sem `outcome`. **Progressivo** = avança ≥10 jardas (simplificação, não a regra da Opta). xA = xG do chute que o passe gerou (`assisted_shot_id`).
- `npxg` exclui pênaltis. Gols contra não entram em `goals`/`goals_against` (só chutes).
- Posse aproximada por `passes_share` (fatia dos passes do jogo).
- Jogador transferido no meio da temporada fica com o último clube.
- Nome do time: vale o da lista de jogos, casado pelo `team_id` — nas escalações da Ligue 1 o nome muda de jogo para jogo ("Olympique de Marseille" × "Marseille", "Stade Malherbe Caen" × "Caen").
- Conferência das tabelas contra as reais: Premier League, La Liga e Serie A batem; Ligue 1 bate exceto pelos 3 jogos ausentes (PSG 93 em vez de 96, Gazélec 34 em vez de 37).
- Infiltração: `box_receptions` (passe recebido já dentro da área adversária; recepção falha não conta), `carries_into_box` (condução que começa fora e termina dentro da área), `npg` (gols sem pênalti — fora do score: ruído alto numa temporada). **Sprints e corridas sem bola não existem** no StatsBomb (dado de evento, não de rastreamento físico).
- `positions` guarda os minutos por posição (`"Center Attacking Midfield:1033;Right Wing:1005"`); `position` é a principal.
- Classificação (`points`, `goals_for`, `goals_conceded`, `rank`) vem do placar oficial dos jogos. Conferida contra a tabela real de 2015/16 (Leicester 81, Arsenal 71, Tottenham 70…; Kane 25 gols, Özil 19 assistências).
