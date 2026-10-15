# Frente GLOBAL — eventos, fluxo e mercados de fronteira (rodada 2, out/2026)

Código: `quant/fundos/ideias_global.py` (`python ideias_global.py dados ...` baixa; `python ideias_global.py` roda e salva
`resultado/ideias_global.pkl`). Corte OOS = 2021-01-01 em todos. Benchmark CDI (long-short/hedgeado) exceto G6 (ACWI c/ hedge).
Tudo em USD sobre o T-bill, convertido para R$ com hedge (`brl`). Decisão no fechamento da data em que a informação
fica pública (data de ARQUIVAMENTO na SEC), execução no fechamento seguinte.

## Resumo

| Fundo | Escolhido no IS | IR IS | OOS a.a. | Bench OOS | IR OOS | P(bater) | PBO | custo x2 (pp) | +1 dia (pp) |
|---|---|---|---|---|---|---|---|---|---|
| G1 Merger arb (ETF) com hedge de beta | `{'veiculo': 'MNA', 'hedge': 0}` | 0,5 | 9,7% | 11,4% (CDI) | -0,3 | 15% | 19% | -1,7 | -1,7 |
| G2 Insiders em grupo (Form 4) x IWM | `{'min_ins': 3, 'dias': 126, 'chefe': 1}` | 0,8 | 7,7% | 11,4% (CDI) | -0,3 | 18% | 15% | -6,6 | -4,0 |
| G3 Spin-offs após a venda forçada | `{'espera': 40, 'dias': 126}` | 0,9 | 20,7% | 11,4% (CDI) | 1,4 | 100% | 34% | 9,0 | 9,1 |
| G4 Calendário de fluxo EUA | `{'comp': 'rebal', 'alvo': 0.05}` | 0,6 | 12,1% | 11,4% (CDI) | 0,3 | 78% | 40% | 0,3 | -0,9 |
| G5 Fronteira: momentum com filtro de câmbio | `{'n': 3, 'filtro_fx': 1, 'hedge': 'EEM'}` | -0,5 | 11,7% | 11,4% (CDI) | 0,1 | 49% | 74% | -2,2 | 0,2 |
| G6 Fronteira: compra depois da crise | `{'queda': 0.4, 'meses': 6}` | 0,8 | 19,1% | 21,1% (ACWI (R$ c/ hedge)) | -0,3 | 26% | 3% | -2,2 | -2,0 |
| G7 Argentina: CCL implícito por ação | `{'sinal': 'dispersao', 'janela': 60, 'freq': 'W'}` | 0,1 | 12,8% | 11,4% (CDI) | 0,2 | 59% | 25% | -7,2 | 0,1 |
| G8 ADR x local por fuso (Ásia/Europa) | `{'regiao': 'india+coreia', 'thr': 0.02}` | -0,2 | 10,8% | 11,4% (CDI) | -0,2 | 32% | 3% | -6,9 | -2,2 |

Veredito curto:
- **Funciona e sobrevive ao OOS: spin-offs (G3).** +9 pp/ano sobre o CDI OOS, vol 5,7%, robusto a custo x2 e a +1 dia.
  Mas é cauda direita: sem os 5 melhores negócios OOS (SNDK, RHLD, GRAL, TRAX, Q) o excesso cai para ~3,4 pp/ano (Sharpe 0,7).
- **Pequeno mas consistente: calendário de fluxo (G4)**, sobretudo o rebalanceamento de fim de mês ações x títulos. ~+1 pp/ano, vol 2%.
  Serve como livro de baixa vol num multiestratégia, não como fundo.
- **Morreu no OOS: insiders em grupo (G2), merger arb via ETF (G1), lead-lag ADR x local (G8).**
- **Ruído caro: Argentina CCL (G7), fronteira momentum (G5), fronteira pós-crise (G6).** G6 tinha IS lindo graças a 2009/2016/2020
  e a um viés de sobrevivência grave (ver abaixo).

## Dados novos (dados/)

| arquivo | conteúdo |
|---|---|
| `sec_indice.parquet` | EDGAR full-index (form.gz) 2006Q1–2026Q4, só formas de evento: SC TO-T(/A), SC TO-C, SC 14D9(-C), DEFM14A, PREM14A, S-4, 10-12B(/A), SC 13E3, 25-NSE, 15-12B/G, 15-15D (≈150 mil linhas) |
| `sec_insider_compras.parquet` | Insider Transactions Data Sets 2006q1–2026q3: só transações não-derivativas código **P** (compra em mercado), com emissor, ticker informado, data de arquivamento, cargo (867 mil linhas) |
| `sec_emissores.parquet` | mapa CIK → ticker informado nos Forms 3/4/5 por trimestre (inclui empresas já deslistadas) |
| `sec_insider_clusters_*.parquet` | eventos de cluster já calculados (cache) |
| `sec_ofertas_preco.parquet` | preço da oferta lido do texto do SC TO-T (regex "$xx per share") para os alvos com preço no Yahoo |
| `y_fronteira.parquet` | ETFs de fronteira/EM pequenos + moedas + MNA/MRGR + ADRs argentinos e ações .BA |
| `y_pares.parquet` | Open/Close de 40 pares ADR x ação local (TW, HK, IN, JP, KR, Europa) + moedas |
| `y_insiders/y_spinoffs/y_alvos.parquet` | preços Yahoo dos tickers dos eventos (com lista de tentados para nunca re-baixar) |

User-Agent da SEC: "pesquisa-quant contato@example.com", ≤ 8 req/s.

### O viés que domina esta frente: o Yahoo apaga quem foi comprado ou quebrou

Cobertura de preços (fração dos eventos com algum preço no Yahoo):

| ano do evento | insiders (cluster 3) | spin-offs | alvos de oferta (SC 14D9) |
|---|---|---|---|
| 2006 | 30% | 53% | 27% |
| 2007 | 34% | 28% | 33% |
| 2008 | 37% | 35% | 29% |
| 2009 | 45% | 36% | 21% |
| 2010 | 43% | 53% | 26% |
| 2011 | 44% | 42% | 25% |
| 2012 | 45% | 39% | 24% |
| 2013 | 42% | 52% | 21% |
| 2014 | 42% | 39% | 19% |
| 2015 | 46% | 46% | 16% |
| 2016 | 48% | 73% | 14% |
| 2017 | 50% | 25% | 16% |
| 2018 | 53% | 60% | 18% |
| 2019 | 58% | 79% | 30% |
| 2020 | 64% | 73% | 17% |
| 2021 | 66% | 74% | 34% |
| 2022 | 76% | 89% | 17% |
| 2023 | 81% | 79% | 23% |
| 2024 | 90% | 86% | 22% |
| 2025 | 94% | 100% | 7% |
| 2026 | 99% | 100% | 46% |

- **Merger arb por evento é intestável com Yahoo.** Dos 1.034 alvos de tender offer com ticker conhecido (2006–2026), só 240 tickers
  têm algum preço e só **100 eventos** têm preço na data do SC 14D9 — e **100% deles ainda negociam hoje**, ou seja, são justamente
  as ofertas que fracassaram, foram parciais, mini-tenders, ofertas do próprio emissor, ou tickers reaproveitados. É uma amostra
  anti-sobrevivência perfeita: a mediana do "negócio" é +1%, com perdas como TTWO 2008 (oferta hostil da EA a US$ 26 retirada:
  comprei a 25,61, um ano depois 8,25 = −68%), SSYS 2023 (oferta da Nano Dimension a US$ 18, comprei a 14,55, saí a 9,02 = −38%)
  e SWX 2021 (Icahn a US$ 75, comprei a 59,58, saí a 55,72 = −6%). Não serve para medir spread capturado. Taxa de conclusão
  pelo EDGAR (alvo arquiva 25-NSE/15-12 em até 1 ano após o SC 14D9): ~71% — piso, porque nem todo alvo deslistado arquiva 25-NSE
  sob o próprio CIK; a literatura dá ~90% para ofertas amigáveis em dinheiro.
- **Mitigação adotada:** o fundo de merger arb (G1) usa o ETF MNA/MRGR, que é a carteira real de arbitragem. A tabela de eventos fica
  em `res[0]["eventos_alvos"]` só como prova do viés.
- **Insiders:** a cobertura sobe de ~35% (2006–08) para ~95% (2025). No IS faltam justamente as small caps que quebraram ou foram
  compradas → o IS é otimista (quebras somem) e o OOS é bem menos viesado. Isso, sozinho, explica parte do "funcionava e parou".
- **Spin-offs:** 74–100% de cobertura no OOS; o que falta são separadas compradas depois (viés para baixo) e quebradas (para cima).
- **ETFs de fronteira mortos:** PAK, FM, FRN, GXG/ICOL (Colômbia), EGPT, NGE (Nigéria), RSX/ERUS (Rússia, congelados em 2022) não
  existem mais no Yahoo. São exatamente os países das maiores crises → G5/G6 só veem os sobreviventes. Na prática a regra de G6
  ("compra depois de −40%") teria comprado Nigéria/Egito/Paquistão em quedas que continuaram; o resultado de G6 é teto, não estimativa.

---

## G1 — Merger arbitrage (ETF MNA/MRGR, hedge de beta)

**Tese de mesa:** arbitragem de fusões é vender seguro contra quebra do negócio; o prêmio paga ~CDI+3–5% historicamente, com cauda
esquerda em crises. Comprar o alvo após o anúncio, hedge com o comprador nas ofertas em ações.

**Implementação:** como não há preço dos alvos concluídos (ver viés), compramos o prêmio via ETF: 100% MNA (IQ Merger Arbitrage,
2009+) e/ou MRGR (ProShares, 2012+), vendendo SPY no beta móvel de 126 dias. Rebalanceio mensal, custo 3 bps, aluguel 0,3%.

**Resultado:** escolhido `{'veiculo': 'MNA', 'hedge': 0}`; IR IS 0,5; OOS 9,7% a.a. vs 11,4% do benchmark (IR -0,3, vol 4,9%, pior queda -3,9%), P(bater) 15%, PBO 19%. MNA tem beta de só ~0,12 contra o SPY e rendeu T-bill + 2 pp/ano até 2020; de 2021 em diante
rendeu **abaixo do T-bill** (−1,4 pp/ano). Hipótese (não testada aqui): o spread bruto subiu com o juro de 5%, mas os negócios
barrados por antitruste (FTC/DOJ 2021–24) e a taxa do ETF (~0,75% a.a.) comeram o prêmio. Hedge de beta não ajuda (beta baixo; só adiciona custo).

**Excesso sobre o CDI por ano (pp):** 2013: +6.8, 2014: +5.5, 2015: +1.4, 2016: +4.7, 2017: +5.3, 2018: +0.0, 2019: +2.6, 2020: +2.3, 2021: -3.6, 2022: -4.1, 2023: -5.5, 2024: -0.3, 2025: +4.7, 2026: -0.5

**O que deu errado:** não há o que otimizar — o ETF é um índice passivo de alvos anunciados, sem seleção de negócio nem
dimensionamento por probabilidade de quebra, que é onde está o alfa de um arbitrador de verdade.

**Próximo passo:** montar a base de negócios a partir do texto dos 8-K/SC TO-T/DEFM14A (preço da oferta, tipo, prazo), e conseguir
preços de deslistadas (CRSP/Norgate/Sharadar são pagos; Stooq também apaga). Sem isso, merger arb fica só como alocação no ETF.

---

## G2 — Insiders em grupo (Form 4, código P) x IWM

**Tese de mesa:** quando 3+ diretores/executivos compram com dinheiro do bolso em 30 dias, a informação é melhor que a do mercado,
principalmente em small/mid caps pouco cobertas.

**Implementação:** Form 4 (e 4/A), transação não-derivativa código P, aquisição (A), ≥ US$ 10 mil e preço ≥ US$ 2, arquivada até
60 dias após o negócio; só Officer/Director (sem 10% owners/fundos); exclui fundos fechados/SPACs/BDCs pelo nome. Evento = dia de
**arquivamento** que completa `min_ins` insiders distintos em 30 dias corridos (no máx. 1 evento por emissor a cada 6 meses).
Variante `chefe`: exige CEO/CFO/presidente e soma ≥ US$ 250 mil. Checagem de ticker: preço do Yahoo na data tem de estar entre
1/3 e 3x o preço do Form 4 (descarta ticker reaproveitado). Compra no fechamento seguinte, 5% por nome, segura 63/126 pregões,
vende IWM na mesma soma, custo 40 bps por perna.

**Resultado:** escolhido `{'min_ins': 3, 'dias': 126, 'chefe': 1}`; IR IS 0,8; OOS 7,7% a.a. vs 11,4% do benchmark (IR -0,3, vol 9,7%, pior queda -10,9%), P(bater) 18%, PBO 15%. Retorno médio por negócio contra o IWM: IS +7,3% (mediana +0,7%), OOS −0,3% (mediana −2,7%).
Nenhuma das 8 variantes bate o CDI no OOS.

**Excesso sobre o CDI por ano (pp):** 2008: +44.0, 2009: +31.1, 2010: +22.9, 2011: +10.2, 2012: +2.7, 2013: +5.2, 2014: +0.9, 2015: -2.6, 2016: +10.6, 2017: -1.7, 2018: +10.5, 2019: -5.7, 2020: +9.3, 2021: -5.7, 2022: -3.9, 2023: +16.6, 2024: -5.0, 2025: -10.8, 2026: -10.2

O IS inteiro é 2008–2010 (+44, +31, +23 pp): insiders compraram no fundo da crise e o rebote de small caps fez o resto — e é
justamente o período com pior cobertura (as que quebraram não estão na amostra). Depois de 2011 o efeito é ruído, e de 2024 em diante
é negativo (−5, −11, −10 pp): o sinal é público, gratuito, raspado por todo mundo (openinsider, bots) e o preço já anda no dia do Form 4.

**10 melhores negócios (contribuição ao fundo, % do PL):**

| ativo | lado | entrada | saida | dias | retorno % | contrib % | hedge % | ret - hedge % |
|---|---|---|---|---|---|---|---|---|
| EXEL | compra | 2010-08-26 | 2011-02-25 | 126 | 266.84 | 6.98 | 37.66 | 229.18 |
| TNDM | compra | 2018-02-14 | 2018-08-15 | 126 | 1209.48 | 5.97 | 9.54 | 1199.94 |
| JAZZ | compra | 2010-09-13 | 2011-03-14 | 126 | 192.0 | 5.42 | 22.97 | 169.03 |
| PROV | compra | 2009-12-14 | 2010-06-16 | 126 | 111.66 | 4.43 | 9.82 | 101.84 |
| CLW | compra | 2009-03-09 | 2009-09-04 | 126 | 619.17 | 4.04 | 66.88 | 552.29 |
| CRMD | compra | 2020-08-21 | 2021-02-23 | 126 | 226.21 | 3.27 | 44.37 | 181.84 |
| BKD | compra | 2009-03-11 | 2009-09-09 | 126 | 383.09 | 3.22 | 60.9 | 322.19 |
| WAL | compra | 2009-11-17 | 2010-05-20 | 126 | 74.23 | 3.13 | 7.02 | 67.22 |
| FLUX | compra | 2020-08-19 | 2021-02-19 | 126 | 208.15 | 3.08 | 44.93 | 163.22 |
| AGO | compra | 2009-03-06 | 2009-09-03 | 126 | 385.98 | 3.07 | 60.78 | 325.2 |

**10 piores:**

| ativo | lado | entrada | saida | dias | retorno % | contrib % | hedge % | ret - hedge % |
|---|---|---|---|---|---|---|---|---|
| YUII | compra | 2011-06-15 | 2011-12-13 | 126 | -82.84 | -4.29 | -7.18 | -75.67 |
| CPF | compra | 2011-02-24 | 2011-08-24 | 126 | -62.71 | -4.21 | -13.42 | -49.29 |
| NSIT | compra | 2008-06-03 | 2008-12-01 | 126 | -74.2 | -2.98 | -43.09 | -31.11 |
| ARLO | compra | 2018-08-13 | 2019-02-13 | 126 | -81.45 | -2.73 | -8.37 | -73.09 |
| OFIX | compra | 2008-05-09 | 2008-11-06 | 126 | -63.55 | -2.68 | -30.71 | -32.83 |
| SRNE | compra | 2017-02-06 | 2017-08-07 | 126 | -65.6 | -2.65 | 3.69 | -69.3 |
| RLMD | compra | 2024-09-12 | 2025-03-17 | 126 | -91.18 | -2.58 | -4.39 | -86.79 |
| TROX | compra | 2015-06-03 | 2015-12-01 | 126 | -62.58 | -2.55 | -4.01 | -58.57 |
| PMNT | compra | 2024-02-15 | 2024-08-16 | 126 | -78.63 | -2.36 | 1.86 | -80.49 |
| TGIC | compra | 2007-11-09 | 2008-05-13 | 126 | -74.52 | -2.27 | -4.92 | -69.6 |

O que deu certo: EXEL 2010 (+267% em 6 meses), TNDM 2018 (+1.209%), JAZZ 2010, CLW 2009 — biotechs/small caps no fundo do ciclo.
O que deu errado: YUII/CPF 2011 (China small caps, fraude/colapso), RLMD 2024, ARLO 2018 — "compra de apoio" dos diretores em queda.

**Próximo passo (se insistir):** compras de valor alto relativo ao patrimônio do insider e às compras passadas dele
("oportunistas" de Cohen-Malloy-Pomorski), em empresas sem cobertura de analistas; mas o OOS atual não justifica capital.

---

## G3 — Spin-offs após a venda forçada (Form 10-12B)

**Tese de mesa:** a separada nasce pequena, fora do mandato de quem tinha a controladora; fundos de índice e gestores vendem nas
primeiras semanas sem olhar preço. Quando essa venda acaba, o preço passa a refletir o negócio (e a gestão, agora com opções da
própria empresa, tem incentivo).

**Implementação:** CIK que arquivou 10-12B (2006+) → ticker pelos Forms 3/4 dos próprios diretores (pega deslistadas) → Yahoo.
Só vale se o 1º preço vier até 1 ano depois do 10-12B e não houver preço antes (empresa nova). Compra `espera` = 10/20/40 pregões
depois do 1º preço, segura 126/252 pregões, 5% por nome, hedge IWM, custo 20 bps. 153 negócios (61 OOS).

**Resultado:** escolhido `{'espera': 40, 'dias': 126}`; IR IS 0,9; OOS 20,7% a.a. vs 11,4% do benchmark (IR 1,4, vol 5,7%, pior queda -4,5%), P(bater) 100%, PBO 34%. Todas as 6 variantes batem o CDI no OOS (mediana +11 pp). PBO 34%.
**Checagem anti-autoengano (Sharpe 1,44 OOS):** não achei look-ahead (data do 1º preço é pública; entra 40 pregões depois);
os nomes são spin-offs reais (CEG/Exelon, GEV/GE, SNDK/WDC, GRAL/Illumina, Q/DuPont, SOLS/Honeywell, JXN/Prudential plc, SLVM/IP...).
Falso positivo achado: XPEL 2019 (Form 10 por *uplisting*, não spin) — 1 em 153. O resultado depende da cauda: sem os 5 melhores OOS
o excesso cai para ~3,4 pp/ano (Sharpe ~0,7). Viés: separadas que foram compradas ou quebraram em < 1 ano faltam (10–25% no OOS).

**Excesso sobre o CDI por ano (pp):** 2008: +0.9, 2009: +23.1, 2010: +1.0, 2011: -1.0, 2012: +5.1, 2013: +3.8, 2014: -4.2, 2015: -2.4, 2016: +10.4, 2017: +6.1, 2018: +2.0, 2019: +11.3, 2020: +4.3, 2021: +5.0, 2022: +5.1, 2023: +11.4, 2024: +7.5, 2025: +17.2, 2026: +7.6

**10 melhores negócios (contribuição ao fundo, % do PL):**

| ativo | lado | entrada | saida | dias | retorno % | contrib % | hedge % | ret - hedge % |
|---|---|---|---|---|---|---|---|---|
| CLW | compra | 2009-02-05 | 2009-08-06 | 126 | 270.34 | 8.43 | 23.65 | 246.69 |
| VRTS | compra | 2009-03-04 | 2009-09-01 | 126 | 264.8 | 7.28 | 52.07 | 212.73 |
| SNDK | compra | 2025-04-14 | 2025-10-14 | 126 | 271.73 | 7.16 | 30.92 | 240.81 |
| TREE | compra | 2008-10-09 | 2009-04-13 | 126 | 142.03 | 6.25 | -5.74 | 147.78 |
| RHLD | compra | 2025-04-23 | 2025-10-22 | 126 | 195.2 | 6.22 | 26.01 | 169.19 |
| GRAL | compra | 2024-08-12 | 2025-02-12 | 126 | 149.82 | 5.64 | 7.57 | 142.25 |
| PRTA | compra | 2013-02-22 | 2013-08-22 | 126 | 169.65 | 5.44 | 13.84 | 155.81 |
| TRAX | compra | 2026-06-03 | 2026-10-14 | 92 | 119.74 | 5.2 | -6.5 | 126.24 |
| CARR | compra | 2020-05-18 | 2020-11-13 | 126 | 119.39 | 4.11 | 31.64 | 87.75 |
| CTRE | compra | 2014-07-28 | 2015-01-27 | 126 | 72.16 | 3.64 | 5.68 | 66.48 |

**10 piores:**

| ativo | lado | entrada | saida | dias | retorno % | contrib % | hedge % | ret - hedge % |
|---|---|---|---|---|---|---|---|---|
| CVEO | compra | 2014-07-17 | 2015-01-15 | 126 | -86.52 | -7.57 | 2.74 | -89.27 |
| RYAM | compra | 2014-08-13 | 2015-02-12 | 126 | -49.18 | -3.22 | 7.18 | -56.36 |
| CC | compra | 2015-08-18 | 2016-02-18 | 126 | -58.62 | -3.1 | -16.62 | -42.0 |
| KD | compra | 2021-12-21 | 2022-06-23 | 126 | -46.83 | -2.62 | -22.03 | -24.8 |
| RNA | compra | 2026-04-28 | 2026-10-14 | 117 | -39.86 | -2.22 | -2.15 | -37.72 |
| BHM | compra | 2022-11-25 | 2023-05-30 | 126 | -37.04 | -2.11 | -6.83 | -30.2 |
| ONL | compra | 2022-01-24 | 2022-07-26 | 126 | -36.1 | -2.07 | -11.02 | -25.08 |
| KN | compra | 2014-04-15 | 2014-10-14 | 126 | -33.49 | -1.89 | -4.43 | -29.06 |
| DNOW | compra | 2014-07-18 | 2015-01-16 | 126 | -29.58 | -1.63 | 2.82 | -32.4 |
| FDXF | compra | 2026-07-27 | 2026-10-14 | 56 | -28.3 | -1.59 | -7.9 | -20.4 |

O que deu certo, concreto: SNDK — Sandisk separada da Western Digital em fev/2025; comprei 40 pregões depois (14/04/2025) e em 6 meses
subiu +272% (IWM +31%): o mercado vendeu a "memória NAND commodity" e veio o ciclo de IA. GEV — GE Vernova, comprada em 24/05/2024,
+92% em 6 meses. CEG — Constellation (Exelon), +82% em 2022 com o IWM −13%. GRAL (Illumina obrigada a se desfazer pela FTC/UE):
venda forçada de verdade, +150%. Padrão: a separada que a controladora "queria se livrar" e que o índice vendeu.
O que deu errado: CVEO 2014 (Civeo, acomodações para petróleo, −87% no colapso do petróleo), RYAM/CC 2014–15 (químicas alavancadas),
KD 2021 (Kyndryl, −47%). Spin de negócio ruim e alavancado em setor em queda continua ruim.

**Próximo passo:** filtrar por alavancagem (dívida empurrada para a separada) e por setor em tendência; testar espera maior
(60 pregões) e vender a controladora como hedge em vez de IWM.

---

## G4 — Calendário de fluxo EUA

**Tese de mesa:** fluxos que não olham preço e têm data marcada: (a) *turn of the month* (salário/aporte de previdência entra no 1º dia),
(b) *tax-loss selling* (small caps perdedoras vendidas até meados de dezembro e recompradas em janeiro), (c) fundos balanceados e de
pensão rebalanceando no fim do mês: se ações subiram mais que títulos, vendem ações nos últimos dias.

**Implementação:** (a) SPY nos pregões −1,+1,+2,+3; (b) IWM−SPY de 16/12 a 15/01; (c) no dia −6 mede SPY/TLT no mês; nos dias −4..−1
vende 0,5 SPY e compra 0,5 TLT se ações ganharam (e o inverso). Datas conhecidas de antemão → decisão 2 pregões antes. Vol-alvo
5%/10% enquanto posicionado. Custo 3 bps.

**Resultado:** escolhido `{'comp': 'rebal', 'alvo': 0.05}`; IR IS 0,6; OOS 12,1% a.a. vs 11,4% do benchmark (IR 0,3, vol 1,9%, pior queda -1,1%), P(bater) 78%, PBO 40%. Por componente (excesso a.a. em USD, Sharpe): tom IS +0,5 pp (0,19) / OOS +0,4 pp (0,23);
taxloss IS +0,3 (0,27) / OOS +0,8 (0,42); rebal IS +1,5 (0,60) / OOS +0,7 (0,39); todos IS +1,7 (0,49) / OOS +1,4 (0,54).
Pequeno, mas todas as 8 variantes batem o CDI no OOS. É o único "fluxo" que sobreviveu, e o efeito é do tamanho do custo para
quem paga mais que 3 bps.

**Excesso sobre o CDI por ano (pp):** 2008: +5.3, 2009: +2.3, 2010: +0.4, 2011: +1.3, 2012: +0.8, 2013: -0.1, 2014: +0.7, 2015: +1.3, 2016: +1.6, 2017: +2.7, 2018: +4.2, 2019: -2.1, 2020: +0.8, 2021: +1.3, 2022: +3.2, 2023: -0.9, 2024: +3.3, 2025: -1.2, 2026: -2.0

**10 melhores negócios (contribuição ao fundo, % do PL):**

| ativo | lado | entrada | saida | dias | retorno % | contrib % |
|---|---|---|---|---|---|---|
| SPY | compra | 2008-10-27 | 2008-10-31 | 4 | 15.33 | 2.97 |
| SPY | compra | 2008-11-21 | 2008-11-28 | 4 | 13.29 | 2.13 |
| SPY | venda | 2020-02-24 | 2020-02-28 | 4 | 8.53 | 2.02 |
| SPY | compra | 2018-12-24 | 2018-12-31 | 4 | 6.61 | 1.69 |
| SPY | compra | 2007-11-26 | 2007-11-30 | 4 | 5.42 | 1.53 |
| SPY | venda | 2022-08-25 | 2022-08-31 | 4 | 6.06 | 1.18 |
| TLT | compra | 2021-11-23 | 2021-11-30 | 4 | 4.91 | 1.07 |
| SPY | compra | 2020-03-25 | 2020-03-31 | 4 | 4.44 | 1.07 |
| SPY | compra | 2015-08-25 | 2015-08-31 | 4 | 5.55 | 1.04 |
| SPY | compra | 2011-11-23 | 2011-11-30 | 4 | 7.23 | 1.01 |

**10 piores:**

| ativo | lado | entrada | saida | dias | retorno % | contrib % |
|---|---|---|---|---|---|---|
| SPY | compra | 2007-07-25 | 2007-07-31 | 4 | -3.96 | -1.27 |
| SPY | compra | 2007-02-22 | 2007-02-28 | 4 | -3.46 | -1.27 |
| SPY | venda | 2022-07-25 | 2022-07-29 | 4 | -4.06 | -0.84 |
| TLT | venda | 2019-05-24 | 2019-05-31 | 4 | -3.06 | -0.79 |
| TLT | venda | 2007-02-22 | 2007-02-28 | 4 | -2.1 | -0.79 |
| SPY | compra | 2021-09-24 | 2021-09-30 | 4 | -3.33 | -0.77 |
| SPY | compra | 2022-06-24 | 2022-06-30 | 4 | -3.31 | -0.7 |
| SPY | compra | 2019-05-24 | 2019-05-31 | 4 | -2.69 | -0.69 |
| SPY | compra | 2008-06-24 | 2008-06-30 | 4 | -2.47 | -0.66 |
| SPY | venda | 2020-05-22 | 2020-05-29 | 4 | -2.95 | -0.65 |

O que deu certo: fins de mês de pânico em que as ações caíram muito no mês (out/2008: comprei SPY nos 4 últimos pregões, +15%;
dez/2018 +6,6%; mar/2020 +4,4%) — os balanceados compram ações para voltar ao 60/40. E os inversos (fev/2020: vendi SPY, +8,5%).
O que deu errado: meses em que o movimento do mês continuou (jul/2022 −4%).

---

## G5 — Fronteira: momentum 12-1 com filtro de câmbio (vs EEM)

**Tese de mesa:** fluxo estrangeiro em fronteira é lento e pró-cíclico; a moeda caindo antecipa saída. Top 3/5 de 21 ETFs
(VNM, AFK, KSA, QAT, UAE, KWT, ARGT, TUR, GREK, EIDO, EPHE, EPU, ECH, EZA, INDA, THD, EWM, EPOL, EWZ, EWW, ECNS) por retorno 12-1m,
só se a moeda não caiu em 3 meses; vende EEM na mesma soma. Custo 5–50 bps por perna (VNM/AFK/KWT 50).

**Resultado:** escolhido `{'n': 3, 'filtro_fx': 1, 'hedge': 'EEM'}`; IR IS -0,5; OOS 11,7% a.a. vs 11,4% do benchmark (IR 0,1, vol 14,7%, pior queda -21,5%), P(bater) 49%, PBO 74%. IS negativo em todas as variantes (−8%/ano contra EEM em 2014–2020): o momentum de país foi destruído por
reversões (Argentina 2019, Turquia, Grécia 2015). O OOS positivo (2021–22) veio de estar comprado em ECNS/México/Peru e vendido em
EEM durante a queda da China. PBO 74% — não confiar.

**Excesso sobre o CDI por ano (pp):** 2012: +2.7, 2013: +28.8, 2014: -15.2, 2015: -21.6, 2016: -1.7, 2017: -17.2, 2018: -3.2, 2019: -18.8, 2020: -24.9, 2021: +9.7, 2022: +13.0, 2023: -4.5, 2024: +1.1, 2025: +6.9, 2026: -21.5

**10 melhores negócios (contribuição ao fundo, % do PL):**

| ativo | lado | entrada | saida | dias | retorno % | contrib % |
|---|---|---|---|---|---|---|
| ECNS | compra | 2020-04-01 | 2021-08-02 | 336 | 64.39 | 17.88 |
| ECH | compra | 2009-02-02 | 2009-10-01 | 168 | 43.69 | 17.52 |
| EWM | compra | 2006-11-01 | 2007-08-01 | 186 | 42.57 | 15.9 |
| EWW | compra | 2006-08-01 | 2006-12-01 | 86 | 18.89 | 15.35 |
| ECNS | compra | 2011-10-03 | 2012-01-03 | 63 | 10.19 | 13.87 |
| EWZ | compra | 2007-01-03 | 2007-09-04 | 168 | 30.17 | 12.99 |
| EPHE | compra | 2012-07-02 | 2013-05-01 | 207 | 38.54 | 11.02 |
| EZA | compra | 2009-05-01 | 2009-10-01 | 106 | 29.9 | 9.44 |
| EWZ | compra | 2009-04-01 | 2009-05-01 | 21 | 19.2 | 9.22 |
| GREK | compra | 2025-07-01 | 2026-07-01 | 251 | 27.89 | 9.03 |

**10 piores:**

| ativo | lado | entrada | saida | dias | retorno % | contrib % |
|---|---|---|---|---|---|---|
| ARGT | compra | 2019-08-01 | 2019-09-03 | 22 | -31.85 | -11.65 |
| THD | compra | 2011-08-01 | 2011-10-03 | 44 | -29.99 | -11.49 |
| EIDO | compra | 2011-08-01 | 2011-10-03 | 44 | -30.86 | -11.32 |
| GREK | compra | 2014-11-03 | 2015-02-02 | 61 | -26.64 | -11.29 |
| ECNS | compra | 2015-05-01 | 2016-04-01 | 231 | -31.3 | -10.01 |
| UAE | compra | 2020-03-02 | 2020-04-01 | 22 | -25.34 | -8.96 |
| EWM | compra | 2009-01-02 | 2009-02-02 | 20 | -8.12 | -8.52 |
| EZA | compra | 2008-06-02 | 2008-10-01 | 85 | -22.63 | -8.43 |
| QAT | compra | 2015-06-01 | 2016-01-04 | 150 | -21.39 | -7.72 |
| EWW | compra | 2008-03-03 | 2008-10-01 | 148 | -17.64 | -7.08 |

---

## G6 — Fronteira: compra depois da crise

**Tese de mesa:** depois de queda > 40–60% do topo de 3 anos, o estrangeiro já saiu e o país está barato; compra quando o retorno de 1
mês vira positivo, 20% do PL por país por 6–12 meses, resto em ACWI.

**Resultado:** escolhido `{'queda': 0.4, 'meses': 6}`; IR IS 0,8; OOS 19,1% a.a. vs 21,1% do benchmark (IR -0,3, vol 16,4%, pior queda -20,0%), P(bater) 26%, PBO 3%. IS espetacular (2009: EWZ +117%, TUR +91%, EZA +71%; 2016; 2020: ARGT +63%, EZA +67%), OOS abaixo do ACWI
(só 5 entradas; ECNS 2022–25 −18%). Não há métrica de valuation (P/L de país) nos dados — o "barato" é só o drawdown.
**Viés de sobrevivência grave** (Rússia, Nigéria, Egito, Paquistão, Colômbia ausentes) → o IS é teto.

**Excesso sobre o ACWI por ano (pp):** 2012: +7.5, 2013: +1.8, 2014: +8.2, 2015: -14.3, 2016: +39.1, 2017: +14.4, 2018: +1.3, 2019: -2.0, 2020: +58.9, 2021: -12.3, 2022: +10.3, 2023: -11.0, 2024: -1.7, 2025: +2.5, 2026: -2.1

**10 melhores negócios (contribuição ao fundo, % do PL):**

| ativo | lado | entrada | saida | dias | retorno % | contrib % |
|---|---|---|---|---|---|---|
| EWZ | compra | 2009-01-02 | 2009-12-01 | 230 | 116.55 | 17.38 |
| TUR | compra | 2009-04-01 | 2009-11-02 | 149 | 91.48 | 14.02 |
| EZA | compra | 2008-12-01 | 2009-11-02 | 232 | 71.34 | 12.66 |
| ECH | compra | 2008-12-01 | 2009-08-03 | 168 | 80.54 | 12.41 |
| THD | compra | 2009-04-01 | 2009-11-02 | 149 | 72.96 | 11.62 |
| EZA | compra | 2020-05-01 | 2021-03-01 | 208 | 67.38 | 11.05 |
| ARGT | compra | 2020-05-01 | 2020-12-01 | 148 | 63.22 | 10.29 |
| EWZ | compra | 2015-11-02 | 2017-01-03 | 294 | 51.15 | 10.1 |
| EWM | compra | 2008-12-01 | 2009-10-01 | 210 | 58.2 | 9.81 |
| EWW | compra | 2009-01-02 | 2009-12-01 | 230 | 48.07 | 9.15 |

**10 piores:**

| ativo | lado | entrada | saida | dias | retorno % | contrib % |
|---|---|---|---|---|---|---|
| ECNS | compra | 2022-09-01 | 2025-04-01 | 646 | -18.12 | -1.79 |
| TUR | compra | 2015-11-02 | 2016-09-01 | 210 | -11.7 | -1.72 |
| EIDO | compra | 2026-08-03 | 2026-10-14 | 51 | -7.15 | -1.44 |
| GREK | compra | 2015-03-02 | 2018-06-01 | 820 | -23.83 | -0.55 |
| ECH | compra | 2014-03-03 | 2014-09-02 | 127 | 3.86 | 0.79 |
| VNM | compra | 2022-12-01 | 2023-12-01 | 251 | 3.18 | 1.06 |
| ECH | compra | 2021-12-01 | 2022-07-01 | 146 | 3.28 | 1.29 |
| ECH | compra | 2015-11-02 | 2016-09-01 | 210 | 6.66 | 1.55 |
| ARGT | compra | 2012-08-01 | 2014-02-03 | 377 | 8.66 | 2.25 |
| ECNS | compra | 2016-03-01 | 2016-09-01 | 129 | 12.26 | 2.45 |

---

## G7 — Argentina: CCL implícito por ação (local/ADR)

**Tese de mesa:** cada par ADR/ação .BA implica um dólar CCL; em cepo (2011–15, 2019–24) a arbitragem direta é limitada (parking,
restrições do BCRA), então o CCL de uma ação pode se descolar dos outros; quem ajusta seria o ADR.

**Implementação:** 13 pares (YPF, GGAL, BMA, PAM, TEO, CRESY, LOMA, SUPV, TGS, CEPU, EDN, IRS, BBAR). Sinal = log(local/ADR) contra a
média de 20/60 dias, menos a mediana das outras ações; compra o ADR cujo CCL subiu (local cara/ADR barato), vende os outros,
neutro em dólar, máx. 25% por nome. Só a perna NY (15 bps/perna, aluguel 3% a.a.). Rebalanceio diário/semanal/mensal.

**Bug achado e corrigido:** TX (Ternium S.A., Luxemburgo) **não** é o ADR de TXAR.BA (Ternium Argentina) — o par gerava os maiores
"negócios" (−83%/+14%). Removido.

**Resultado:** escolhido `{'sinal': 'dispersao', 'janela': 60, 'freq': 'W'}`; IR IS 0,1; OOS 12,8% a.a. vs 11,4% do benchmark (IR 0,2, vol 17,1%, pior queda -32,8%), P(bater) 59%, PBO 25%. O sinal existe mas é curto: bruto de custos, diário, rende +21 a +25%/ano IS e +9 a +12% OOS (Sharpe 0,6–1,4), mas gira
~250x/ano e o custo leva a −15 a −26%/ano. Semanal sobra ~0 a +1%; mensal, nada. O efeito "mesmo dia" (sinal e retorno no mesmo
pregão) dá Sharpe 3–4 — é o descompasso de fechamento (BYMA fecha 1h antes de NY no inverno) e não é executável.
Variante "brecha" (cesta comprada quando a brecha CCL/oficial cai em 1 mês): −4%/ano IS, +3,9% OOS, sem robustez — não entrou na grade.

**Excesso sobre o CDI por ano (pp):** 2010: +8.1, 2011: +4.5, 2012: +24.6, 2013: -24.2, 2014: -1.3, 2015: -1.7, 2016: -12.9, 2017: -15.1, 2018: +16.8, 2019: +17.8, 2020: -0.7, 2021: +22.0, 2022: -37.3, 2023: +8.2, 2024: +11.9, 2025: +16.3, 2026: -2.6

**10 melhores negócios (contribuição ao fundo, % do PL):**

| ativo | lado | entrada | saida | dias | retorno % | contrib % |
|---|---|---|---|---|---|---|
| IRS | venda | 2008-09-15 | 2008-11-03 | 35 | 84.7 | 12.74 |
| EDN | compra | 2021-08-09 | 2021-10-04 | 39 | 44.36 | 8.15 |
| SUPV | compra | 2020-05-11 | 2020-07-13 | 43 | 20.77 | 7.95 |
| CRESY | compra | 2024-10-28 | 2024-12-02 | 24 | 40.85 | 7.78 |
| SUPV | compra | 2025-10-06 | 2025-10-13 | 5 | 28.82 | 7.65 |
| SUPV | compra | 2022-12-19 | 2023-01-17 | 18 | 71.7 | 7.63 |
| EDN | venda | 2012-04-16 | 2012-04-23 | 5 | 32.11 | 7.3 |
| EDN | compra | 2014-02-10 | 2014-03-10 | 19 | 26.77 | 7.17 |
| BBAR | venda | 2014-01-27 | 2014-02-03 | 5 | 21.65 | 6.31 |
| GGAL | compra | 2010-10-04 | 2010-11-22 | 35 | 55.74 | 6.29 |

**10 piores:**

| ativo | lado | entrada | saida | dias | retorno % | contrib % |
|---|---|---|---|---|---|---|
| EDN | venda | 2013-09-03 | 2013-10-14 | 29 | -69.91 | -22.16 |
| BBAR | compra | 2008-09-29 | 2008-11-03 | 25 | -50.2 | -18.4 |
| TGS | venda | 2015-02-02 | 2015-04-06 | 43 | -47.72 | -14.65 |
| YPF | compra | 2009-01-26 | 2009-03-23 | 39 | -56.17 | -11.14 |
| BMA | compra | 2008-10-20 | 2008-11-03 | 10 | -32.44 | -9.67 |
| BBAR | venda | 2009-09-21 | 2009-11-09 | 35 | -34.59 | -8.55 |
| LOMA | venda | 2022-06-27 | 2022-09-06 | 49 | -33.34 | -8.16 |
| EDN | compra | 2008-07-21 | 2008-08-25 | 25 | -17.92 | -8.04 |
| SUPV | compra | 2019-12-30 | 2020-03-16 | 52 | -62.03 | -6.41 |
| CRESY | compra | 2006-05-08 | 2006-05-22 | 10 | -30.88 | -6.13 |

**Próximo passo:** fazer a arbitragem de verdade (comprar local em pesos/vender ADR) exige conta na Argentina e lida com o parking;
como mesa estrangeira, o que dá para fazer é usar o desvio como filtro de execução (comprar o ADR do par com CCL mais alto) num
livro comprado em Argentina — não como estratégia isolada.

---

## G8 — ADR x ação local por fuso

**Tese de mesa:** o ADR negocia horas depois do fechamento local; o prêmio do ADR sobre a local (em USD, contra a média de 20 dias)
prevê a abertura local seguinte. A abertura (gap) não é capturável; o teste honesto é comprar/vender a ação local na ABERTURA e zerar
no fechamento.

**Medido (2006–2026, beta de regressão do retorno local no prêmio do ADR):** o gap da abertura absorve 30–90% do prêmio
(HK 0,85; Japão 0,6–0,8; Europa 0,3–0,6; Índia 0,1–0,4). O que sobra para o pregão é pequeno: Índia +0,04 a +0,08, Coreia +0,10 a +0,15
(OOS), HK +0,01 a +0,09, Japão ~+0,02, Europa **negativo** OOS (−0,05 a −0,16: a abertura europeia exagera e reverte).
Bruto de custos, Ásia com limiar 1% tem Sharpe 2–3 OOS; com 10 bps + imposto local (TW 0,15% day-trade, HK 0,26%, KR 0,2%,
Londres 0,5%, Paris 0,3%) vira zero ou negativo em todos os mercados.

**Bug achado e corrigido:** o Yahoo grava, para ações japonesas antes de 2010, a abertura ≈ fechamento do dia anterior. O "intradiário"
virava close-to-close e o fundo Japão dava +275 pp em 2008 (IR IS 1,8). Dias com |gap| < 0,05% descartados e início em 2011.

**Resultado:** escolhido `{'regiao': 'india+coreia', 'thr': 0.02}`; IR IS -0,2; OOS 10,8% a.a. vs 11,4% do benchmark (IR -0,2, vol 3,1%, pior queda -4,3%), P(bater) 32%, PBO 3%.

**Excesso sobre o CDI por ano (pp):** 2011: -3.6, 2012: -8.2, 2013: +3.1, 2014: +2.8, 2015: +4.1, 2016: +0.6, 2017: -3.9, 2018: -6.4, 2019: +2.8, 2020: -2.4, 2021: -0.3, 2022: +0.1, 2023: +1.0, 2024: -3.9, 2025: +0.6, 2026: -1.1

**10 melhores negócios (contribuição ao fundo, % do PL):**

| ativo | lado | entrada | saida | dias | sinal % | retorno % | contrib % |
|---|---|---|---|---|---|---|---|
| WIPRO.NS | compra | 2006-05-23 | 2006-05-23 | 1 | 3.53 | 18.54 | 1.84 |
| DRREDDY.NS | compra | 2006-05-02 | 2006-05-02 | 1 | 8.98 | 15.96 | 1.58 |
| 105560.KS | compra | 2020-03-20 | 2020-03-20 | 1 | 5.91 | 15.98 | 1.57 |
| HDFCBANK.NS | venda | 2005-03-24 | 2005-03-24 | 1 | -4.16 | 14.0 | 1.38 |
| ICICIBANK.NS | venda | 2008-10-10 | 2008-10-10 | 1 | -10.12 | 13.42 | 1.33 |
| 055550.KS | compra | 2008-11-26 | 2008-11-26 | 1 | 2.13 | 13.35 | 1.3 |
| INFY.NS | compra | 2020-03-24 | 2020-03-24 | 1 | 3.9 | 12.99 | 1.28 |
| ICICIBANK.NS | compra | 2008-04-08 | 2008-04-08 | 1 | 3.87 | 12.04 | 1.19 |
| ICICIBANK.NS | venda | 2006-09-29 | 2006-09-29 | 1 | -2.95 | 12.02 | 1.19 |
| DRREDDY.NS | venda | 2008-10-06 | 2008-10-06 | 1 | -9.0 | 11.88 | 1.17 |

**10 piores:**

| ativo | lado | entrada | saida | dias | sinal % | retorno % | contrib % |
|---|---|---|---|---|---|---|---|
| 005490.KS | venda | 2008-10-28 | 2008-10-28 | 1 | -2.46 | -19.6 | -1.99 |
| 055550.KS | compra | 2008-10-29 | 2008-10-29 | 1 | 8.41 | -18.08 | -1.84 |
| 105560.KS | compra | 2008-10-29 | 2008-10-29 | 1 | 12.05 | -17.53 | -1.78 |
| DRREDDY.NS | venda | 2008-02-29 | 2008-02-29 | 1 | -2.94 | -16.73 | -1.69 |
| 055550.KS | venda | 2008-11-21 | 2008-11-21 | 1 | -6.42 | -16.33 | -1.66 |
| 005490.KS | compra | 2008-10-24 | 2008-10-24 | 1 | 3.26 | -15.5 | -1.58 |
| ICICIBANK.NS | compra | 2008-03-19 | 2008-03-19 | 1 | 5.56 | -14.55 | -1.47 |
| ICICIBANK.NS | venda | 2006-09-25 | 2006-09-25 | 1 | -3.82 | -14.22 | -1.44 |
| 005490.KS | venda | 2008-11-21 | 2008-11-21 | 1 | -4.66 | -12.22 | -1.25 |
| 055550.KS | venda | 2008-11-07 | 2008-11-07 | 1 | -6.45 | -12.0 | -1.23 |

**Conclusão:** não é arbitragem impossível como no Brasil — o efeito existe e é medido —, mas o mercado local já precifica quase tudo na
abertura e o resto é do tamanho do imposto. Só viável para quem tem custo de market maker (Índia/Coreia com DMA e rebate).

---

## Ideias não testadas (por quê)

- **Inclusão no S&P 500 (anúncio → efetivação):** precisa da data do ANÚNCIO (comunicado da S&P DJI); a Wikipedia só tem a data de
  efetivação. Usar efetivação − 5 dias seria look-ahead nos casos de substituição às pressas. Fica para quando houver a base de anúncios.
- **Crowding 13F:** os data sets 13F (2013+) têm ~100 MB/trimestre e vêm por CUSIP; o mapa CUSIP→ticker histórico não é público e a
  cobertura de preços das ações abandonadas (as que interessam) sofre o mesmo viés de deslistagem. Custo/benefício ruim nesta rodada.
- **Merger arb por negócio:** ver viés acima — sem preço das deslistadas, qualquer número é anti-sobrevivência.

## Lições para quem reler

1. Em eventos corporativos EUA, **o Yahoo é a maior fonte de viés**: some quem foi comprado (merger arb fica só com fracassos) e quem
   quebrou (insiders/spin-offs ficam otimistas no passado). Meça a cobertura por ano antes de acreditar em qualquer IS.
2. Insider cluster e merger arb via ETF são estratégias "de livro" que **pararam** depois de 2020; spin-off ainda paga.
3. Lead-lag de fuso e CCL argentino são reais **bruto**; líquido de custo e imposto, não.
4. Yahoo intradiário antigo (Open) não é confiável para Japão < 2010; Ternium ≠ Ternium Argentina.
5. Arquivos: `resultado/ideias_global.pkl` (lista de dicts do `roda` + `contrib` (formato longo quando > 60 ativos) + `trades`;
   G1 traz também `eventos_alvos`), `resultado/ideias_global_log.txt`.
