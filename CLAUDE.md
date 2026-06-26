# CLAUDE.md — Career Mode Scout (TM × SoFIFA)

> Título de trabalho: **career-scout**. Ferramenta de scouting para o Modo Carreira do FIFA/EA FC.
> Esta é a fonte de verdade do projeto. Leia tudo antes de escrever ou alterar código.
> Status atual: **Estágio 1 concluído** — scraper TM funcional, schema travado, 125 chegadas do PSG (2014–2021) extraídas e salvas. Próximo: Estágio 2 (perfilagem).

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

- **Linguagem:** Python 3.11+ (consistente com o histórico do dev; scrapers anteriores em `requests`/BeautifulSoup).
- **Libs candidatas:** `pandas`, `requests`, `beautifulsoup4`/`lxml`, e **uma das libs de scraping de futebol** (ver [seção 8](#8-bibliotecas-e-recursos-externos)). Decisão de "lib pronta vs scraper próprio" ainda em aberto.
- **Saída de dados:** CSV/Parquet locais por enquanto (cache em disco). Banco só se/quando justificar.
- **Interface:** CLI primeiro. Frontend/dashboard é fase futura, não escopo inicial.

> ⚠️ Comandos de build/test/lint **ainda não definidos** — preencher esta seção assim que o esqueleto do repo existir (ex.: `pytest`, `ruff`, `python -m career_scout ...`).

### Layout de repositório proposto (ajustar conforme implementar)
```
career-scout/
├── CLAUDE.md
├── pyproject.toml
├── career_scout/
│   ├── extract/        # Estágio 1 — scrapers Transfermarkt
│   │   └── transfermarkt.py
│   ├── profile/        # Estágio 2 — perfilagem estatística
│   │   └── aggregate.py
│   ├── match/          # Estágio 3 — query + ranqueamento no SoFIFA
│   │   └── sofifa.py
│   ├── normalize/      # camada de normalização (posições, ligas, valores)
│   │   └── positions.py
│   └── models.py       # dataclasses / schemas dos dataframes
├── data/
│   ├── raw/            # HTML/JSON cru cacheado
│   └── processed/      # CSV/Parquet limpos
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
- **Kaggle (stefanoleone992):** "FIFA 15–23 complete player dataset", ~110 atributos por jogador, todos os updates.
- **HuggingFace (`jsulz/FIFA23`)** e similares: mesmo schema.
- Útil quando a edição jogada é antiga: evita scraping inteiro.

### Ética/robots
- Conforme nota pública de datasets derivados do SoFIFA, o **`robots.txt` do sofifa.com não restringia a coleta** de dados de players/coaches/teams no momento daquelas coletas. Ainda assim: **rate-limit, cache local e User-Agent honesto** são obrigatórios. Reconferir o `robots.txt` atual antes de scrapar em volume.

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
    candidatos = jogadores da edição-FIFA cuja posição == position_norm
    para cada candidato, calcular score de distância ao perfil:
        + match de nacionalidade (se moda existir)        × peso_nac
        + match de liga (se moda existir)                 × peso_liga
        + |idade - age_mean| normalizado                  × peso_idade
        + |value_eur - market_value_mean| normalizado     × peso_valor
    ordenar por score; retornar top-N
```
- Parâmetros categóricos descartados no estágio 2 (moda `None`) **simplesmente não entram** no score.
- Normalizar idade e valor (z-score ou min-max) antes de somar, senão o valor domina por escala.
- Pesos configuráveis; default razoável: valor e posição altos, nacionalidade média, liga baixa.
- `from_club_mode` raramente sobrevive ao filtro de moda — não depender dele.

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
3. **Estágio 2** (perfilagem) — `profile/aggregate.py`. **Próximo passo.**
4. **Estágio 3:** dataset pronto do SoFIFA FIFA 22 (Kaggle) + ranqueamento por distância ao perfil.
5. Generalizar: múltiplos clubes, seletor de versão, parâmetros via CLI.
6. (Futuro) scraping ao vivo do SoFIFA para FC 24/25/26; dashboard.

---

## 14. Decisões tomadas

| Decisão | Escolha |
|---------|---------|
| **D1** — scraper TM | `requests` + BeautifulSoup direto (ScraperFC não tem método de transfers por clube) |
| **D2** — eixo de valor | **Fee paga** (não valor de mercado). `market_value` removido do schema. A busca no SoFIFA usará `value_eur` um pouco menor que a média de fee das contratações definitivas. |
| **D3** — granularidade | Posição fina com fallback para linha (config `min_sample`, default 3) |
| **D5** — janela | 7 anos de histórico (configurável via `--history`) |
| **D6** — SoFIFA | Dataset Kaggle para FIFA 22; scraping ao vivo como fallback para edições recentes |
| **transfer_type** | Campo adicionado: `"permanent"` \| `"loan"` \| `"free"`. `fee_mean` no Estágio 2 considera só permanent+free onde fee não é None. |

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
- `"End of loan30/06/YYYY"` — data colada, capturada antes do regex numérico
- `td.hauptlink` para pegar link do clube de origem (não o logo)
- `loan fee:` com valor numérico é empréstimo com taxa, não contratação definitiva
