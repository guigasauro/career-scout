# career-scout

Olheiro para o **Modo Carreira do FIFA / EA FC**, baseado no histórico real de contratações do clube.

Ele aprende no [Transfermarkt](https://www.transfermarkt.com) o *padrão de contratação* de um clube: posições, idade, nacionalidade, liga de origem e valor pago. Depois busca no [SoFIFA](https://sofifa.com) jogadores parecidos na edição do jogo que você está jogando.

> Exemplo: se nos últimos 5 anos o clube contratou **zagueiros franceses de ~23 anos por ~€10M**, o career-scout ranqueia os zagueiros da edição escolhida pela semelhança com esse perfil.

## Como funciona

```
Transfermarkt ──► Perfilagem ──► SoFIFA
 chegadas do clube   perfil por posição   candidatos ranqueados
```

1. **Extração:** raspa as chegadas do clube nas temporadas anteriores à edição do jogo, sem retornos de empréstimo, promoções da base e duplicatas.
2. **Perfilagem:** para cada posição, calcula a média de idade e de valor pago e a moda de nacionalidade e de liga. A moda só entra quando aparece pelo menos 2 vezes.
3. **Matching:** dá uma nota de semelhança entre 0 e 1 a cada jogador da edição. A nota é ranqueada, e não um filtro, então sempre há resultados. Opcionalmente:
   - premia potencial alto;
   - no **modo reforço**, ancora as sugestões no overall dos titulares do elenco.

## Instalação

Requer Python 3.10+.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Dados do SoFIFA (não inclusos)

Os dados de jogadores **não são distribuídos neste repositório**. Coloque-os em `data/raw/`:

- **FIFA 15–22:** baixe o dataset [FIFA 22 complete player dataset](https://www.kaggle.com/datasets/stefanoleone992/fifa-22-complete-player-dataset) (Kaggle) e copie os `players_15.csv` … `players_22.csv` para `data/raw/`.
- **FIFA 23 / FC 24–26:** gere com o scraper incluso. O SoFIFA fica atrás de um desafio Cloudflare, então o scraper usa cookies da sua sessão:
  1. Abra https://sofifa.com/players no navegador e espere passar a verificação.
  2. Copie o cookie `cf_clearance` e o `User-Agent` do navegador (DevTools).
  3. Salve em `data/raw/sofifa_cookies.json`:
     ```json
     { "cookies": { "cf_clearance": "..." }, "user_agent": "Mozilla/5.0 ..." }
     ```
  4. Rode `python -m career_scout.match.sofifa_scraper --edition 26`.

  O cookie expira em algumas horas. O scraper avisa quando for preciso renovar.

As chegadas do Transfermarkt são raspadas sob demanda e ficam em cache em `data/processed/`.

## Uso

```bash
fastapi dev career_scout/api.py
```

Abra http://localhost:8000 e escolha edição → país → liga → clube.

São 150 clubes das 5 grandes ligas, mapeados entre Transfermarkt e SoFIFA em `data/club_mapping.json`. Para mapear outras ligas, use `seed_clubs.py`.

## Testes

```bash
pytest
```

## Aviso

Projeto pessoal e não comercial. O scraping usa cache agressivo e rate-limit. Respeite os termos de uso do Transfermarkt e do SoFIFA e não redistribua os dados coletados. Não é afiliado à EA, ao Transfermarkt nem ao SoFIFA.

## Licença

[MIT](LICENSE)
