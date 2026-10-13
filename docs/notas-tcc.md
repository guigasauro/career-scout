# Notas para o TCC — recomendação de reforços a partir de deficiências estatísticas

> Diário de pesquisa do módulo de análise do career-scout (`career_scout/analytics/`). Registra decisões,
> protocolo e resultados na ordem em que aconteceram, inclusive os negativos. Detalhes de implementação
> ficam no `CLAUDE.md` §18; aqui fica o que entra no texto do TCC.

## 1. Pergunta de pesquisa

Dá para recomendar contratações a partir das **deficiências estatísticas de um time na temporada**
— comparando o time com um patamar de referência, ligando cada deficiência às funções em campo que a
resolvem e ranqueando jogadores de várias ligas pelas estatísticas dessas funções?

Pergunta operacional da validação: **as contratações que os clubes fizeram de verdade na janela
seguinte aparecem nas listas do método mais do que apareceria um jogador qualquer?**

## 2. Dados

### 2.1 Fontes consideradas (out/2026)

| Fonte | Decisão | Motivo |
|---|---|---|
| **StatsBomb Open Data** | **usada** | Dados de evento completos (cada passe, chute com xG, pressão, duelo, condução, com coordenadas). Licença permite uso não comercial/pesquisa com crédito. github.com/statsbomb/open-data |
| **Transfermarkt** | usada | Idade, valor de mercado da época, contratações e valores pagos. Coleta com cache e pausa entre páginas. |
| FBref | descartada | Perdeu xG e métricas avançadas em 20/01/2026, de todas as temporadas (a Opta exigiu apagar). Sobrou estatística básica. |
| Understat | descartada | `robots.txt` com `Disallow: /` para todos os robôs. |
| Sofascore | descartada (por ora) | Termos de uso (seções 2.8 e 2.9) proíbem extração de parte substancial do banco e coleta automatizada sem consentimento explícito. Pedido de autorização redigido (`email_sofascore.md`, fora do git). |
| Opta / StatsBomb / Wyscout pagos | fora do escopo | Licenças estimadas em €15–80 mil/ano por clube (sem preço oficial). |

### 2.2 Cobertura usada: temporada 2015/16

| Liga | Jogos no StatsBomb | Situação |
|---|---|---|
| Premier League | 380/380 | completa |
| La Liga | 380/380 | completa |
| Serie A | 380/380 | completa |
| Ligue 1 | 377/380 | 3 jogos ausentes (PSG fica com 93 pts em vez de 96; Gazélec 34 em vez de 37) |
| Bundesliga | 34 | **excluída**: só os jogos do Leverkusen; sem a liga inteira não há tabela nem percentil |

As tabelas de classificação geradas a partir dos placares foram conferidas contra as reais
(Leicester 81, Arsenal 71, Tottenham 70…; Barcelona 91, Real 90…; Juventus 91, Napoli 82…).

### 2.3 Integração com o Transfermarkt

- Jogadores do StatsBomb casados com o elenco de cada clube no TM por nome (sobrenome + inicial pesam
  mais que o primeiro nome): Premier League 548/550, La Liga 531/539, Serie A 550/551, Ligue 1 573/574.
- **Auditoria do mapeamento de clubes** (título real da página de cada id do TM × nome esperado):
  19 clubes apontavam para outro clube (ex.: Everton → Hertha BSC II, Mainz → Copenhague, Sampdoria →
  Spartak Moscou, Deportivo → Montpellier). Todos corrigidos. Lição metodológica: mapeamento feito pela
  busca automática precisa de verificação independente.

## 3. Método

### 3.1 Estatísticas
Eventos de cada jogo → somas por jogador (minutos pela escalação) e por time (a favor e contra).
Métricas por 90 minutos; ações defensivas ajustadas pela posse do time (escala para 50% de posse do
adversário). Simplificações assumidas:
- passe progressivo = passe certo que avança ≥10 jardas (não é a definição da Opta);
- posse aproximada pela fatia de passes do jogo;
- gols contra fora das estatísticas de chute (mas dentro da classificação);
- **não há dados físicos** (sprints, distância): StatsBomb é dado de evento, não de rastreamento.

### 3.2 Deficiências do time
16 métricas por jogo em três blocos (ataque, criação, defesa). Para cada uma: percentil na liga e
distância até o patamar de referência em desvios-padrão da liga (negativo = deficiência).
- Modo **tier** (padrão): referência = média dos times de uma faixa da tabela (Top 4 por padrão).
- Modo **relative**: distância contra o nível geral do próprio time (as áreas mais fracas dele).
- Métricas de **estilo** (posse, % de passes) não geram pedido de reforço: o Leicester foi campeão com
  pouca posse.

### 3.3 Da deficiência ao jogador
Cada deficiência aponta para **perfis** de função (ex.: xG sofrido → zagueiro · marcação e volante ·
desarmes; passes progressivos → volante/meia/zagueiro · construção). Cada perfil tem estatísticas por
90 com pesos. Score do candidato = percentil médio ponderado nessas estatísticas, **calculado dentro da
liga do jogador**, multiplicado por um fator de força da liga (coeficiente UEFA de países ao fim de
2015/16: Espanha 105,7; Inglaterra 76,3; Itália 70,4; França 52,7; peso 0,3 → fator 1,00 a 0,85).
Elegíveis: ≥900 minutos e ≥30% dos minutos na função.

**Os pesos dos perfis e o peso da força da liga foram escolhidos pelo autor, não calibrados.**

### 3.4 Orçamento (experimento 2)
Orçamento do clube = percentil 90 dos valores pagos em compras definitivas nas 3 temporadas anteriores
(2013/14–2015/16; com menos de 3 compras pagas, o maior valor). Teto = orçamento × 1,25. Compara-se com o
valor de mercado do candidato no TM na época. Só usa informação anterior à janela prevista.

## 4. Protocolo de validação

- **Gabarito**: chegadas da janela de **verão de 2016** no TM para cada time das 4 ligas (sem retornos
  de empréstimo; compras, livres e empréstimos).
- **Avaliáveis**: contratados que jogaram ≥900 minutos em uma das 4 ligas em 2015/16 e não eram do
  próprio time. De 832 chegadas, **215** são avaliáveis (26%); as demais vieram de outras ligas (inclusive
  a Bundesliga), da base ou jogaram pouco.
- **Medidas**, sempre comparadas ao **acaso** (um jogador qualquer do mesmo pool):
  1. a função do contratado está entre as pedidas pelo método?
  2. ele aparece no top 10 / top 30 de algum perfil pedido?
  3. sua posição relativa nos perfis pedidos é melhor que nos outros perfis da mesma função?
- **Separação**: desenvolvimento = times de Premier League e Serie A (117 avaliáveis);
  teste = times de La Liga e Ligue 1 (98). Critério de escolha fixado **antes** de rodar: maior ganho
  sobre o acaso no top 30. O teste é rodado uma vez.

## 5. Resultados

### 5.0 Linha de base (todos os times, antes da separação)
Patamar Top 4, deficiências com distância ≤ −0,5, força da liga 0,3.

| Medida | Método | Acaso |
|---|---|---|
| Função pedida | 84% | 83% |
| Top 10 de um perfil pedido | 6% | 8% |
| Top 30 | 20% | 22% |
| Posição relativa: perfis pedidos × outros perfis (0 = topo) | 0,45 | 0,50 |

Diferença de perfil 0,055, IC95% bootstrap [−0,011; 0,119], teste dos sinais p = 0,07 (n = 89):
não significativa. Com a **média da liga** como referência (Top 4 trocado pelos 20 times): também no
acaso (função 65% × 61%; top 30 12% × 14%).

Observação: Kanté (Chelsea, 13º entre os volantes) e Mané (Liverpool, 3º no perfil de infiltração) são
acertos, mas **os dois influenciaram ajustes do método** (o perfil de infiltração foi criado sabendo
do Mané), então não contam como evidência.

### 5.1 Experimento 1 — patamar e foco (confirmatório)

| Variante | Desenvolvimento: ganho no top 30 | Teste: ganho no top 30 |
|---|---|---|
| A — Top 4, distância ≤ −0,5 | −0,2 pts | −3,4 pts (IC95% −11,4 a +4,8) |
| **B — Top 4, 3 maiores deficiências** (escolhida) | **+3,6 pts** | **−6,5 pts (IC95% −9,9 a −2,3)** |
| C — relativo, 3 maiores | +0,7 pts | — |
| D — relativo, 5 maiores | −1,1 pts | — |

**Conclusão**: o ganho do desenvolvimento não se repetiu no teste — era ruído de amostra pequena.
Nenhuma variante supera o acaso. A separação de teste evitou reportar um ganho falso.

Pista: no teste, os contratados aparecem nas listas **menos** que um jogador qualquer. As listas
premiam números altos, típicos de jogadores caros ou de clubes grandes, e times médios compram dentro
do orçamento → motivou o experimento 2.

**Depois deste experimento, La Liga e Ligue 1 deixam de ser um conjunto de teste limpo.**

### 5.2 Experimento 2 — filtro de orçamento (exploratório)
_Ver seção a seguir; preenchida após a rodada._

## 6. Limitações e ameaças à validade

- **Uma temporada só** (2015/16) com dados de evento abertos e completos; o conjunto de teste já foi
  usado no experimento 1 → experimentos seguintes são exploratórios.
- **Gabarito ruidoso**: contratação real depende de orçamento, disponibilidade, empresários, vontade do
  jogador e oportunidade de mercado — não só da melhor opção estatística.
- **Cobertura**: 26% das contratações são avaliáveis; a Bundesliga ficou de fora.
- **Ajustes guiados por casos conhecidos** (Kanté, Mané) antes da validação sistemática.
- **Pesos não calibrados** (perfis, força da liga) e coeficiente UEFA como proxy de força da liga
  (mede copas europeias, não a liga inteira).
- **Sem dados físicos** e sem contexto tático (sistema de jogo, papel do jogador no time).

## 7. Reprodutibilidade

```bash
source transfer-advisor-venv/bin/activate
python -m career_scout.analytics.statsbomb premier-league-2015-16   # idem la-liga, serie-a, ligue-1
python -m career_scout.analytics.market premier-league-2015-16
python -m career_scout.analytics.deficiencies premier-league-2015-16 Chelsea
python -m career_scout.analytics.recommend premier-league-2015-16 Chelsea
python -m career_scout.analytics.validate 2015-16                    # linha de base
python -m career_scout.analytics.validate 2015-16 --leagues premier-league,serie-a --top-k 3   # exp. 1 (dev, B)
python -m career_scout.analytics.validate 2015-16 --leagues la-liga,ligue-1 --top-k 3          # exp. 1 (teste, B)
python -m career_scout.analytics.validate 2015-16 --budget          # exp. 2
```

## 8. Referências

- StatsBomb Open Data — github.com/statsbomb/open-data
- Transfermarkt — transfermarkt.com
- Coeficientes de países da UEFA (temporada 2016) — comp.uefa.com/v2/coefficients
- Termos e condições do Sofascore — sofascore.com/terms-and-conditions
- Remoção das estatísticas avançadas do FBref — sports-reference.com/blog (jan/2026)
