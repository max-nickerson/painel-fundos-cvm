# Atribuição profunda dos vencedores da rodada 1

Data: out/2026. Código: `atribuicao_fundos.py` (atribuição e testes) e `ideias_atribuicao.py` (4 fundos melhorados).
Resultados: `resultado/atribuicao.pkl` (por fundo: `contrib` diária por ativo e `trades` com cada negócio), `resultado/atribuicao_saida.txt`
(todas as tabelas) e `resultado/ideias_atribuicao.pkl`.

**Como ler os números.** Cada série foi reproduzida com a lógica copiada dos módulos originais; a checagem bate com o original até 1e-16
(carry, termo, vol, commodities, multi). Os valores aqui são **excesso BRUTO sobre o CDI** (sem taxa de gestão). O `ranking.csv` da
rodada 1 foi gerado com uma versão antiga do `rodar.py`, com 0,5–2% de administração e 20% de performance (confira `r["fundo"].adm` no pkl).
Por isso os números de lá são menores: no carry, +8,8 pp no ranking contra +12,5 pp a.a. de excesso bruto aqui.
"Contribuição em pp" é a soma do excesso diário (pesado pela posição) e não leva juros compostos.
"Negócio" é um episódio contínuo de posição com o mesmo sinal num ativo.

## Resumo para o dono do fundo

| Fundo | O que REALMENTE gerou o resultado | Replicável? |
|---|---|---|
| 11 Carry de moedas | 1/3 do ganho OOS veio de **comprado em lira turca de jul/2023 a hoje, com 55–75% do PL** (+32,6 pp: carry de +67,6 pp contra −34,9 pp de desvalorização). Outro 1/4 veio de **vendido em iene desde 2016** (+17,5 pp OOS). O "teto de 25% por moeda" não funcionou porque era aplicado ANTES do vol-alvo, que multiplica a carteira por até 3. | Em parte. Sem a TRY sobram +9,7 pp a.a.; em G10+LatAm sobram +10 pp. Com metade do carry, só +2,7 pp. Antes de 2021 o fundo dava ~0 (IS −0,5 pp a.a.). |
| 06 Eurobonds | Quase tudo é **uma safra**: bonds comprados em mai–jul/2023 a 61–86 (MC Brazil/Acelen, Simpar, Movida, Hidrovias, BRF 2050, Globo, Açu), que voltaram para 84–99. As entradas de 2023T2–T3 somam +12,2 pp dos +13,5 pp desde 2021. A parcela de preço/spread é +4,1 pp e a de carrego +9,4 pp. Fora do IS, a Andrade Gutierrez (bond a 23–40, negócios esparsos) responde por 45% do OOS. | A tese "comprar HY brasileiro em stress e carregar" é replicável, mas a amostra tem 1 ciclo e preços FINRA esparsos. |
| 02 Termo | **Artefato de medição.** A taxa sai do último negócio a termo contra o fechamento à vista, que acontecem em horários diferentes. O filtro "taxa > CDI+0,5%" seleciona o ruído. Travando a taxa pelo VWAP à vista, o excesso OOS cai de +2,4 para +0,6 pp a.a.; executando no dia seguinte, para +0,2 pp. O prêmio estrutural do termo existe (mediana CDI+0,7 pp), mas a capacidade é de ~R$ 4 mi de PL. | Não como fundo. |
| 15 Prêmio de vol | **É beta de S&P.** O beta OOS é 0,76, e o excesso que esse beta explica (7,55 pp) é maior que o excesso do fundo (7,41 pp). Com o beta vendido em SPY, o put-write rende +0,7 pp OOS. O filtro VVIX evitou o Volmageddon de fev/2018 (o filtro só com VIX3M perderia −27 pp), mas não evitou abr/2025 (−11 pp, atraso de 1 dia). 2023 sozinho deu +27 pp; 2022 deu −18 pp. | Como beta, sim. Como alfa, não. |
| 12 Commodities | **Ouro, prata e urânio comprados.** No OOS: GLD +7,8, SLV +7,2, URA +5,9 pp. 2025 (alta de ouro, prata e platina) deu +18 pp dos +22 pp do OOS. Fora 2025, ~0. | É um prêmio de momento com Sharpe baixo (IS ~0). |
| 20 Multi | **73% do OOS vem do termo** (o artefato), 20% do box e 6% da conversão, com alavancagem de 3,75x (vol-alvo de 6% sobre livros quase sem vol). Os outros 11 livros somam ~0. O carry e o vol, que ganharam, quase não entram (IR IS ≤ 0 ou peso 0,1–0,3%). | Não: herda o artefato do termo. |

---

## 11 Carry de moedas (n=3, sem filtro, comprado/vendido, teto 25%, vol-alvo 8%)

**Mecânica real.** Todo fim de mês o fundo compra as 3 moedas de maior juro de política (BIS) e vende as 3 de menor juro contra o dólar.
Os pesos são pelo inverso da vol, com teto de 25% e alvo de 8% de vol.
**Bug de desenho:** o `clip(-teto, teto)` vem ANTES do `vol_alvo`, que escala a carteira em até 3x.
A lira turca tem vol diária baixa (câmbio administrado), recebe peso máximo, e o vol-alvo multiplica a carteira.
Resultado: a TRY ficou com 55% do PL em média desde jul/2023 e **75% do PL em 2025–26** (tabela de posição trimestral abaixo).

### Contribuição por moeda (pp, soma do excesso diário; "OOS" = 2021+)
|        |   spot pp |   carry pp |   total pp |   spot OOS |   carry OOS |   total OOS |   % dias comprado OOS |   % dias vendido OOS |
|:-------|----------:|-----------:|-----------:|-----------:|------------:|------------:|----------------------:|---------------------:|
| TRY    |     -94   |      102.4 |        7.7 |      -53.3 |        73.8 |        20.4 |                  90   |                  0   |
| JPY    |      14.5 |       10.6 |       24.3 |       12.3 |         5.4 |        17.5 |                   0   |                100   |
| BRL    |     -10.2 |       18.8 |        8.2 |        4.1 |         4.9 |         8.9 |                  65.2 |                  0   |
| MXN    |      -2.8 |       11   |        7.9 |       -0.3 |         6.3 |         5.8 |                  73.3 |                  0   |
| COP    |       4   |        1.6 |        5.6 |        4   |         1.6 |         5.6 |                  30.9 |                  0   |
| EURUSD |       6.6 |        0.4 |        6.8 |        5.4 |         0.2 |         5.6 |                   0   |                 17.4 |
| CHF    |     -25.5 |       11.8 |      -14.6 |       -2.1 |         6.2 |         3.9 |                   0   |                100   |
| HUF    |      -0   |        6.5 |        6.3 |        1.1 |         2.4 |         3.4 |                  26   |                  0   |
| SEK    |       3.6 |        3   |        6.3 |        2.3 |         0   |         2.3 |                   0   |                 11.5 |
| NOK    |       0   |        0   |        0   |        0   |         0   |         0   |                   0   |                  0   |
| CAD    |       2.2 |       -0.2 |        1.9 |        0   |         0   |         0   |                   0   |                  0   |
| AUDUSD |       0   |        0   |        0   |        0   |         0   |         0   |                   0   |                  0   |
| NZDUSD |       0   |        0   |        0   |        0   |         0   |         0   |                   0   |                  0   |
| GBPUSD |      -1.2 |       -0.3 |       -1.7 |        0   |         0   |         0   |                   0   |                  0   |
| IDR    |       6.2 |        1.2 |        7.3 |        0   |         0   |         0   |                   0   |                  0   |
| KRW    |       0   |        0   |        0   |        0   |         0   |         0   |                   0   |                  0   |
| INR    |      -8.8 |        4   |       -4.9 |        0   |         0   |         0   |                   0   |                  0   |
| ILS    |      -0   |       -0   |       -0.1 |        0   |         0   |         0   |                   0   |                  0   |
| CLP    |       0   |        0   |        0   |        0   |         0   |         0   |                   0   |                  0   |
| CZK    |      -1.5 |        1.3 |       -0.4 |        0   |         0   |         0   |                   0   |                  0   |
| PLN    |       0   |        0   |        0   |        0   |         0   |         0   |                   0   |                  0   |
| CNY    |       0   |        0   |        0   |        0   |         0   |         0   |                   0   |                  0   |
| PHP    |       0   |        0   |        0   |        0   |         0   |         0   |                   0   |                  0   |
| THB    |      -4.4 |        3.9 |       -0.7 |       -3.9 |         3.8 |        -0.2 |                   0   |                 71.2 |
| ZAR    |      -4.3 |       11.8 |        7.1 |       -0.9 |         0.6 |        -0.3 |                  11.6 |                  0   |

### Por ano: spot x carry
|      |   spot |   carry |   custos+alav |   total |
|-----:|-------:|--------:|--------------:|--------:|
| 2005 |    0   |     0   |           0   |     0   |
| 2006 |  -17.7 |     6.8 |          -0.6 |   -11.6 |
| 2007 |   -3.3 |     7.1 |          -0.5 |     3.3 |
| 2008 |  -14.6 |     4.1 |          -0.2 |   -10.7 |
| 2009 |    5.1 |     4.3 |          -0.3 |     9.1 |
| 2010 |   -6.8 |     5.6 |          -0.8 |    -1.9 |
| 2011 |  -15   |     3.9 |          -0.5 |   -11.6 |
| 2012 |   -2   |     4.9 |          -0.9 |     2   |
| 2013 |    0.8 |     4.7 |          -0.7 |     4.8 |
| 2014 |   15.1 |     4.8 |          -0.7 |    19.2 |
| 2015 |  -16.9 |     4.3 |          -0.2 |   -12.9 |
| 2016 |    8.2 |     5.1 |          -0.4 |    12.9 |
| 2017 |   -9.3 |     6   |          -0.6 |    -3.9 |
| 2018 |  -11   |     6.2 |          -0.5 |    -5.3 |
| 2019 |   -3.1 |     9.5 |          -0.7 |     5.6 |
| 2020 |  -14.2 |     5.2 |          -0.6 |    -9.6 |
| 2021 |   -6.7 |     7.1 |          -0.8 |    -0.4 |
| 2022 |    5.2 |     6.2 |          -0.6 |    10.8 |
| 2023 |   -0.9 |    11.9 |          -0.7 |    10.4 |
| 2024 |  -11.5 |    28.3 |          -0.7 |    16.1 |
| 2025 |  -16   |    27.7 |          -0.7 |    11   |
| 2026 |   -1.2 |    24   |          -0.5 |    22.3 |

O padrão é o do carry clássico: o carry rende 4–7 pp/ano, e o spot devolve parte ou tudo (2006, 2008, 2011, 2015, 2020).
O OOS foi bom porque, de 2022 a 2026, o diferencial ficou enorme (TRY 40–50%, BRL 13–15%, COP 9–13%, contra JPY 0% e CHF ~1%),
e o spot só devolveu parte dele.

### 10 melhores e 10 piores negócios (histórico inteiro)
| ativo   | lado     | entrada    | saida      |   dias |   peso_medio |   retorno % |   contrib pp |   contrib OOS pp |   spot pp |   carry pp |   dif juros médio % |
|:--------|:---------|:-----------|:-----------|-------:|-------------:|------------:|-------------:|-----------------:|----------:|-----------:|--------------------:|
| TRY     | comprado | 2023-07-05 | 2026-10-14 |    824 |         0.55 |       73.13 |        32.62 |            32.62 |    -34.87 |      67.61 |               36.57 |
| JPY     | vendido  | 2016-10-04 | 2026-10-14 |   2521 |         0.36 |       82.82 |        16.16 |            17.47 |      8.77 |       7.81 |               -2.4  |
| JPY     | vendido  | 2006-04-04 | 2015-01-02 |   2203 |         0.31 |        0.43 |         8.14 |             0    |      5.69 |       2.8  |               -1.17 |
| SEK     | vendido  | 2014-11-04 | 2020-06-01 |   1402 |         0.31 |       29.88 |         7.84 |             0    |      5.49 |       2.56 |               -1.4  |
| IDR     | comprado | 2013-10-02 | 2014-02-03 |     85 |         0.16 |       -2.25 |         6.79 |             0    |      6.54 |       0.27 |                5.1  |
| CZK     | vendido  | 2012-07-03 | 2015-01-02 |    629 |         0.33 |       10.61 |         6.76 |             0    |      6.84 |       0.03 |               -0.02 |
| ZAR     | comprado | 2007-01-04 | 2010-12-01 |    986 |         0.18 |       36.48 |         6.5  |             0    |      1.72 |       4.88 |                7.2  |
| COP     | comprado | 2025-09-03 | 2026-10-14 |    281 |         0.19 |       32.73 |         6.06 |             6.06 |      5.09 |       0.98 |                4.77 |
| BRL     | comprado | 2024-11-04 | 2026-10-14 |    487 |         0.2  |       32.18 |         5.68 |             5.68 |      2.91 |       2.8  |                7.13 |
| EURUSD  | vendido  | 2021-10-04 | 2022-10-03 |    252 |         0.37 |       17.57 |         5.59 |             5.59 |      5.42 |       0.23 |               -0.72 |

| ativo   | lado     | entrada    | saida      |   dias |   peso_medio |   retorno % |   contrib pp |   contrib OOS pp |   spot pp |   carry pp |   dif juros médio % |
|:--------|:---------|:-----------|:-----------|-------:|-------------:|------------:|-------------:|-----------------:|----------:|-----------:|--------------------:|
| TRY     | comprado | 2014-02-04 | 2022-12-01 |   2224 |         0.23 |      -67    |       -27.5  |           -12.25 |    -48.28 |      21.1  |               11.33 |
| CZK     | vendido  | 2006-04-04 | 2007-12-03 |    420 |         0.3  |      -20.59 |        -7.17 |             0    |     -8.38 |       1.28 |               -2.57 |
| CHF     | vendido  | 2006-04-04 | 2009-08-03 |    839 |         0.25 |      -17.39 |        -6.62 |             0    |     -8.01 |       1.51 |               -1.42 |
| CHF     | vendido  | 2010-07-02 | 2014-10-01 |   1070 |         0.34 |      -14.57 |        -4.55 |             0    |     -4.27 |      -0.08 |                0.06 |
| BRL     | comprado | 2013-04-02 | 2017-10-02 |   1136 |         0.18 |       -8.03 |        -3.91 |             0    |    -10.17 |       6.39 |                8.07 |
| CHF     | vendido  | 2015-01-05 | 2026-10-14 |   2962 |         0.38 |       -1.45 |        -3.38 |             3.86 |    -13.25 |      10.36 |               -2.33 |
| INR     | comprado | 2011-10-04 | 2012-05-01 |    145 |         0.29 |       -8.86 |        -2.49 |             0    |     -3.44 |       0.98 |                5.82 |
| INR     | comprado | 2012-09-05 | 2014-08-01 |    479 |         0.3  |        1.33 |        -2.36 |             0    |     -5.34 |       3.06 |                5.33 |
| CAD     | vendido  | 2009-05-04 | 2010-07-01 |    294 |         0.32 |      -12.22 |        -2.31 |             0    |     -2.21 |      -0.05 |                0.14 |
| SEK     | vendido  | 2006-04-04 | 2006-07-03 |     63 |         0.26 |       -5.91 |        -1.74 |             0    |     -1.91 |       0.19 |               -2.88 |

### 10 melhores e 10 piores no OOS (coluna "contrib OOS pp")
| ativo   | lado     | entrada    | saida      |   dias |   peso_medio |   retorno % |   contrib pp |   contrib OOS pp |   spot pp |   carry pp |   dif juros médio % |
|:--------|:---------|:-----------|:-----------|-------:|-------------:|------------:|-------------:|-----------------:|----------:|-----------:|--------------------:|
| TRY     | comprado | 2023-07-05 | 2026-10-14 |    824 |         0.55 |       73.13 |        32.62 |            32.62 |    -34.87 |      67.61 |               36.57 |
| JPY     | vendido  | 2016-10-04 | 2026-10-14 |   2521 |         0.36 |       82.82 |        16.16 |            17.47 |      8.77 |       7.81 |               -2.4  |
| COP     | comprado | 2025-09-03 | 2026-10-14 |    281 |         0.19 |       32.73 |         6.06 |             6.06 |      5.09 |       0.98 |                4.77 |
| BRL     | comprado | 2024-11-04 | 2026-10-14 |    487 |         0.2  |       32.18 |         5.68 |             5.68 |      2.91 |       2.8  |                7.13 |
| EURUSD  | vendido  | 2021-10-04 | 2022-10-03 |    252 |         0.37 |       17.57 |         5.59 |             5.59 |      5.42 |       0.23 |               -0.72 |
| MXN     | comprado | 2022-12-02 | 2025-09-02 |    688 |         0.27 |       19.66 |         5.24 |             5.24 |      1.24 |       4.13 |                5.54 |
| CHF     | vendido  | 2015-01-05 | 2026-10-14 |   2962 |         0.38 |       -1.45 |        -3.38 |             3.86 |    -13.25 |      10.36 |               -2.33 |
| HUF     | comprado | 2022-08-02 | 2024-02-01 |    378 |         0.2  |       23.87 |         3.44 |             3.44 |      1.12 |       2.36 |                7.95 |
| BRL     | comprado | 2021-09-02 | 2023-07-03 |    460 |         0.18 |       21.96 |         3.2  |             3.2  |      1.15 |       2.1  |                6.73 |
| SEK     | vendido  | 2021-10-04 | 2022-06-01 |    167 |         0.24 |       11.35 |         2.31 |             2.31 |      2.3  |       0.03 |               -0.23 |

| ativo   | lado     | entrada    | saida      |   dias |   peso_medio |   retorno % |   contrib pp |   contrib OOS pp |   spot pp |   carry pp |   dif juros médio % |
|:--------|:---------|:-----------|:-----------|-------:|-------------:|------------:|-------------:|-----------------:|----------:|-----------:|--------------------:|
| TRY     | comprado | 2014-02-04 | 2022-12-01 |   2224 |         0.23 |      -67    |       -27.5  |           -12.25 |    -48.28 |      21.1  |               11.33 |
| THB     | vendido  | 2022-10-04 | 2026-10-14 |   1011 |         0.34 |       -3.71 |        -0.89 |            -0.89 |     -4.48 |       3.74 |               -2.73 |
| COP     | comprado | 2024-02-02 | 2024-10-01 |    167 |         0.21 |       -4.42 |        -0.48 |            -0.48 |     -1.07 |       0.61 |                4.46 |
| ZAR     | comprado | 2017-10-03 | 2021-09-01 |    986 |         0.2  |       11.88 |         2.29 |            -0.28 |     -0.97 |       3.38 |                4.3  |
| MXN     | comprado | 2017-08-02 | 2022-07-01 |   1238 |         0.26 |       15.46 |         2.65 |             0.59 |     -4.07 |       6.89 |                5.37 |
| THB     | vendido  | 2022-08-02 | 2022-09-01 |     23 |         0.37 |        1.91 |         0.67 |             0.67 |      0.62 |       0.06 |               -1.69 |
| SEK     | vendido  | 2021-10-04 | 2022-06-01 |    167 |         0.24 |       11.35 |         2.31 |             2.31 |      2.3  |       0.03 |               -0.23 |
| BRL     | comprado | 2021-09-02 | 2023-07-03 |    460 |         0.18 |       21.96 |         3.2  |             3.2  |      1.15 |       2.1  |                6.73 |
| HUF     | comprado | 2022-08-02 | 2024-02-01 |    378 |         0.2  |       23.87 |         3.44 |             3.44 |      1.12 |       2.36 |                7.95 |
| CHF     | vendido  | 2015-01-05 | 2026-10-14 |   2962 |         0.38 |       -1.45 |        -3.38 |             3.86 |    -13.25 |      10.36 |               -2.33 |

### Os grandes negócios, com contexto
- **TRY comprada, 05/07/2023 → hoje (+32,6 pp; carry +67,6, spot −34,9; diferencial médio 36,6%).** Depois da eleição de maio/2023, Şimşek
  assumiu a Fazenda e Erkan o BC turco. A política virou ortodoxa: juro de 8,5% para 15% em 22/jun/2023, 30% em set, 42,5% em dez e 50% em mar/2024.
  A lira saiu de uma desvalorização descontrolada (~21→26/USD em junho) para uma depreciação administrada de ~1,5–2% ao mês, contra um carry de
  ~3–4% ao mês. Esse é o "carry trade da lira" de 2024, o melhor carry de emergentes daquele ano.
  O pior momento foi a prisão de İmamoğlu em 19/03/2025 (lira −3 a −4% no fechamento, −10% intradiário, BC subiu o juro de emergência para 46%).
  **Ressalva:** com 55–75% do PL, foi uma aposta de uma moeda só, não um fundo de carry.
- **TRY comprada, 02/2014 → 12/2022 (−27,5 pp; −12,3 pp dentro do OOS).** O lado ruim da mesma moeda. Em set–dez/2021 Erdoğan forçou cortes de
  19% para 14% com inflação de 20%+ e a lira perdeu ~44% no ano. Em 2021 a TRY custou −7,6 pp e o fundo fechou o ano em −0,4.
- **JPY vendido, 10/2016 → hoje (+17,5 pp no OOS; spot +12,3, carry +5,4).** O BoJ manteve juro de −0,1% e controle da curva até mar/2024,
  enquanto o Fed foi de 0,25% a 5,5%. USDJPY: 115 (jan/22) → 151 (out/22) → 161 (jul/24). O desmonte do carry do iene em jul–ago/2024
  (USDJPY 161→142) devolveu parte, mas o negócio continuou positivo.
- **EUR vendido, 10/2021 → 10/2022 (+5,6 pp, quase tudo spot).** Choque de energia da guerra na Ucrânia mais a divergência Fed x BCE.
  O EURUSD foi de 1,16 a 0,97 (quebrou a paridade em jul/2022).
- **BRL comprado, 09/2021 → 07/2023 (+3,2 pp) e 11/2024 → hoje (+5,7 pp).** No primeiro, o BCB subiu a Selic de 2% para 13,75%. No segundo,
  a compra foi feita a ~5,8 R$/USD, logo antes do novo ciclo até 15%; o real voltou para a casa de 5,3–5,4 em 2025–26.
- **MXN comprado, 12/2022 → 09/2025 (+5,2 pp; carry 4,1).** O "super peso": Banxico a 11,25% e o nearshoring levaram o MXN de 19,5 para 16,3 em 2023.
  Apanhou na eleição de jun/2024 (supermaioria do Morena) e no desmonte do iene.
- **COP comprado, 09/2025 → hoje (+6,1 pp, 5,1 de spot)** e **HUF comprado, 08/2022 → 02/2024 (+3,4 pp).** Neste, o MNB tinha base de 13% e
  depósito efetivo de 18% na crise de 2022.
- **CHF vendido (−3,4 pp no histórico; +3,9 no OOS).** O franco é o caso clássico de moeda de juro baixo que se valoriza em crise:
  o spot custou −13 pp desde 2015.

### Testes de fragilidade (excesso bruto a.a. sobre o CDI)
| variante                                                             |   IS 2010-20 |   OOS 2021+ |   2021 |   2022 |   2023 |   2024 |   2025+ |
|:---------------------------------------------------------------------|-------------:|------------:|-------:|-------:|-------:|-------:|--------:|
| original                                                             |        -0.46 |       12.53 |  -0.86 |  11.07 |  10.69 |  17    |   20.15 |
| sem TRY                                                              |         0.73 |        9.72 |   4.66 |  15.59 |  10.43 |  -0.2  |   15.04 |
| sem EM de alta inflação/alto carry (TRY ZAR BRL COP HUF MXN INR IDR) |         3.18 |        4.9  |   4.14 |  14.96 |   4    |   0.95 |    2.75 |
| carry 50% (haircut)                                                  |        -3.15 |        2.71 |  -4.33 |   7.65 |   4.2  |   1.61 |    3.91 |
| carry 50% e sem TRY                                                  |        -1.59 |        6.03 |   2.49 |  12.4  |   5.75 |  -3.83 |   10.7  |
| carry 0% (só spot)                                                   |        -5.78 |       -6.25 |  -7.68 |   4.33 |  -1.9  | -11.77 |  -10.14 |
| só G10                                                               |        -0.65 |        4.35 |   7.67 |  -1.24 |   2.25 |   5.9  |    6.08 |
| G10 + LatAm                                                          |        -0.87 |       10.05 |   3.91 |  19.05 |  10.14 |   3.28 |   12.67 |
| sem JPY                                                              |        -2    |       10.1  |  -1.56 |   6.43 |   7.2  |  16.1  |   17.69 |
| sem JPY e sem TRY                                                    |        -1    |        7.98 |   5.27 |  11    |   7.52 |  -0.96 |   13.53 |
| só lado comprado                                                     |        -1.78 |        8.21 | -11.9  |  -1.49 |  13.49 |   3.28 |   28.01 |
| n=5                                                                  |        -2.89 |       13.47 |   2.6  |  15.55 |  12.08 |  13.91 |   19.4  |
| execução +1 dia                                                      |        -0.62 |       12.39 |  -1.1  |  10.32 |  10.08 |  17.22 |   20.55 |

Leitura:
- **Sem a TRY sobram +9,7 pp OOS.** A TRY é "só" ~2,8 pp a.a. do OOS, mas é TODO o ano de 2024 (+17 pp com TRY, −0,2 pp sem).
- **Sem os emergentes de alto carry/inflação sobram +4,9 pp,** quase tudo de 2022 (vendido em EUR/JPY/CHF/SEK contra o dólar no ciclo do Fed).
- **Com metade do carry sobram +2,7 pp; com carry zero, −6,3 pp.** O fundo depende de o carry medido pelo juro BIS ser o carry recebido de fato.
  Nas moedas NDF o código já aplica 70%. Na TRY de 2024–25 o juro implícito offshore ficou perto do juro oficial (40–50%), então o diferencial é crível.
  Em 2021–22, o juro oficial da TRY (8,5–14%) estava abaixo da inflação, e o carry implícito no forward era diferente. Na HUF de 2022, o BIS
  (13%) subestima a taxa efetiva (18%). **Antes de operar: refazer com o carry implícito dos forwards de 1 mês (Bloomberg/Refinitiv).**
- **Só G10: +4,4 pp OOS. G10+LatAm: +10 pp.** O ganho vem de LatAm (BRL, MXN, COP) mais o vendido em JPY/EUR.
- **IS de 2010–2020 ≈ 0 em todas as variantes.** O carry de moedas não dava dinheiro antes de 2021. O OOS é um regime de diferenciais
  grandes (ciclos de alta em emergentes antes do Fed, depois Fed alto contra BoJ/SNB a zero). Ou seja, o fundo foi escolhido com IR IS negativo
  (−0,007) e deu certo por causa do regime, não da seleção.

### Posição média por trimestre no OOS (% do PL)
|                     |   EURUSD |   JPY |   CHF |   SEK |   MXN |   ZAR |   TRY |   COP |   HUF |   THB |   BRL |
|:--------------------|---------:|------:|------:|------:|------:|------:|------:|------:|------:|------:|------:|
| 2021-03-31 |        0 |   -46 |   -46 |     0 |    27 |    24 |    20 |     0 |     0 |     0 |     0 |
| 2021-06-30 |        0 |   -44 |   -44 |     0 |    27 |    23 |    13 |     0 |     0 |     0 |     0 |
| 2021-09-30 |        0 |   -73 |   -73 |     0 |    48 |    29 |    41 |     0 |     0 |     0 |    10 |
| 2021-12-31 |      -49 |   -42 |   -38 |   -31 |    30 |     0 |    18 |     0 |     0 |     0 |    16 |
| 2022-03-31 |      -34 |   -38 |   -33 |   -21 |    24 |     0 |     3 |     0 |     0 |     0 |    15 |
| 2022-06-30 |      -31 |   -32 |   -40 |   -12 |    27 |     0 |    22 |     0 |     0 |     0 |    15 |
| 2022-09-30 |      -32 |   -27 |   -32 |     0 |     0 |     0 |    25 |     0 |    10 |   -13 |    16 |
| 2022-12-31 |       -1 |   -23 |   -27 |     0 |    13 |     0 |    28 |     0 |    13 |   -30 |    14 |
| 2023-03-31 |        0 |   -23 |   -35 |     0 |    37 |     0 |     0 |     0 |    22 |   -34 |    20 |
| 2023-06-30 |        0 |   -25 |   -30 |     0 |    22 |     0 |     0 |     0 |    17 |   -29 |    22 |
| 2023-09-30 |        0 |   -30 |   -40 |     0 |    40 |     0 |    15 |     0 |    26 |   -42 |     1 |
| 2023-12-31 |        0 |   -43 |   -49 |     0 |    27 |     0 |    39 |     0 |    25 |   -41 |     0 |
| 2024-03-31 |        0 |   -33 |   -45 |     0 |    33 |     0 |    64 |    15 |     9 |   -34 |     0 |
| 2024-06-30 |        0 |   -38 |   -42 |     0 |    33 |     0 |    60 |    20 |     0 |   -41 |     0 |
| 2024-09-30 |        0 |   -24 |   -33 |     0 |    13 |     0 |    37 |    19 |     0 |   -33 |     0 |
| 2024-12-31 |        0 |   -21 |   -31 |     0 |    18 |     0 |    45 |     0 |     0 |   -23 |    11 |
| 2025-03-31 |        0 |   -31 |   -47 |     0 |    25 |     0 |    66 |     0 |     0 |   -34 |    19 |
| 2025-06-30 |        0 |   -24 |   -26 |     0 |    17 |     0 |    34 |     0 |     0 |   -28 |    15 |
| 2025-09-30 |        0 |   -24 |   -28 |     0 |    19 |     0 |    58 |     8 |     0 |   -35 |    21 |
| 2025-12-31 |        0 |   -27 |   -35 |     0 |     0 |     0 |    75 |    22 |     0 |   -36 |    24 |
| 2026-03-31 |        0 |   -27 |   -32 |     0 |     0 |     0 |    75 |    13 |     0 |   -32 |    20 |
| 2026-06-30 |        0 |   -34 |   -35 |     0 |     0 |     0 |    75 |    18 |     0 |   -29 |    21 |
| 2026-09-30 |        0 |   -42 |   -36 |     0 |     0 |     0 |    75 |    19 |     0 |   -40 |    21 |
| 2026-12-31 |        0 |   -30 |   -36 |     0 |     0 |     0 |    75 |    16 |     0 |   -45 |    30 |

---

## 06 Eurobonds BR com hedge cambial e de Treasury (n=15, alav 1)

**Mecânica real.** O sinal de força é o percentil do **spread** do bond no mês: o livro compra os de MAIOR spread (top 10%) e vende quando o
percentil cai abaixo de 50%. É, por construção, um livro de high yield/stress.
Decomposição do retorno diário:
- **preço/spread** = variação de preço + D × variação do Treasury, ou seja, o movimento de preço que não é juro americano;
- **carrego** = cupom − custo dos hedges (DOL e Treasury) − CDI.

### Por emissor (desde 2021)
|           |   preço(spread) pp |   carrego pp |   total pp |   OOS 2024+ pp |   IS 2021-23 pp |
|:----------|-------------------:|-------------:|-----------:|---------------:|----------------:|
| Andrade   |               3.22 |         1.32 |       3.85 |           3.85 |            0    |
| Globo     |               1.56 |         0.08 |       1.48 |           0.57 |            0.91 |
| MC        |               0.66 |         0.97 |       1.42 |           2.34 |           -0.93 |
| Hidrovias |               1.12 |         0.1  |       1.15 |           1.2  |           -0.05 |
| Acu       |               0.87 |         0.36 |       1.13 |           0.33 |            0.8  |
| 3R        |               0.26 |         0.67 |       1.12 |           1.12 |            0    |
| BRF       |               0.3  |         0.62 |       1.07 |           0.78 |            0.3  |
| Minerva   |               0.23 |         0.54 |       0.93 |           0.7  |            0.23 |
| Simpar    |               0.11 |         0.31 |       0.78 |           0.34 |            0.44 |
| Movida    |              -0.11 |         0.32 |       0.66 |           0.16 |            0.5  |
| Braskem   |              -1.06 |         1.74 |       0.66 |           1.09 |           -0.43 |
| Natura    |               0.45 |        -0.01 |       0.4  |           0    |            0.4  |
| Aegea     |              -0.67 |         0.62 |      -0.11 |          -0.17 |            0.07 |
| Petrobras |              -0.64 |         0.3  |      -0.37 |           0    |           -0.37 |
| Raizen    |              -1.15 |         0.17 |      -0.7  |          -0.7  |            0    |

### Por ano
|   data |   preço/spread |   carrego |   custos/resíduo |   total |
|-------:|---------------:|----------:|-----------------:|--------:|
|   2019 |           0    |      0    |             0    |    0    |
|   2020 |           0    |      0    |             0    |    0    |
|   2021 |          -1.49 |      0.67 |            -0.18 |   -1    |
|   2022 |          -2.05 |      1.15 |            -0.22 |   -1.12 |
|   2023 |           4.17 |      2.61 |            -0.58 |    6.2  |
|   2024 |           3.77 |      2.48 |             0.02 |    6.27 |
|   2025 |           0.48 |      1.52 |            -0.37 |    1.63 |
|   2026 |          -0.73 |      0.97 |             1.29 |    1.53 |

### 10 melhores e 10 piores negócios
| emissor   |   cupom | venc       | entrada    | saida      |   dias |   px_entrada |   px_saida |   spread entrada % |   retorno % |   preço pp |   carrego pp |   contrib pp | motivo      |
|:----------|--------:|:-----------|:-----------|:-----------|-------:|-------------:|-----------:|-------------------:|------------:|-----------:|-------------:|-------------:|:------------|
| Andrade   |    9    | 2029-12-28 | 2024-03-05 | 2024-05-28 |     58 |        23.6  |      30.75 |              46.34 |       46.56 |       2.53 |         0.48 |         2.65 | sumiu       |
| MC        |    7.25 | 2031-06-30 | 2023-05-18 | 2026-10-07 |    852 |        78.84 |      98.28 |               8.56 |       36.27 |       1.75 |         0.57 |         2.15 | em carteira |
| BRF       |    5.75 | 2050-09-21 | 2023-07-05 | 2026-10-07 |    819 |        67.48 |      70.5  |               5.13 |       26.59 |       1.33 |         0.2  |         1.9  | em carteira |
| Simpar    |    5.2  | 2031-01-26 | 2023-05-18 | 2026-10-07 |    852 |        72.5  |      83.95 |               6.47 |       25.63 |       1.23 |         0.15 |         1.76 | em carteira |
| Globo     |    5.5  | 2032-01-14 | 2023-07-13 | 2025-10-03 |    560 |        78.5  |      96.99 |               5.36 |       16.83 |       1.3  |         0.02 |         1.42 | sinal < 50% |
| Movida    |    5.25 | 2031-02-08 | 2023-05-18 | 2026-10-07 |    852 |        75    |      83.38 |               5.89 |       18.44 |       0.8  |         0.13 |         1.41 | em carteira |
| Hidrovias |    4.95 | 2031-02-08 | 2023-05-18 | 2025-08-21 |    568 |        78.05 |      94    |               6.24 |       22.7  |       1.49 |        -0.06 |         1.41 | sumiu       |
| Acu       |    7.5  | 2035-07-13 | 2023-06-05 | 2024-09-02 |    313 |        86.12 |      99.4  |               5.71 |       18.32 |       1    |         0.2  |         1.16 | sumiu       |
| 3R        |    9.75 | 2031-02-05 | 2024-02-05 | 2026-10-07 |    672 |        99.9  |     104.65 |               5.67 |       14.84 |       0.25 |         0.62 |         1.12 | em carteira |
| Raizen    |    6.25 | 2032-07-08 | 2026-09-02 | 2026-10-07 |     24 |        56.38 |      64.25 |              13.88 |       15.73 |       0.65 |        -0.02 |         1.05 | em carteira |

| emissor   |   cupom | venc       | entrada    | saida      |   dias |   px_entrada |   px_saida |   spread entrada % |   retorno % |   preço pp |   carrego pp |   contrib pp | motivo      |
|:----------|--------:|:-----------|:-----------|:-----------|-------:|-------------:|-----------:|-------------------:|------------:|-----------:|-------------:|-------------:|:------------|
| Raizen    |    6.25 | 2032-07-08 | 2026-02-04 | 2026-04-23 |     52 |        78    |      52.58 |               5.75 |      -30.79 |      -2.12 |         0.1  |        -2.1  | sumiu       |
| BRF       |    5.75 | 2050-09-21 | 2021-09-03 | 2022-09-06 |    253 |       101.62 |      71.1  |               3.87 |      -17.16 |      -1.37 |         0.23 |        -1.12 | sumiu       |
| Simpar    |    5.2  | 2031-01-26 | 2021-02-03 | 2023-05-05 |    564 |       101.8  |      74.75 |               4.03 |      -13.71 |      -1.1  |         0.27 |        -0.98 | sumiu       |
| Braskem   |    7.45 | 2029-11-15 | 2024-09-04 | 2026-10-07 |    525 |        83.16 |      60    |               8.02 |      -15.04 |      -1.13 |         0.5  |        -0.93 | em carteira |
| Movida    |    5.25 | 2031-02-08 | 2021-02-03 | 2023-05-05 |    564 |        99.74 |      77.6  |               4.01 |      -12.61 |      -1.04 |         0.3  |        -0.75 | sumiu       |
| MC        |    7.25 | 2031-06-30 | 2021-08-04 | 2023-05-05 |    439 |       103.75 |      75.53 |               5.46 |      -10.59 |      -1.14 |         0.45 |        -0.73 | sumiu       |
| Andrade   |    9    | 2029-12-28 | 2025-12-11 | 2026-01-21 |     27 |        37.05 |      32.89 |              48.13 |       -9.09 |      -0.74 |         0.14 |        -0.57 | sumiu       |
| Raizen    |    6.25 | 2032-07-08 | 2026-06-25 | 2026-07-29 |     24 |        56.53 |      53.25 |              13.74 |       -4.21 |      -0.41 |         0.01 |        -0.44 | sumiu       |
| B2W       |    4.38 | 2030-12-20 | 2023-06-02 | 2023-07-28 |     39 |        17.3  |      16.24 |              35.18 |       -5.07 |      -0.57 |         0.24 |        -0.39 | sumiu       |
| Petrobras |    6.85 | 2115-06-05 | 2021-02-03 | 2023-05-05 |    564 |       118.65 |      88.15 |               3.99 |       -6.99 |      -0.74 |         0.38 |        -0.37 | sumiu       |

### O que aconteceu
- **A safra de mai–jul/2023 (entradas de 2023T2–T3: +12,2 pp dos +13,5 pp desde 2021).** No 1º semestre de 2023 o high yield brasileiro em
  dólar estava no fundo do poço: fraude da Americanas (jan/2023), recuperação judicial da Light (mai/2023), Selic a 13,75%, Treasury de 10 anos
  subindo. Em 18/05/2023 o livro comprou de uma vez:
  - MC Brazil Downstream (refinaria de Mataripe/Acelen) 7,25% 2031 a 78,8 → 98,3 (+2,15 pp);
  - Simpar 5,2% 2031 a 72,5 → 84 (+1,8);
  - Movida 5,25% 2031 a 75 → 83 (+1,4);
  - Hidrovias 4,95% 2031 a 78 → 94 (+1,4);
  - e, em junho–julho: BRF 5,75% 2050 a 67 → 70,5 (+1,9), Globo 5,5% 2032 a 78,5 → 97 (+1,4), Açu 7,5% 2035 a 86 → 99 (+1,2).

  O que levou esses preços para cima: início dos cortes da Selic (ago/2023), elevação do rating soberano (Fitch para BB em jul/2023, S&P em dez/2023)
  e o fechamento de spread do HY emergente em 2023–24. Os +6,2 pp de 2023 e os +6,3 pp de 2024 são essa safra.
- **Andrade Gutierrez 9% 2029 (+3,85 pp, 100% no OOS).** É um bond em reestruturação, negociado a 23–43, entrado e saído ~20 vezes porque os
  preços FINRA somem por dias (motivo de saída "sumiu"). O melhor negócio (23,6 → 30,75 em 58 dias, +2,65 pp) é com preço de negócio esparso.
  **Não é executável** nesse tamanho e frequência.
- **Piores:** Raízen 6,25% 2032 a 78 → 52,6 em 2026 (−2,1 pp; a crise de alavancagem da Raízen e os rebaixamentos), BRF 2050 e Simpar/Movida
  comprados a ~100 em 2021 que caíram a 71–77 em 2022 (alta de juros: são preços com o Treasury hedgeado, então foi abertura de spread), e
  Braskem 7,45% 2029 a 83 → 60 (ciclo ruim da petroquímica, saga da venda da Novonor).
- **Carrego x preço.** No total desde 2021: carrego +9,4 pp, preço/spread +4,1 pp. Mas nos 10 melhores negócios o preço domina (compra a 70–80,
  saída perto do par). O carrego é o "aluguel" de esperar a recuperação.
- **Concentração em nomes de stress.** Entradas abaixo de 80: 43 negócios, +14,9 pp; entradas acima de 90: −1,6 pp. Sem os nomes de stress e
  high yield, o livro teria +4,4 pp desde 2021 (contra +13,5).
- **Bugs/dados:** 53 de 64 negócios saem por "sumiu" (FINRA sem negócio por 3 dias). O livro vende ao último preço e recompra dias depois, o que
  é irreal para bonds ilíquidos. O número de nomes em carteira foi de 4,6 (2021) a 11,2 (2024), nunca os 15 nominais.

---

## 02 Financiador a termo (thr 0,5%, peso 10%)

**Mecânica real.** Compra à vista e vende a termo (60–400 dias) quando a taxa implícita, a mediana do dia por ação e faixa de prazo,
supera CDI+0,5%. Carrega até o vencimento; não há marcação a mercado (risco zero com garantia da B3).

### Por ano de entrada
|   ano |   negocios |   tickers |   taxa_media |   cdi_entrada |   edge_entrada |   edge_realizado |   prazo_du |   vol_termo_mediano_RS |   contrib_pp |
|------:|-----------:|----------:|-------------:|--------------:|---------------:|-----------------:|-----------:|-----------------------:|-------------:|
|  2014 |         35 |        22 |        13.5  |         10.5  |           3    |             2.69 |      58    |            2.34114e+06 |         2.21 |
|  2015 |         33 |        17 |        16.16 |         13.36 |           2.79 |             2.51 |      54.5  |            1.742e+06   |         1.74 |
|  2016 |         27 |        17 |        17.03 |         14.06 |           2.97 |             3.17 |      55    |            1.55171e+06 |         2.03 |
|  2017 |         31 |        18 |        12.24 |          9.81 |           2.44 |             3.24 |      54.5  |            2.00395e+06 |         2.26 |
|  2018 |         38 |        19 |         9.55 |          6.49 |           3.06 |             3.13 |      54.25 |            1.96019e+06 |         2.92 |
|  2019 |         41 |        25 |         8.89 |          5.89 |           3    |             3.25 |      54.5  |            2.28953e+06 |         2.82 |
|  2020 |         33 |        23 |         7.08 |          2.94 |           4.14 |             4.53 |      64    |            2.39468e+06 |         4.37 |
|  2021 |         32 |        23 |         9.64 |          4.43 |           5.21 |             3.93 |      64    |            1.76715e+06 |         2.92 |
|  2022 |         36 |        22 |        16.38 |         12.44 |           3.94 |             3.45 |      58    |            1.80711e+06 |         2.56 |
|  2023 |         33 |        23 |        16.08 |         13.2  |           2.88 |             3.15 |      54.5  |            1.14362e+06 |         2.36 |
|  2024 |         32 |        20 |        13.42 |         10.92 |           2.49 |             2.41 |      56.25 |            2.47213e+06 |         2.08 |
|  2025 |         28 |        17 |        17.22 |         14.03 |           3.19 |             2.69 |      64.5  |            1.0124e+06  |         1.86 |
|  2026 |         27 |        22 |        16.52 |         14.36 |           2.16 |             2.34 |      58    |            2.15394e+06 |         1.14 |

### Por ação (top 15 de 107)
|         |   total pp |   OOS pp |   IS pp |   % do total |
|:--------|-----------:|---------:|--------:|-------------:|
| PETR4T  |       3.4  |     1.42 |    1.98 |        10.89 |
| BBDC4T  |       1.53 |     0.69 |    0.84 |         4.9  |
| BBAS3T  |       2.17 |     0.65 |    1.52 |         6.95 |
| ITSA4T  |       0.97 |     0.56 |    0.41 |         3.09 |
| VALE3T  |       1.29 |     0.55 |    0.74 |         4.14 |
| COGN3T  |       0.78 |     0.54 |    0.24 |         2.51 |
| BRAV3T  |       0.49 |     0.49 |    0    |         1.56 |
| RRRP3T  |       0.42 |     0.42 |    0    |         1.33 |
| ITUB4T  |       0.97 |     0.39 |    0.58 |         3.11 |
| BPAC11T |       0.65 |     0.38 |    0.27 |         2.07 |
| IRBR3T  |       0.83 |     0.37 |    0.46 |         2.64 |
| JSLG3T  |       0.3  |     0.3  |    0    |         0.96 |
| PETZ3T  |       0.29 |     0.29 |    0    |         0.92 |
| B3SA3T  |       0.29 |     0.29 |    0    |         0.92 |
| MGLU3T  |       0.47 |     0.28 |    0.19 |         1.5  |

Não é concentrado: top 5 ações = 30% do ganho, top 10 = 43%, top 8 meses de entrada = 15%. PETR4, BBAS3, BBDC4 e VALE3 lideram.

### 10 melhores e 10 piores negócios
| ticker   | entrada    | venc       |    du |   taxa % |   cdi entrada % |   edge pp |   cdi médio realizado % |   edge realizado pp |   volume termo R$ |   n negócios |   contrib pp |
|:---------|:-----------|:-----------|------:|---------:|----------------:|----------:|------------------------:|--------------------:|------------------:|-------------:|-------------:|
| FESA4T   | 2020-01-29 | 2020-11-09 | 203.5 |     9.83 |            4.4  |      5.43 |                    2.77 |                7.06 |  878578           |            2 |         0.51 |
| BBAS3T   | 2018-08-07 | 2019-01-19 | 118.5 |    13.85 |            6.39 |      7.46 |                    6.4  |                7.46 |       2.52408e+06 |            2 |         0.3  |
| JSLG3T   | 2024-05-02 | 2024-10-29 | 128   |    17.26 |           10.65 |      6.61 |                   10.47 |                6.79 |       7.07231e+06 |            3 |         0.3  |
| IRBR3T   | 2020-06-12 | 2021-04-19 | 221   |     5.3  |            2.9  |      2.4  |                    2.03 |                3.26 |       3.00362e+06 |            2 |         0.27 |
| ITSA4T   | 2020-05-19 | 2021-05-16 | 259.5 |     4.84 |            2.9  |      1.94 |                    2.16 |                2.69 |       3.02832e+07 |            2 |         0.26 |
| PETR4T   | 2021-03-23 | 2021-09-04 | 118.5 |     9.6  |            2.65 |      6.95 |                    3.77 |                5.83 |       1.68046e+06 |            2 |         0.25 |
| VALE5T   | 2016-06-17 | 2016-11-14 | 106   |    20.85 |           14.13 |      6.72 |                   14.09 |                6.76 |  754548           |            3 |         0.24 |
| MRFG3T   | 2014-05-19 | 2015-05-22 | 263   |    14    |           10.8  |      3.2  |                   11.48 |                2.52 |       1.81002e+07 |            2 |         0.23 |
| BEEF3T   | 2020-01-24 | 2020-06-23 | 107   |     9.34 |            4.4  |      4.94 |                    3.57 |                5.77 |       1.05061e+06 |            2 |         0.22 |
| COGN3T   | 2020-05-05 | 2020-08-03 |  64   |    11.47 |            3.65 |      7.82 |                    2.52 |                8.95 |       2.39468e+06 |            3 |         0.21 |

| ticker   | entrada    | venc       |    du |   taxa % |   cdi entrada % |   edge pp |   cdi médio realizado % |   edge realizado pp |   volume termo R$ |   n negócios |   contrib pp |
|:---------|:-----------|:-----------|------:|---------:|----------------:|----------:|------------------------:|--------------------:|------------------:|-------------:|-------------:|
| VALE3T   | 2021-09-20 | 2022-03-21 | 130   |     6.66 |            5.15 |      1.51 |                    8.56 |               -1.9  |       4.68075e+06 |            3 |        -0.09 |
| BBDC4T   | 2024-11-01 | 2025-01-16 |  54   |    11.33 |           10.65 |      0.68 |                   11.6  |               -0.27 |       1.7306e+06  |            2 |        -0    |
| ITUB4T   | 2015-05-22 | 2015-08-05 |  53   |    13.65 |           13.13 |      0.52 |                   13.61 |                0.04 |       1.56255e+06 |            2 |         0    |
| COGN3T   | 2021-02-23 | 2022-02-20 | 259.5 |     5.53 |            1.9  |      3.63 |                    5.52 |                0.02 |  675937           |            2 |         0    |
| BBDC4T   | 2014-01-07 | 2014-03-10 |  44   |    10.39 |            9.77 |      0.62 |                   10.26 |                0.13 |       2.72349e+06 |            3 |         0    |
| LAVV3T   | 2026-10-07 | 2026-12-29 |  59   |    16.2  |           13.65 |      2.55 |                   13.65 |                2.55 |  888339           |            2 |         0    |
| ITSA4T   | 2015-07-22 | 2015-09-21 |  43   |    14.37 |           13.64 |      0.73 |                   14.07 |                0.29 |       5.89365e+06 |            3 |         0    |
| PETR4T   | 2015-01-16 | 2015-03-19 |  44   |    12.57 |           11.57 |      1    |                   12.18 |                0.39 |       2.32307e+06 |            3 |         0.01 |
| PETR4T   | 2015-07-22 | 2015-10-07 |  55   |    14.4  |           13.64 |      0.76 |                   14.08 |                0.32 |       3.27748e+06 |            4 |         0.01 |
| PETR4T   | 2014-11-28 | 2015-04-13 |  96   |    12.22 |           11.06 |      1.16 |                   12.02 |                0.2  |  718846           |            2 |         0.01 |

### O problema: ruído de horário selecionado (maldição do vencedor)
| teste                                             |   negócios |   edge médio travado pp |   excesso OOS pp a.a. |   excesso 2014-20 pp a.a. |
|:--------------------------------------------------|-----------:|------------------------:|----------------------:|--------------------------:|
| original (seleciona e trava no fechamento)        |        426 |                    3.19 |                  2.39 |                      2.56 |
| seleciona no fech., trava pelo VWAP à vista       |        426 |                    0.31 |                  0.56 |                      0.04 |
| seleciona no fech., trava pelo pior preço à vista |        426 |                   -4.79 |                 -3.72 |                     -3.71 |
| executa no dia seguinte (lag 1)                   |        243 |                    0.57 |                  0.16 |                      0.17 |
| thr 2% (só taxas muito altas)                     |        424 |                    4.2  |                  3.09 |                      3.07 |

- Considerando TODOS os candidatos (papel/faixa/dia com ≥2 negócios), o spread sobre o CDI tem mediana de +0,72 pp, p25 de −1,2 e p75 de +2,8.
  Uma dispersão de 4 pp para uma taxa de financiamento é ruído. Num termo de 60 dias, 1% de diferença entre o preço à vista no horário do
  negócio a termo e o fechamento vira ~4–6 pp a.a. de taxa.
- O filtro "> CDI+0,5%" escolhe justamente os dias em que o à vista fechou abaixo do preço do momento do termo. Travando pelo VWAP à vista
  (preço médio do dia, mais próximo do que se conseguiria de fato), o edge médio cai de 3,2 para 0,3 pp e o excesso OOS de +2,4 para +0,6 pp a.a.
  Executando no dia seguinte, sobra +0,2 pp. Pelo pior preço à vista do dia, −3,7 pp.
- **O que é real:** o termo é financiamento de alavancagem de pessoa física, e as corretoras cobram acima do CDI. A mediana de CDI+0,7 pp
  (CDI+1,2–2,1 pp em 2021–22 e 2025, quando o CDI subiu rápido e a taxa do termo, mais "pegajosa", não acompanhou na hora) é plausível.
- **Capacidade:** o volume a termo diário nos papéis/faixas que pagam > CDI+0,5% tem mediana de R$ 6,8 mi. Uma posição de 10% do PL que use
  até 20% do volume do dia limita o PL a ~R$ 3,6 mi (mediana; p75 R$ 8,5 mi).
- A taxa média travada no OOS (14,8% contra CDI de 11,5% na entrada) é ilusória pelo motivo acima.

---

## 15 Prêmio de volatilidade (50% put-write ^PUT + 50% SVXY com filtro VIX/VIX3M<1 e VVIX < p80)

### Por ano
|      |   svxy |   put |   total |   % dias SVXY ligado |
|-----:|-------:|------:|--------:|---------------------:|
| 2005 |    0   |   2.1 |     2.1 |                  0   |
| 2006 |    0   |   4.8 |     4.8 |                  0   |
| 2007 |   -1.4 |   2.5 |     1.1 |                 37.5 |
| 2008 |   -1.4 | -13.8 |   -15.2 |                 53.4 |
| 2009 |   -0.4 |  12.9 |    12.5 |                 78.2 |
| 2010 |   -0.5 |   4.6 |     4.1 |                 67.5 |
| 2011 |    5.1 |   3.7 |     8.8 |                 63.5 |
| 2012 |   19   |   4   |    23   |                 84   |
| 2013 |   23.8 |   5.9 |    29.7 |                 90.9 |
| 2014 |    6.7 |   3.3 |    10   |                 70.2 |
| 2015 |   12.2 |   3.6 |    15.8 |                 73   |
| 2016 |   40.7 |   3.8 |    44.5 |                 85.7 |
| 2017 |   39.1 |   4.7 |    43.8 |                 76.9 |
| 2018 |    0.3 |  -3.5 |    -3.2 |                 61   |
| 2019 |    9.5 |   5.5 |    15   |                 82.9 |
| 2020 |    2.9 |   3.7 |     6.6 |                 64   |
| 2021 |    7.1 |  10   |    17.1 |                 82.9 |
| 2022 |  -13.3 |  -4.4 |   -17.7 |                 82.9 |
| 2023 |   23.1 |   4.3 |    27.4 |                 80.8 |
| 2024 |   -6   |   5.8 |    -0.2 |                 69.8 |
| 2025 |   10.5 |   2.9 |    13.4 |                 79.6 |
| 2026 |    4.3 |   3.9 |     8.1 |                 80.2 |

### Episódios do SVXY (254 episódios, mediana de 3 dias ligado)
| ativo   | lado     | entrada    | saida      |   dias |   peso_medio |   retorno % |   contrib pp |   contrib OOS pp |
|:--------|:---------|:-----------|:-----------|-------:|-------------:|------------:|-------------:|-----------------:|
| svxy    | comprado | 2016-11-11 | 2017-02-09 |     61 |          0.5 |       66.59 |        26.29 |             0    |
| svxy    | comprado | 2011-11-29 | 2012-02-10 |     51 |          0.5 |       56.59 |        23.85 |             0    |
| svxy    | comprado | 2016-02-17 | 2016-06-14 |     83 |          0.5 |       46.98 |        22.35 |             0    |
| svxy    | comprado | 2014-04-16 | 2014-07-18 |     65 |          0.5 |       50.96 |        21.62 |             0    |
| svxy    | comprado | 2016-06-30 | 2016-09-12 |     51 |          0.5 |       48.16 |        21.07 |             0    |
| svxy    | comprado | 2012-07-27 | 2012-12-31 |    107 |          0.5 |       33.69 |        17.95 |             0    |
| svxy    | comprado | 2015-02-17 | 2015-06-30 |     94 |          0.5 |       36.92 |        17.89 |             0    |
| svxy    | comprado | 2013-06-28 | 2013-08-28 |     43 |          0.5 |       21.79 |        10.57 |             0    |
| svxy    | comprado | 2021-02-03 | 2021-05-13 |     70 |          0.5 |       20.94 |        10.5  |            10.5  |
| svxy    | comprado | 2025-06-23 | 2025-10-13 |     79 |          0.5 |       20.96 |         9.91 |             9.91 |

| ativo   | lado     | entrada    | saida      |   dias |   peso_medio |   retorno % |   contrib pp |   contrib OOS pp |
|:--------|:---------|:-----------|:-----------|-------:|-------------:|------------:|-------------:|-----------------:|
| svxy    | comprado | 2011-10-31 | 2011-11-01 |      2 |          0.5 |      -24.07 |       -12.86 |             0    |
| svxy    | comprado | 2012-03-26 | 2012-04-10 |     11 |          0.5 |      -18.72 |        -9.59 |             0    |
| svxy    | comprado | 2015-07-15 | 2015-08-21 |     28 |          0.5 |      -18.45 |        -8.77 |             0    |
| svxy    | comprado | 2016-01-07 | 2016-01-08 |      2 |          0.5 |      -15.87 |        -8.27 |             0    |
| svxy    | comprado | 2018-08-20 | 2018-10-11 |     38 |          0.5 |      -13    |        -6.66 |             0    |
| svxy    | comprado | 2024-11-08 | 2024-12-19 |     29 |          0.5 |      -12.56 |        -6.39 |            -6.39 |
| svxy    | comprado | 2025-04-03 | 2025-04-03 |      1 |          0.5 |      -12.48 |        -6.27 |            -6.27 |
| svxy    | comprado | 2022-02-10 | 2022-02-11 |      2 |          0.5 |      -11.14 |        -5.75 |            -5.75 |
| svxy    | comprado | 2020-05-27 | 2020-06-12 |     13 |          0.5 |      -12.31 |        -5.7  |             0    |
| svxy    | comprado | 2014-07-22 | 2014-07-31 |      8 |          0.5 |      -10.59 |        -5.39 |             0    |

### Estresses (pp do PL na janela; comparação com outros filtros)
| evento                           |   SVXY pp |   PUT pp |   total pp |   SVXY ret ativo % |   dias ligado | ligado no 1o dia   |   total só filtro VIX3M pp |   total sem filtro pp |
|:---------------------------------|----------:|---------:|-----------:|-------------------:|--------------:|:-------------------|---------------------------:|----------------------:|
| Volmageddon fev/2018             |      0    |    -1.24 |      -1.24 |             -90.53 |             0 | False              |                     -27.05 |                -65.35 |
| Q4 2018                          |    -15.43 |    -6.02 |     -21.45 |             -28.83 |            31 | True               |                     -25.42 |                -22.06 |
| Covid fev-mar/2020               |     -1.22 |   -10.06 |     -11.28 |             -53.82 |             2 | True               |                     -19.14 |                -45.07 |
| jan/2022 (início da alta do Fed) |    -14.4  |    -1.16 |     -15.56 |             -21.24 |            18 | True               |                     -17.31 |                -12.12 |
| jun/2022                         |     -1.65 |    -1.61 |      -3.26 |              -3.75 |            21 | True               |                      -3.26 |                 -3.26 |
| SVB mar/2023                     |     -3.57 |     0.04 |      -3.53 |              -8.91 |             9 | True               |                      -4.2  |                 -4.2  |
| carry trade do iene ago/2024     |     -3.58 |     0.79 |      -2.79 |             -16.55 |             6 | True               |                     -17.07 |                 -5.83 |
| tarifas abr/2025                 |     -9.7  |    -1.31 |     -11.01 |             -22.99 |             7 | True               |                     -11.01 |                -12.79 |

Dia a dia em abr/2025: o filtro religou no fechamento de 01/04 (VIX/VIX3M = 1,00). A compra executou no fechamento de 02/04, horas antes do
anúncio das tarifas do "Liberation Day", que saiu depois do fechamento. O sinal de desligar só executou em 03/04. Por isso o fundo levou
−12,5% × 0,5 = **−6,3 pp em 03/04**. É o custo do t+1 num livro de cauda.
|                     |   VIX/VIX3M | filtro ON   |   peso SVXY no dia |   SVXY ret % |   contrib SVXY pp |   PUT ret % |
|:--------------------|------------:|:------------|-------------------:|-------------:|------------------:|------------:|
| 2025-03-31 |        1.01 | False       |                0.5 |         0.03 |              0.01 |        0.39 |
| 2025-04-01 |        1    | True        |                0.5 |        -0.15 |             -0.1  |        0.19 |
| 2025-04-02 |        1    | False       |                0   |         1.62 |             -0.02 |        0.3  |
| 2025-04-03 |        1.1  | False       |                0.5 |       -12.48 |             -6.27 |       -3.2  |
| 2025-04-04 |        1.23 | False       |                0   |        -9.88 |             -0    |       -5.69 |
| 2025-04-07 |        1.27 | False       |                0   |        -0.26 |             -0    |       -0.23 |
| 2025-04-08 |        1.26 | False       |                0   |        -6.64 |             -0    |       -1.52 |
| 2025-04-09 |        1.12 | False       |                0   |        10.67 |              0    |        8.79 |
| 2025-04-10 |        1.14 | False       |                0   |        -9.57 |             -0    |       -3.04 |
| 2025-04-11 |        1.11 | False       |                0   |         1.3  |              0    |        1.72 |

Fev/2018: o VVIX já estava acima do p80 desde o fim de janeiro, e o SVXY estava desligado quando caiu −32% (05/02) e −83% (06/02).
Só com o filtro VIX3M, o fundo teria perdido −27 pp; sem filtro, −65 pp.
Hipótese: com o SVXY ligado (50%) em 05/08/2024 a perda seria de −10,7% do PL. Antes da troca do SVXY para −0,5x (27/02/2018),
05–06/02/2018 seria −16% e −41,5%.

### O ponto principal: é beta, não alfa
| variante | excesso OOS a.a. | vol | beta ao S&P | excesso explicado pelo beta |
|---|---|---|---|---|
| filtro VIX3M+VVIX (escolhido) | 7,41 | 16,4% | 0,76 | 7,55 |
| só VIX3M | 8,40 | 19,9% | 0,95 | 9,25 |
| sem filtro | 13,92 | 21,7% | 1,09 | 10,44 |
| só put-write 100% | 7,55 | 10,5% | 0,56 | 5,63 |

No OOS de 2021–26 o S&P subiu forte. O livro escolhido rende o mesmo que 0,76 × S&P com hedge cambial, com caudas piores.
De 2022 a 2024: 2022 −17,7 pp (jan–mar/2022: −15,6 pp, SVXY ligado em 18 dias), 2023 +27,4 pp (VIX de 12–15 o ano todo), 2024 −0,2 pp.
**Só 2023 é 57% de todo o OOS.**

---

## 12 Commodities (momento relativo de 12 meses, top/bottom 30%, vol-alvo 8%)

### Por ETF
|      |   total pp |   OOS pp |   IS pp |   % dias comprado OOS |   % dias vendido OOS |
|:-----|-----------:|---------:|--------:|----------------------:|---------------------:|
| GLD  |      33.42 |     7.76 |   25.66 |                 51.72 |                20.39 |
| SLV  |      18.91 |     7.2  |   11.71 |                 60.26 |                24.04 |
| URA  |       7.83 |     5.91 |    1.93 |                 64.53 |                15.77 |
| CORN |      -3.37 |     3.67 |   -7.04 |                 31.89 |                44.63 |
| DBA  |      -0.37 |     3.64 |   -4.01 |                 32.64 |                14.74 |
| PALL |       7.53 |     2.53 |    5    |                 13.02 |                56.68 |
| PPLT |     -11.11 |     0.84 |  -11.95 |                 28.31 |                23    |
| USO  |       1.38 |     0.66 |    0.72 |                 53.86 |                15.84 |
| CPER |       0.65 |     0.33 |    0.32 |                 31.34 |                15.91 |
| BNO  |       2.39 |    -0.07 |    2.45 |                 54.96 |                13.77 |
| SOYB |      -1.23 |    -1.9  |    0.68 |                 23.9  |                18.94 |
| DBB  |       5.53 |    -2.01 |    7.54 |                 17.7  |                 8.33 |
| WEAT |      -6.91 |    -2.4  |   -4.5  |                 11.64 |                59.57 |
| UNG  |      11.77 |    -4    |   15.77 |                 24.24 |                68.39 |

### Melhores e piores negócios no OOS
| ativo   | lado     | entrada    | saida      |   dias |   peso_medio |   retorno % |   contrib pp |   contrib OOS pp |
|:--------|:---------|:-----------|:-----------|-------:|-------------:|------------:|-------------:|-----------------:|
| GLD     | comprado | 2024-07-16 | 2026-03-23 |    423 |         0.11 |       68.37 |         7.53 |             7.53 |
| CORN    | vendido  | 2023-08-29 | 2024-08-26 |    250 |         0.14 |       35.96 |         4.48 |             4.48 |
| SLV     | comprado | 2025-08-05 | 2026-10-12 |    299 |         0.04 |      114.16 |         4.41 |             4.41 |
| PPLT    | comprado | 2025-05-28 | 2026-06-22 |    268 |         0.04 |       47.2  |         3.5  |             3.5  |
| BNO     | comprado | 2021-03-16 | 2023-03-06 |    497 |         0.06 |       60.56 |         3.37 |             3.37 |
| DBA     | comprado | 2023-10-31 | 2024-05-20 |    139 |         0.2  |       10.14 |         3.23 |             3.23 |
| URA     | comprado | 2020-12-08 | 2022-02-14 |    299 |         0.05 |       62.15 |         3.23 |             2.64 |
| GLD     | comprado | 2023-10-10 | 2024-03-18 |    110 |         0.18 |       13.13 |         2.53 |             2.53 |
| UNG     | comprado | 2021-12-28 | 2022-10-03 |    193 |         0.03 |       70.52 |         2.29 |             2.29 |
| USO     | comprado | 2021-06-15 | 2023-02-06 |    415 |         0.06 |       32.28 |         1.97 |             1.97 |

| ativo   | lado     | entrada    | saida      |   dias |   peso_medio |   retorno % |   contrib pp |   contrib OOS pp |
|:--------|:---------|:-----------|:-----------|-------:|-------------:|------------:|-------------:|-----------------:|
| UNG     | vendido  | 2019-10-01 | 2021-06-28 |    439 |         0.05 |        3.26 |        -0.52 |            -2.92 |
| BNO     | vendido  | 2020-03-10 | 2021-03-08 |    251 |         0.05 |      -50.83 |        -2.53 |            -2.26 |
| USO     | vendido  | 2020-03-03 | 2021-04-26 |    290 |         0.05 |      -29.2  |        -0.99 |            -2.08 |
| GLD     | comprado | 2023-07-25 | 2023-10-02 |     49 |         0.24 |       -7.44 |        -2.04 |            -2.04 |
| WEAT    | comprado | 2022-03-08 | 2022-08-08 |    106 |         0.04 |      -33.08 |        -1.88 |            -1.88 |
| DBB     | comprado | 2025-04-01 | 2025-04-07 |      5 |         0.2  |       -8.21 |        -1.7  |            -1.7  |
| CPER    | comprado | 2025-07-22 | 2025-08-04 |     10 |         0.07 |      -20.8  |        -1.53 |            -1.53 |
| GLD     | vendido  | 2021-03-09 | 2022-04-25 |    286 |         0.17 |      -12.75 |        -1.42 |            -1.42 |
| SOYB    | comprado | 2022-10-04 | 2023-05-15 |    154 |         0.14 |       -4.52 |        -1.35 |            -1.35 |
| DBB     | comprado | 2024-05-21 | 2024-06-17 |     19 |         0.14 |       -8.5  |        -1.25 |            -1.25 |

- **Ganhos:**
  - ouro comprado de 07/2024 a 03/2026 (+68%; compras de bancos centrais depois do congelamento das reservas russas, cortes do Fed, geopolítica);
  - prata 08/2025 → 10/2026 (+114%) e platina 05/2025 → 06/2026 (+47%): o "rali dos metais preciosos" de 2025;
  - milho vendido 08/2023 → 08/2024 (safra recorde nos EUA, −36%);
  - Brent comprado 03/2021 → 03/2023 (reabertura e guerra);
  - urânio 2020–22 (Sprott Physical Uranium Trust comprando urânio físico).
- **Perdas:**
  - petróleo e gás vendidos em 2020–21 (recuperação pós-Covid, −51% no BNO);
  - trigo comprado em mar/2022, no pico da invasão da Ucrânia (−33%);
  - cobre e metais básicos comprados em picos curtos de 2024–25 (DBB −8% em 5 dias no choque tarifário de abr/2025).
- Por ano no OOS: 2021 −3,2, 2022 +6,8, 2023 −6,9, 2024 +9,8, **2025 +18,1**, 2026 −2,6. Sem 2025, o fundo empata com o CDI.
  O IS de 2012–2019 é negativo em 5 de 8 anos.

---

## 20 Multiestratégia
|                                                      |   peso médio OOS % |   alavanc. média OOS |   contrib IS 2015-22 pp |   contrib OOS 2023+ pp |   % do OOS |
|:-----------------------------------------------------|-------------------:|---------------------:|------------------------:|-----------------------:|-----------:|
| 02 Financiador a termo                               |              32.15 |                 3.75 |                   25.79 |                   9.4  |      72.55 |
| 01 Caixa sintético (box de 4 pontas)                 |              32.15 |                 3.75 |                    1.67 |                   2.57 |      19.84 |
| 03 Conversão BOVA11 (box de 3 pontas)                |              32.15 |                 3.75 |                    0.4  |                   0.83 |       6.41 |
| 15 Prêmio de volatilidade                            |               0.11 |                 3.75 |                    0.48 |                   0.2  |       1.54 |
| 12 Commodities sistemático                           |               0.29 |                 3.75 |                    0.08 |                   0.2  |       1.54 |
| 06 Crédito offshore com hedge (cupom cambial)        |               0.32 |                 3.75 |                   -0.03 |                   0.19 |       1.44 |
| 09 Crédito com hedge de ações (estrutura de capital) |               0.6  |                 3.75 |                    0.28 |                   0.16 |       1.26 |
| 08 Crédito privado ML                                |               0.6  |                 3.75 |                    0.28 |                   0.16 |       1.26 |
| 10 Crédito EUA com hedge de juros                    |               0.51 |                 3.75 |                   -0.07 |                   0.11 |       0.83 |
| 05 Long-short ON x PN                                |               0.17 |                 3.75 |                    0.22 |                   0.01 |       0.08 |
| 14 Paridade de risco global                          |               0.25 |                 3.75 |                    0.3  |                  -0.04 |      -0.34 |
| 13 Tendência multiativos (CTA)                       |               0.25 |                 3.75 |                    0.38 |                  -0.15 |      -1.18 |
| 19 Macro com dados alternativos                      |               0.16 |                 3.75 |                    0.38 |                  -0.16 |      -1.21 |
| 16 Ações Brasil neutro (ML)                          |               0.27 |                 3.75 |                    0.05 |                  -0.52 |      -4.01 |

O "multi" é, na prática, **1,2x um livro de termo + 1,2x box + 1,2x conversão**. O vol-alvo de 6% sobre livros com vol de 0,2–0,3% bate
no teto de 3x × 1,25. Como o termo é artefato, o multi também é. O carry (o melhor fundo) não entrou porque o IR IS era −0,007.
O vol e o commodities entraram com 0,1–0,3% de peso por causa do inverso da vol.

---

## Variantes melhoradas (`ideias_atribuicao.py`)

| fundo | parâmetros (IS) | OOS a.a. vs CDI | IR OOS | P(bater) | PBO | custo x2 | +1 dia | leitura |
|---|---|---|---|---|---|---|---|---|
| A1 Carry G10+LatAm, teto 25% do PL DEPOIS do vol-alvo, stop de 2σ em 10 dias | todas sem TRY, stop | 18,0% vs 11,4% | 0,96 | 99% | 71% | +6,4 | +6,6 | Todas as 4 variantes dão +6 a +8 pp OOS, com vol de 6–7% e pior queda de −6,3%. O stop custa ~1,5–2 pp e não melhora a queda; o IS 2010–20 continua ~0. Ganhos OOS: JPY vendido +11,7, COP +7,6, MXN +6,6, BRL +4,6, EUR +4,1; perdas: CLP −2,6, ZAR −1,0. |
| A2 Eurobonds BR em stress (top 30% de spread, preço entre lo e 85, sai em 97) | lo=40, sem stop | 16,7% vs 13,1% | 0,36 | 81% | 17% | +3,3 | +3,6 | É a mesma safra de mai/2023 (BRF 2050 +4,1, Simpar +2,6, MC +2,6, Movida +2,2, Açu/Petrobras/Hidrovias +2 cada). Raízen comprada a 80 em out/2025 −2,9 e Braskem −1,4. Com stop de −20%, piora. |
| A3 Put-write com hedge de beta | hedge 0, SVXY 25% | 19,8% vs 11,4% | 0,64 | 94% | 5% | +7,9 | +9,6 | O IS escolheu SEM hedge. **Com o beta hedgeado, OOS +0,7 pp (hedge 1, sem SVXY)** e IS −1,6 pp: confirma que não há prêmio de vol além do beta no put-write. |
| A4 Termo conservador (trava a menor taxa entre fechamento e VWAP) | thr 0,5%, peso 10% | 13,1% vs 11,4% | 29 | 100% | 15% | +0,7 | **−0,7** | Ainda falha o teste de +1 dia: a taxa do próprio termo (último negócio) também é ruidosa. Não confiar sem dados intradiários sincronizados. |

## O que é replicável e o que foi sorte de período

**Replicável:**
1. **Carry de moedas de G10+LatAm** (vendido em JPY/CHF/EUR, comprado em MXN/BRL/COP/CLP quando o diferencial é grande). É um prêmio de risco
   conhecido, que funciona quando os diferenciais são grandes e a vol é baixa. Excesso esperado de 3–6 pp, não os 12 pp do backtest.
2. **High yield brasileiro em dólar comprado em stress, com hedge de câmbio e Treasury.** É a tese de mesa "o mercado precifica default de
   empresas que não vão quebrar". Funcionou em 2023. A execução precisa de cotação real (dealers) e de capacidade de carregar 1–3 anos.
3. **Put-write como substituto de ações** (beta de ~0,5 com vol menor): é beta mais barato, não alfa.

**Sorte de período ou artefato:**
- a lira turca (1 moeda, 55–75% do PL, regime ortodoxo pós-2023);
- 2023 calmo no vol (57% do OOS);
- 2025 de metais preciosos nas commodities;
- o termo inteiro (ruído de horário) e, portanto, o multi;
- Andrade Gutierrez com preços FINRA esparsos.

## Propostas concretas de fundos (próxima rodada)

1. **Carry G10+LatAm com carry de forward e teto real.**
   - Diferencial medido pelos forwards de 1 mês, não pelo BIS. Teto de 20% do PL por moeda DEPOIS do vol-alvo; TRY no máximo em 10%, como satélite.
   - Hedge de cauda: comprar puts de 1 mês 5% fora do dinheiro em AUDJPY ou MXNJPY com 10–15% do carry esperado. É o hedge clássico do
     carry, que teria pago no desmonte do iene em ago/2024 e em abr/2025.
   - O stop simples de 2σ não ajudou (A1).
2. **"Safra de stress" em eurobonds BR (evento).** Gatilho: o spread mediano do HY BR em dólar abre mais de 150 bps em 3 meses, ou ocorre um
   evento de crédito sistêmico (Americanas-2023, Covid-2020). Então comprar 8–12 nomes NÃO em default (preço entre 60 e 85; rating e alavancagem
   abaixo de um limite) com hedge de DOL e Treasury, e carregar até 95–97 ou 24 meses.
   Teste honesto exige preços de dealer (TRACE só com lotes ≥ US$1 mi) e começar em 2015 (Petrobras/Odebrecht, 2015–16).
3. **Put-write + collar de VIX em vez de SVXY.** Se a ideia é vender vol, que seja delta-hedgeada (straddle de SPX 1 mês com hedge diário) para
   medir o prêmio puro. O backtest atual não separa prêmio de vol de beta. Sem dados de opções de SPX, o put-write hedgeado (A3) indica prêmio ~0.
4. **Termo/box somente com dados sincronizados.** Antes de qualquer capital, gravar por 3 meses o book de termo e à vista ao mesmo tempo
   (corretora/API). Se o edge real for CDI+0,5–1 pp, serve como gestão do caixa do fundo (R$ 2–5 mi), não como estratégia.
5. **Commodities:** manter só como diversificador de tendência de baixo peso (5–10% do risco). Não há tese de mesa além de "metais preciosos
   em bull market". Uma tese melhor a investigar: estrutura a termo (backwardation/contango) em vez de momento de 12 meses.
