# Frente I_MACRO_ACOES — ações e macro do Brasil/rodada 1 replicados em EUA, Europa e Ásia (FASE 2, out/2026)

Código: `quant/fundos/ideias_i_macro_acoes.py` (`python ideias_i_macro_acoes.py dados` baixa com cache; `python ideias_i_macro_acoes.py [IM1 ...]`
roda e salva `resultado/ideias_i_macro_acoes.pkl`, log em `resultado/ideias_i_macro_acoes_log.txt`). Cada dict do pkl tem `contrib`
(contribuição diária por par/ativo/manga, em fração do PL, no calendário do próprio mercado, excesso em USD antes da conversão) e
`trades` (ativo/par, lado, entrada, saída, dias, retorno, contribuição, sinal na entrada, mercado).

Convenções: todo excesso é em USD sobre o T-bill (ou retorno local − juro local quando a posição é hedgeada via futuro de índice) e vira
R$ com `brl()`: fundo = CDI + excesso. Cada mercado no SEU calendário (o `shift` de execução é o pregão seguinte daquele mercado, não o
dia seguinte da união de calendários). Decisão no fechamento de t, execução no fechamento seguinte; datas de calendário conhecidas de
antemão (feriados, Ramadã, ano-novo lunar, eleições) → ordem 2 pregões antes. Benchmark CDI em todos (todos são long-short ou
eventuais). Corte OOS 2021-01-01. Nada de regime genérico na grade (o executor aplica `regimes.py` depois).

Escopo: NÃO refiz eventos corporativos, crédito/juros (carry G10+LatAm, real tático) nem arbitragem/commodities (outras frentes).
O IM5 usa VALOR/PPP + juro REAL com stop — não é o carry nominal.

## Resumo

| Fundo | Escolhido no IS | IR IS | OOS a.a. | CDI OOS | IR OOS | vol OOS | P(bater) | PBO | custo x2 (pp) | +1 dia (pp) | variantes > CDI OOS |
|---|---|---|---|---|---|---|---|---|---|---|---|
| IM1 Pares intra-setor globais (KO/PEP, V/MA, bancos, Toyota/Honda, TSMC/UMC...) | `{'jan': 63, 'z_in': 2.0, 'filtro': 'coint'}` | 0,39 | 5,9% | 11,4% | -0,60 | 7,9% | 6% | 37% | -9,2 | -5,4 | 0% |
| IM2 Reversão de curto prazo em large caps (EUA/Japão/Europa) | `{'L': 21, 'vix': 1, 'regiao': 'jp'}` | 0,02 | 17,3% | 11,4% | 0,57 | 9,9% | 91% | 16% | 5,0 | 6,5 | 25% |
| IM3 Ações sensíveis a crédito quando o HY abre (EUA) | `{'thr': 0.015, 'saida': '63d', 'lado': 'vende'}` | 0,33 | 4,7% | 11,4% | -0,78 | 7,6% | 4% | 64% | -6,9 | -5,9 | 25% |
| IM4 Rotação de países: valor + momento + carry (L/S) | `{'sinal': 'valor+mom+carry', 'hedge': 'piores'}` | -0,08 | 12,0% | 11,4% | 0,10 | 11,7% | 52% | 52% | -1,0 | 0,4 | 75% |
| IM5 Moedas EM/G10 por valor (PPP) e juro real, com stop | `{'sinal': 'ppp+juro_real', 'stop': 0.03}` | 0,74 | 8,1% | 11,4% | -0,53 | 5,4% | 7% | 31% | -4,1 | -2,8 | 33% |
| IM6 CTA global com risco de mesa (vol por ativo, stop de crise) | `{'modo': 'cta', 'janelas': 'lento'}` | 0,28 | 9,2% | 11,4% | -0,13 | 11,0% | 29% | 8% | -3,2 | -2,8 | 0% |
| IM7 Tendência de crises (vendido em ações só quando o crédito abre) | `{'thr': 0.015, 'tlt': 1}` | 0,01 | 9,8% | 11,4% | -0,18 | 6,6% | 25% | 8% | -1,9 | -3,6 | 0% |
| IM8 Calendário global (virada de mês, feriados, Ano-Novo Lunar, Ramadã, inverno x verão) | `{'comp': 'tudo'}` | 0,31 | 9,3% | 11,4% | -0,08 | 13,1% | 39% | 88% | -4,8 | -2,0 | 50% |
| IM9 Eleições: compra depois do pânico, com hedge cambial | `{'queda': 0.03, 'dias': 63, 'veiculo': 'etf'}` | -0,04 | 13,2% | 11,4% | 0,30 | 5,8% | 76% | 82% | 1,6 | 1,3 | 88% |

Veredito curto:
- **Nada aqui é alfa comprovado.** Nenhum fundo tem IS e OOS bons ao mesmo tempo. Os três com OOS positivo (IM2, IM9, IM4) foram
  escolhidos com IR IS ≈ 0 — o OOS bom é "sorte de regime", não confirmação.
- **Mais interessante para continuar: IM2 reversão mensal no Japão só com VIX alto** (OOS +6 pp/ano em USD, IR 0,57, P 91%, PBO 16%,
  sobrevive a custo x2 e +1 dia) — mas IS ≈ 0 (2009–20) e 1/3 do OOS é um único negócio (SoftBank vendido em nov/2025, +6,8% do PL).
  E **IM9 eleições** (OOS +1,8 pp, 88% das variantes > CDI, robusto a custo/atraso), com só 20 negócios e IS negativo.
- **Morreu no OOS o que era bom no IS**: pares (IM1, IS IR 0,39 → −5,5 pp/ano OOS, 0% das variantes > CDI), moedas por PPP+juro real
  (IM5, IS IR 0,74 → −3,3 pp OOS; o PPP sozinho −8 pp/ano: iene "barato" ficou mais barato), crédito-ações (IM3), CTA (IM6).
- **Achados de mesa (negativos, mas úteis):** (1) vender as ações sensíveis a crédito quando o HY abre funcionou até 2020 e perdeu
  muito em 2022–23; o lado contrário (comprar depois do pânico) é que ganhou no OOS — o mesmo padrão do G6/E9: depois de 2009 os
  pânicos de crédito foram comprados pelo Fed. (2) "Tendência de crises" vendida em ações perde: os gatilhos de crédito aparecem
  perto do fundo (abr/2025, out/2015). (3) Calendário: só "véspera de feriado nos EUA" e "virada de mês na Alemanha" sobrevivem com
  sinal pequeno; Ramadã no Golfo é ruído caro (−5,5 pp/ano OOS).

## Dados novos (quant/fundos/dados/)

| arquivo | conteúdo |
|---|---|
| `y_imacro_acoes.parquet` | Yahoo (fechamento ajustado) de 260 ações: as 92 pernas dos pares + 100 large caps EUA + 60 Japão + 60 Europa |
| `y_imacro_idx.parquet` | 35 índices locais (Nikkei, DAX, FTSE, CAC, MIB, IBEX, SMI, AEX, OMX, ASX, TSX, IPC, Merval, BIST, Nifty, Sensex, JCI, Kospi, Taiex, HSI, KLCI, Stoxx50, Shanghai, STI, NZ50, Bovespa, Atenas...). Falharam: SET (Tailândia), PSEi, WIG20, TASI, BUX, IPSA, Peru |
| `bis_cpi.parquet` | BIS WS_LONG_CPI (índice, mensal, 63 países, 1995+) — CPI de Taiwan, Vietnã e Catar não existe |
| `bis_reer.parquet` | BIS WS_EER câmbio efetivo REAL amplo (64 países, mensal 1995+) — sem Vietnã/Catar |

Não baixou: ROG.SW (Roche, par NOVN x ROG removido); "B"/"GOLD" no Yahoo misturam Barnes Group/Randgold com Barrick → par de ouro
ficou só NEM x AEM.

### Armadilhas encontradas (para não repetir)
1. **OAS do high yield (ICE/BofA) no FRED só tem os últimos 3 anos** (`BAMLH0A0HYM2` começa em 2023-10 no `fred_diario.parquet`): o ICE
   restringiu o histórico. Quem usar spread de crédito antes de 2023 está usando NaN. Troquei por um fator de crédito negociável:
   HYG − β·IEF (β de 126 dias, só passado). Alternativa gratuita com histórico: Moody's `BAA10Y` no FRED.
2. **Erros do Yahoo em moedas que voltam em 2–3 pregões** (COP 11/07/2013 e 04/06/2015 = 100x; IDR dez/2013 alternando ±20%): o
   `base.limpa_fx` só olha o dia seguinte e deixou passar — o IM5 dava vol de 2.900%. Novo `limpa_fx3` (salto > 4% desfeito em até 3
   dias, em log). CLP +13% em 20/07/2022 é real (intervenção do BCCh) e foi mantido.
3. **Hedge de beta com beta parcial**: no IM3 usei o beta ao S&P da regressão de dois fatores (mercado + crédito) para o hedge; como as
   ações sensíveis a crédito têm beta total maior, o livro ficava comprado em mercado e o SPY virava o maior "negócio" (+17% do PL no
   IS). Corrigido para beta total.
4. **vol-alvo em estratégia intermitente** (só posicionada em episódios): o `vol_alvo` estima a vol com a carteira dos 63 dias
   anteriores, que estava zerada → alavancagem máxima na entrada. Use a vol da carteira candidata (que existe todo dia), congelada na entrada.
5. **Hedge cambial de Turquia/Argentina pelo juro de política é otimista**: em 2023 a política turca era 8,5% e o forward offshore
   implicava 30%+; o "BIST hedgeado" rendia +64% em 3 meses. Nas eleições TR/AR só uso o ETF em dólar.
6. Calendário da união de mercados: se juntar Tóquio, Londres e Nova York num índice só e fizer `shift(1)`, a execução cai num feriado
   local e vira execução no mesmo fechamento da decisão. Cada par/manga roda no próprio calendário e só a soma vai para o calendário B3.
7. Universos de large caps são a lista ATUAL (viés de sobrevivência): nas estratégias vendidas (IM3) o viés é contra (quem quebrou e
   seria o melhor short não está); na reversão (IM2) é a favor (as que caíram e nunca voltaram faltam).

---

## IM1 — Pares intra-setor globais

**Tese de mesa.** O análogo de ON×PN e PETR×PRIO: duas empresas com o mesmo negócio não divergem muito sem notícia. KO×PEP, V×MA, HD×LOW,
JPM×BAC, WFC×C, GS×MS, XOM×CVX, UPS×FDX, LMT×NOC, UNP×CSX, T×VZ, PG×CL, CAT×DE, NEM×AEM, MCD×YUM, MO×PM; Shell×BP, Barclays×Lloyds,
HSBC×StanChart, Vodafone×BT, DT×Orange, Telefónica×Orange, BNP×SocGen, Santander×BBVA, Intesa×UniCredit, Allianz×AXA, BMW×Mercedes,
E.ON×RWE, LVMH×Kering; Toyota×Honda, MUFG×SMFG, Mitsubishi×Mitsui, NTT×KDDI, Takeda×Astellas, Sony×Panasonic, TSMC×UMC, Samsung×Hynix,
KB×Shinhan, Hyundai×Kia, CCB×ICBC, China Mobile×Unicom, BHP×Rio (ASX), CBA×Westpac, NAB×ANZ, HDFC×ICICI, Infosys×TCS (46 pares).

**Implementação.** Resíduo diário rA − β·rB (β de 1 ano em retornos de 5 dias, limitado a [0,3; 2]), z-score do resíduo acumulado em
63/126 dias; decisão na sexta; entra com |z| > 1,5/2,0, sai em z = 0 ou 126 dias; **quebra estrutural**: |z| > 3,5 → sai e bloqueia o
par por 63 dias; filtro de cointegração opcional (t de Dickey-Fuller do resíduo em 252 dias < −2) e correlação > 0,3. Limpeza no PAR
(dia com |r| > 25% em qualquer perna zera as duas). Risco igual por par. Custos por mercado (EUA 3 bps, Europa/Japão/Austrália 5, Ásia
8) + impostos (UK 0,5% na compra, França 0,3%, Espanha 0,2%, Itália 0,1%, Taiwan 0,3% na venda, Coreia 0,2% na venda, HK 0,1% cada
lado, Índia 0,1% cada lado), aluguel 0,3% EUA a 3% Índia; venda descoberta proibida na Coreia (out/08–mai/09, ago–nov/11,
mar/20–mai/21, nov/23–mar/25) bloqueia entrada.

**Números.** escolhido no IS `{'jan': 63, 'z_in': 2.0, 'filtro': 'coint'}` | IR IS 0,39 | OOS 5,9% vs CDI 11,4% | IR OOS -0,60 | vol OOS 7,9% | pior queda OOS -12,9% | P(bater) 6% | PBO 37% | Sharpe deflac. 2% | custo x2 -9,2 pp | +1 dia -5,4 pp | período todo 10,1% vs 9,9% (IR 0,06, pior queda -12,9%)

**Excesso sobre o CDI por ano (pp):** 2009: +5.1, 2010: +8.0, 2011: -4.6, 2012: -2.4, 2013: +2.1, 2014: +4.5, 2015: -6.7, 2016: +12.5, 2017: -0.0, 2018: +8.3, 2019: -2.1, 2020: +11.7, 2021: -7.5, 2022: +1.4, 2023: -6.0, 2024: -5.8, 2025: -5.6, 2026: -7.8

**Variantes (IR IS → excesso OOS pp/ano):** {jan: 63, z_in: 1.5, filtro: coint} +0.12 → -6.2; {jan: 63, z_in: 1.5, filtro: nenhum} -0.06 → -9.4; {jan: 63, z_in: 2.0, filtro: coint} +0.39 → -4.6; {jan: 63, z_in: 2.0, filtro: nenhum} +0.08 → -4.1; {jan: 126, z_in: 1.5, filtro: coint} +0.06 → -7.5; {jan: 126, z_in: 1.5, filtro: nenhum} -0.02 → -6.9; {jan: 126, z_in: 2.0, filtro: coint} +0.30 → -4.0; {jan: 126, z_in: 2.0, filtro: nenhum} +0.25 → -4.7

Negócios: 974 | acerto 64%

10 melhores:

| ativo             | lado     | entrada    | saida      |   dias |   contrib %PL |   sinal | mercado   |
|:------------------|:---------|:-----------|:-----------|-------:|--------------:|--------:|:----------|
| Takeda x Astellas | vendido  | 2021-09-21 | 2021-10-11 |     13 |          2.66 |   3.007 | JP        |
| NEM x AEM         | vendido  | 2024-10-07 | 2024-10-28 |     15 |          2.65 |   2.466 | US        |
| HSBA x STAN       | comprado | 2012-07-23 | 2012-08-13 |     15 |          1.92 |  -2.288 | UK        |
| INFY x TCS        | vendido  | 2017-07-17 | 2017-08-21 |     24 |          1.87 |   2.435 | IN        |
| T x VZ            | comprado | 2014-03-03 | 2014-03-24 |     15 |          1.79 |  -2.893 | US        |
| DTE x ORA         | vendido  | 2020-02-17 | 2020-03-16 |     20 |          1.75 |   2.347 | EU        |
| CBA x WBC         | comprado | 2014-10-12 | 2014-11-09 |     20 |          1.73 |  -2.564 | AU        |
| Toyota x Honda    | comprado | 2020-12-07 | 2020-12-14 |      5 |          1.7  |  -2.462 | JP        |
| NAB x ANZ         | vendido  | 2018-03-11 | 2018-05-14 |     42 |          1.65 |   2.364 | AU        |
| INFY x TCS        | vendido  | 2019-07-22 | 2019-10-22 |     59 |          1.61 |   3.264 | IN        |

10 piores:

| ativo           | lado     | entrada    | saida      |   dias |   contrib %PL |   sinal | mercado   |
|:----------------|:---------|:-----------|:-----------|-------:|--------------:|--------:|:----------|
| JPM x BAC       | vendido  | 2022-10-31 | 2023-05-03 |    126 |         -5.55 |   2.668 | US        |
| LMT x NOC       | vendido  | 2024-04-08 | 2024-10-07 |    126 |         -4.26 |   2.541 | US        |
| BNP x GLE       | vendido  | 2019-01-21 | 2019-07-19 |    126 |         -4.25 |   2.364 | FR        |
| MCD x YUM       | vendido  | 2015-08-03 | 2016-02-02 |    126 |         -4.14 |   2.837 | US        |
| MC x KER        | vendido  | 2020-10-26 | 2021-04-26 |    126 |         -4    |   2.143 | FR        |
| TEF x ORA       | comprado | 2025-08-04 | 2025-11-10 |     70 |         -3.93 |  -2.59  | EU        |
| Samsung x Hynix | vendido  | 2025-08-04 | 2026-02-10 |    126 |         -3.75 |   2.13  | KR        |
| ISP x UCG       | vendido  | 2011-09-19 | 2012-03-14 |    126 |         -3.73 |   2.529 | IT        |
| EOAN x RWE      | vendido  | 2014-11-24 | 2015-06-01 |    126 |         -3.71 |   2.647 | DE        |
| MC x KER        | vendido  | 2019-03-18 | 2019-09-13 |    126 |         -3.55 |   2.009 | FR        |


**O que deu certo.** Reversões rápidas de ruído sem notícia: Takeda×Astellas set/2021 (+2,7% do PL em 13 dias), NEM×AEM out/2024 (+2,7%),
HSBC×StanChart jul/2012 (+1,9%), T×VZ mar/2014. Por par no IS: DT×Orange (+6,0), CBA×Westpac (+5,7), GS×MS, Hyundai×Kia, MUFG×SMFG, V×MA
(+4,5 a +4,8% do PL cada) — pares de negócio quase idêntico e mesmo regulador.

**O que deu errado.** Os piores são todos o stop de 126 dias em divergências que eram mudança de fundamento: JPM×BAC vendido out/2022
(o BAC carregava a carteira de Treasuries que afundou em 2023: −5,6%), LMT×NOC 2024 (B-21/Sentinel na NOC: −4,3%), BNP×SocGen 2019, MCD×YUM
2015 (refranquia do MCD), LVMH×Kering 2019 e 2020 (Gucci perdendo força: −3,6% e −4,0%), Samsung×Hynix 2025–26 (HBM/IA na Hynix: −3,8%),
E.ON×RWE 2014–15 (cisões). O filtro de "quebra estrutural" por z > 3,5 é lento: a divergência fundamental anda devagar e fica entre 2 e 3,5.
Custo: com custo x2 o OOS piora 9 pp/ano — a estratégia gira muito para o tamanho do sinal; 64% de acerto não paga as perdas grandes.

**Próximo passo.** Filtro de notícia (resultado trimestral/guidance dentro da janela = não entrar), limitar a pares do mesmo regulador
e mesma moeda de receita (bancos domésticos, teles, ferrovias) e stop por tempo menor (42 dias).

---

## IM2 — Reversão de curto prazo em large caps (EUA, Japão, Europa)

**Tese de mesa.** Fornecer liquidez: quem precisa vender rápido paga. No Brasil o "ML semanal" falhou; aqui a versão de mesa — quintil
que mais caiu contra o mercado (neutro por país na Europa) comprado, o que mais subiu vendido, dinheiro neutro. Variante com VIX acima
da mediana de 1 ano (liquidez escassa = prêmio maior, Nagel 2012).

**Implementação.** 100 large caps EUA, 60 Japão, 60 Europa; L = 5 (semanal) ou 21 dias (mensal), rebalanceio na mesma frequência;
execução no fechamento SEGUINTE à decisão (perde o 1º dia, onde está boa parte da reversão semanal); vol-alvo 8%; custos 3/5/5 bps +
FTT (França 0,3%, Itália 0,1%, Espanha 0,2% na compra), aluguel 0,3–0,6%.

**Estudo de IC (rank da reversão vs retorno seguinte, pulando o 1º dia):** semanal EUA −0,018 IS / −0,008 OOS, Japão −0,017 / −0,021,
Europa −0,008 / +0,001; mensal EUA −0,031 / −0,051, **Japão −0,040 / −0,011**, Europa 0,000 / −0,010. A reversão existe mas é do tamanho
do custo; no 1º dia depois do sinal ela é maior (que não é capturável sem execução intradiária).

**Números.** escolhido no IS `{'L': 21, 'vix': 1, 'regiao': 'jp'}` | IR IS 0,02 | OOS 17,3% vs CDI 11,4% | IR OOS 0,57 | vol OOS 9,9% | pior queda OOS -9,9% | P(bater) 91% | PBO 16% | Sharpe deflac. 56% | custo x2 5,0 pp | +1 dia 6,5 pp | período todo 11,3% vs 9,9% (IR 0,17, pior queda -17,9%)

**Excesso sobre o CDI por ano (pp):** 2009: -3.6, 2010: -7.8, 2011: -12.7, 2012: +13.0, 2013: +23.1, 2014: -9.9, 2015: +2.1, 2016: -21.2, 2017: -1.3, 2018: +0.2, 2019: +26.8, 2020: -8.5, 2021: +15.2, 2022: +10.9, 2023: -0.2, 2024: -14.0, 2025: +24.3, 2026: +1.1

**Variantes (IR IS → excesso OOS pp/ano):** {L: 5, vix: 0, regiao: jp} -0.36 → -4.8; {L: 5, vix: 0, regiao: todas} -0.99 → -16.5; {L: 5, vix: 1, regiao: jp} -0.42 → -4.7; {L: 5, vix: 1, regiao: todas} -0.82 → -15.1; {L: 21, vix: 0, regiao: jp} -0.02 → -0.3; {L: 21, vix: 0, regiao: todas} -0.39 → -1.1; {L: 21, vix: 1, regiao: jp} +0.02 → +5.7; {L: 21, vix: 1, regiao: todas} -0.47 → +5.8

Negócios: 1900 | acerto 52%

10 melhores:

| ativo   | lado     | entrada    | saida      |   dias |   retorno % |   contrib %PL | mercado   |
|:--------|:---------|:-----------|:-----------|-------:|------------:|--------------:|:----------|
| 9984.T  | vendido  | 2025-11-04 | 2025-12-01 |     18 |        43.8 |          6.77 | jp        |
| 6752.T  | comprado | 2012-06-01 | 2012-07-02 |     21 |        23.8 |          3.81 | jp        |
| 8316.T  | comprado | 2013-06-03 | 2013-07-01 |     20 |        21.9 |          3.59 | jp        |
| 9503.T  | comprado | 2012-11-01 | 2012-12-03 |     21 |        20   |          3.46 | jp        |
| 5401.T  | comprado | 2016-11-01 | 2016-12-01 |     20 |        20.8 |          3.46 | jp        |
| 8725.T  | comprado | 2012-06-01 | 2012-07-02 |     21 |        19.7 |          3.22 | jp        |
| 6954.T  | vendido  | 2011-08-01 | 2011-09-01 |     23 |        17.9 |          2.99 | jp        |
| 8604.T  | comprado | 2012-06-01 | 2012-07-02 |     21 |        17.5 |          2.96 | jp        |
| 9984.T  | comprado | 2024-05-01 | 2024-06-03 |     21 |        16.8 |          2.79 | jp        |
| 8604.T  | comprado | 2019-06-03 | 2019-07-01 |     20 |        16.4 |          2.78 | jp        |

10 piores:

| ativo   | lado     | entrada    | saida      |   dias |   retorno % |   contrib %PL | mercado   |
|:--------|:---------|:-----------|:-----------|-------:|------------:|--------------:|:----------|
| 5411.T  | comprado | 2020-02-03 | 2020-05-01 |     60 |       -46.6 |         -6.81 | jp        |
| 5401.T  | comprado | 2020-02-03 | 2020-05-01 |     60 |       -43.1 |         -5.75 | jp        |
| 7011.T  | comprado | 2020-02-03 | 2020-05-01 |     60 |       -31.7 |         -4.29 | jp        |
| 9984.T  | vendido  | 2013-06-03 | 2013-08-01 |     42 |       -29.6 |         -4.08 | jp        |
| 4901.T  | comprado | 2011-08-01 | 2011-10-03 |     43 |       -23.7 |         -4.05 | jp        |
| 8604.T  | vendido  | 2016-11-01 | 2016-12-01 |     20 |       -21.3 |         -3.95 | jp        |
| 8604.T  | comprado | 2011-08-01 | 2011-11-01 |     63 |       -21.5 |         -3.78 | jp        |
| 7011.T  | vendido  | 2022-02-01 | 2022-07-01 |    101 |       -41.7 |         -3.54 | jp        |
| 6758.T  | comprado | 2011-08-01 | 2011-11-01 |     63 |       -18.9 |         -3.45 | jp        |
| 7270.T  | vendido  | 2012-11-01 | 2012-12-03 |     21 |       -18.1 |         -3.37 | jp        |


Sem a SoftBank (9984.T vendida em nov/2025 depois de +44% em um mês, devolveu tudo: +6,8% do PL) o OOS cai de +6,0 para +3,8 pp/ano em USD.
Semanal perde em tudo (−4,7 a −16,5 pp/ano OOS): a Europa semanal perde até sem custo (−9,7 pp/ano em 2021+): as large caps europeias
tiveram continuação (momentum) de curto prazo depois de 2020.

**O que deu certo.** Comprar as japonesas que caíram muito no mês com VIX alto: Panasonic/MS&AD/Nomura jun/2012 (+17 a +24% em um mês),
SMFG jun/2013 (+22%), Nippon Steel nov/2016, e vender a SoftBank depois das altas (2025). **O que deu errado.** Comprar siderúrgicas e
industriais em fev/2020 (JFE −47%, Nippon Steel −43%, MHI −32% até mai/2020): reversão em crise vira faca caindo; e vender SoftBank em
jun/2013 (subiu mais 30%).

**Próximo passo.** Neutralizar por setor (precisa mapa de setores; TOPIX-17 é público), excluir semanas de resultado, e testar a
execução na abertura seguinte (requer Open confiável — o Yahoo japonês pré-2010 não é).

---

## IM3 — Ações sensíveis a crédito quando o high yield abre (EUA)

**Tese de mesa.** "Short de empresas alavancadas quando o crédito piora". Sem balanço gratuito com histórico (o XBRL da SEC existe, mas
mapear CIK→ticker com preço de deslistada tem o mesmo viés do G2), meço a alavancagem pelo preço: beta da ação ao fator crédito
(HYG−β·IEF), ortogonal ao S&P, em 1 ano. Gatilho: fator crédito caiu 1,5%/3% do topo de 21 dias e está abaixo da média de 63.
Vendo as 15 mais sensíveis e compro as 15 menos, hedge de beta TOTAL com SPY; carteira congelada no episódio; sai quando o crédito
volta a subir (após 21 dias) ou em 63 dias. Variante "compra" = lado oposto (fornecer liquidez no pânico).

**Números.** escolhido no IS `{'thr': 0.015, 'saida': '63d', 'lado': 'vende'}` | IR IS 0,33 | OOS 4,7% vs CDI 11,4% | IR OOS -0,78 | vol OOS 7,6% | pior queda OOS -21,3% | P(bater) 4% | PBO 64% | Sharpe deflac. 0% | custo x2 -6,9 pp | +1 dia -5,9 pp | período todo 9,7% vs 9,9% (IR 0,02, pior queda -30,3%)

**Excesso sobre o CDI por ano (pp):** 2009: +0.2, 2010: -4.6, 2011: -9.0, 2012: +5.4, 2013: +21.5, 2014: -2.5, 2015: +23.4, 2016: -8.5, 2017: -2.1, 2018: +6.7, 2019: +2.8, 2020: +6.2, 2021: -5.1, 2022: -20.5, 2023: -10.4, 2024: -5.4, 2025: -3.3, 2026: +8.0

**Variantes (IR IS → excesso OOS pp/ano):** {thr: 0.015, saida: aperta, lado: vende} +0.28 → -2.6; {thr: 0.015, saida: aperta, lado: compra} -0.39 → +2.0; {thr: 0.015, saida: 63d, lado: vende} +0.33 → -5.8; {thr: 0.015, saida: 63d, lado: compra} -0.41 → +5.3; {thr: 0.03, saida: aperta, lado: vende} +0.05 → -0.1; {thr: 0.03, saida: aperta, lado: compra} -0.13 → -0.2; {thr: 0.03, saida: 63d, lado: vende} +0.23 → -0.3; {thr: 0.03, saida: 63d, lado: compra} -0.30 → +0.0

Negócios: 992 | acerto 50%

10 melhores:

| ativo   | lado     | entrada    | saida      |   dias |   retorno % |   contrib %PL |   sinal | mercado   |
|:--------|:---------|:-----------|:-----------|-------:|------------:|--------------:|--------:|:----------|
| SPY     | comprado | 2022-12-29 | 2023-07-03 |    126 |        16.6 |          7.55 | nan     | US        |
| NVDA    | comprado | 2010-11-24 | 2011-02-25 |     63 |        67.9 |          5.51 |  -0.394 | US        |
| SPY     | comprado | 2010-02-01 | 2010-05-03 |     63 |        10.8 |          5.24 | nan     | US        |
| SPY     | comprado | 2016-11-01 | 2017-02-02 |     63 |         8.6 |          4.09 | nan     | US        |
| INTC    | comprado | 2026-03-16 | 2026-06-15 |     63 |       179.4 |          4.07 |  -0.903 | US        |
| FCX     | vendido  | 2015-06-18 | 2015-09-17 |     63 |        87.7 |          4.02 |   2.2   | US        |
| BA      | vendido  | 2020-02-26 | 2020-05-27 |     63 |        23.1 |          4    |   0.754 | US        |
| NVDA    | vendido  | 2018-10-11 | 2019-01-14 |     63 |        34.9 |          3.59 |   0.652 | US        |
| MS      | comprado | 2012-11-08 | 2013-02-11 |     63 |        41.2 |          3.4  |  -0.556 | US        |
| SLB     | vendido  | 2018-10-11 | 2019-01-14 |     63 |        37.8 |          3.24 |   0.829 | US        |

10 piores:

| ativo   | lado     | entrada    | saida      |   dias |   retorno % |   contrib %PL |   sinal | mercado   |
|:--------|:---------|:-----------|:-----------|-------:|------------:|--------------:|--------:|:----------|
| NVDA    | vendido  | 2022-12-29 | 2023-07-03 |    126 |       -71.1 |         -5.26 |   0.536 | US        |
| BAC     | comprado | 2011-03-17 | 2011-09-15 |    126 |       -47.5 |         -3.92 |  -0.34  | US        |
| SPY     | vendido  | 2012-11-08 | 2013-02-11 |     63 |       -10   |         -3.7  | nan     | US        |
| EOG     | vendido  | 2020-02-26 | 2020-05-27 |     63 |       -35.7 |         -2.84 |   1.133 | US        |
| GE      | vendido  | 2010-11-24 | 2011-02-25 |     63 |       -25.7 |         -2.81 |   0.2   | US        |
| SPY     | vendido  | 2017-11-10 | 2018-05-15 |    126 |        -6.9 |         -2.76 | nan     | US        |
| GE      | comprado | 2020-02-26 | 2020-05-27 |     63 |       -33.4 |         -2.52 |  -0.768 | US        |
| GE      | vendido  | 2022-12-29 | 2023-07-03 |    126 |       -41.6 |         -2.39 |   0.407 | US        |
| FCX     | vendido  | 2016-11-01 | 2017-02-02 |     63 |       -38.1 |         -2.34 |   2.883 | US        |
| MA      | vendido  | 2013-05-30 | 2013-11-26 |    126 |       -25.4 |         -2.29 |   0.332 | US        |


**O que deu certo (IS).** Vender petroleiras/mineradoras alavancadas na queda do petróleo 2015 (FCX jun/2015: −47% em 3 meses; 2015 inteiro
+23 pp), BA/EOG em fev/2020, NVDA/SLB em out/2018. **O que deu errado (OOS).** 2022–23: o gatilho disparou em dez/2022 e o livro vendeu
NVDA (beta alto ao crédito) logo antes do ciclo de IA (−71%: −5,3% do PL); 2022 inteiro −20 pp. O lado "compra" ganhou no OOS (+5,3 pp/ano
na variante 63 dias), mas perdeu no IS — é o mesmo sinal que mudou de sinal com o regime (Fed comprando crédito desde 2020).

**Próximo passo.** Alavancagem de verdade via XBRL (dívida/EBITDA dos 10-K) só para o universo S&P 500 histórico (lista de entradas e
saídas da Wikipedia) e preços de deslistadas — sem isso, o teste do lado vendido é viesado contra.

---

## IM4 — Rotação de países: valor + momento + carry (L/S)

**Tese de mesa.** Rodada 1 ganhou do CDI e não do ACWI. Aqui é L/S: país com moeda real barata (REER do BIS contra a média de 10 anos;
CAPE/PL de país não é gratuito) e que caiu muito de 5 a 1 ano atrás (reversão de longo prazo) tem prêmio de risco alto; momento 12-1
diz que o estrangeiro voltou; carry (juro de política − Fed) paga a espera.

**Implementação.** 34 ETFs (os 33 da lista + SPY, porque sem os EUA no universo qualquer "comprado em países, vendido em ACWI" perde a
década americana — foi o primeiro resultado: todas as variantes negativas no IS). Top 6 por média de ranks, peso inverso à vol
relativa (teto 1,5x), mensal; vendido no ACWI ou nos 6 piores. REER defasado 2 meses. Custos por ETF de 1 bp (SPY) a 50 bps
(Catar/Emirados), aluguel 0,3%.

**Números.** escolhido no IS `{'sinal': 'valor+mom+carry', 'hedge': 'piores'}` | IR IS -0,08 | OOS 12,0% vs CDI 11,4% | IR OOS 0,10 | vol OOS 11,7% | pior queda OOS -14,7% | P(bater) 52% | PBO 52% | Sharpe deflac. 24% | custo x2 -1,0 pp | +1 dia 0,4 pp | período todo 8,9% vs 9,9% (IR -0,03, pior queda -27,8%)

**Excesso sobre o CDI por ano (pp):** 2010: +11.9, 2011: -4.9, 2012: +8.2, 2013: +14.7, 2014: -2.6, 2015: -13.7, 2016: +3.8, 2017: -2.8, 2018: -14.2, 2019: -7.5, 2020: -8.2, 2021: -9.5, 2022: +47.3, 2023: -10.1, 2024: -11.1, 2025: +9.3, 2026: -11.4

**Variantes (IR IS → excesso OOS pp/ano):** {sinal: valor, hedge: acwi} -0.38 → -0.6; {sinal: valor, hedge: piores} -0.09 → +1.8; {sinal: valor+mom, hedge: acwi} -0.81 → +1.8; {sinal: valor+mom, hedge: piores} -0.29 → +4.1; {sinal: valor+mom+carry, hedge: acwi} -0.53 → +0.7; {sinal: valor+mom+carry, hedge: piores} -0.08 → +1.3; {sinal: mom, hedge: acwi} -0.73 → -0.5; {sinal: mom, hedge: piores} -0.24 → +1.1

Negócios: 401 | acerto 45%

10 melhores:

| ativo   | lado     | entrada    | saida      |   dias |   retorno % |   contrib %PL |   sinal |
|:--------|:---------|:-----------|:-----------|-------:|------------:|--------------:|--------:|
| TUR     | comprado | 2019-05-01 | 2024-03-01 |   1217 |        88   |         10.85 |   0.741 |
| ARGT    | comprado | 2016-03-01 | 2017-06-01 |    316 |        66.5 |         10.64 |   0.648 |
| EWY     | comprado | 2025-10-01 | 2026-10-14 |    261 |        99.6 |         10.4  |   0.687 |
| EWW     | comprado | 2017-07-03 | 2023-02-01 |   1405 |        25   |         10.15 |   0.705 |
| ECH     | comprado | 2025-02-03 | 2026-05-01 |    312 |        56.3 |          9.06 |   0.678 |
| EZA     | comprado | 2024-06-03 | 2025-10-01 |    333 |        67.9 |          8.07 |   0.756 |
| EWY     | comprado | 2020-08-03 | 2021-04-01 |    167 |        49.9 |          7.47 |   0.637 |
| UAE     | comprado | 2021-07-01 | 2022-04-01 |    190 |        36.4 |          7.35 |   0.704 |
| EWT     | comprado | 2026-04-01 | 2026-10-14 |    136 |        54.7 |          6.96 |   0.683 |
| EWN     | comprado | 2012-08-01 | 2013-11-01 |    315 |        44.6 |          6.9  |   0.651 |

10 piores:

| ativo   | lado     | entrada    | saida      |   dias |   retorno % |   contrib %PL |   sinal |
|:--------|:---------|:-----------|:-----------|-------:|------------:|--------------:|--------:|
| EWC     | comprado | 2020-01-02 | 2020-07-01 |    125 |       -12.7 |         -6.92 |   0.786 |
| EPOL    | comprado | 2011-06-01 | 2011-10-03 |     86 |       -38.6 |         -6.61 |   0.66  |
| SPY     | vendido  | 2025-05-01 | 2026-07-01 |    292 |       -27.6 |         -6.55 |   0.365 |
| GREK    | comprado | 2019-10-01 | 2020-04-01 |    126 |       -42.1 |         -6.52 |   0.721 |
| EWM     | vendido  | 2010-03-01 | 2011-03-01 |    253 |       -26.9 |         -6.44 |   0.343 |
| EWZ     | comprado | 2018-03-01 | 2020-04-01 |    525 |       -47.3 |         -6.12 |   0.747 |
| EWN     | vendido  | 2024-11-01 | 2026-03-02 |    330 |       -31.8 |         -6.08 |   0.381 |
| EWL     | vendido  | 2010-07-01 | 2011-06-01 |    231 |       -29.7 |         -5.98 |   0.422 |
| EWL     | vendido  | 2022-07-01 | 2025-03-03 |    668 |       -28.3 |         -5.89 |   0.302 |
| EIDO    | comprado | 2026-04-01 | 2026-07-01 |     62 |       -27.2 |         -5.75 |   0.705 |


**O que deu certo.** Comprar quem estava barato E voltando: Turquia mai/2019–mar/2024 (+88%), Argentina mar/2016–jun/2017 (+67%),
Coreia out/2025–out/2026 (+100%), Chile 2025–26 (+56%), África do Sul 2024–25 (+68%), México 2017–23. **O que deu errado.** 2022 explica
quase tudo: +47 pp (comprado em LatAm/Golfo/commodity, vendido em Taiwan/EUA na queda das big techs); fora 2022 é negativo. Vender Suíça
e Holanda (EWL/EWN) e os EUA (SPY vendido mai/2025–jul/2026: −28%) custou caro: "caro" pelo REER continuou caro.

**Próximo passo.** Valor de país precisa de P/L ou CAPE (MSCI/Barclays são pagos); dá para montar P/L agregado dos ETFs pelos holdings
(iShares publica) — trabalho grande. Como está, não há alfa.

---

## IM5 — Moedas EM/G10 por valor (PPP) e juro real, com stop

**Tese de mesa.** O análogo do "real tático" (que funcionou pelo diferencial de juro real), aplicado a MXN, ZAR, INR, IDR, KRW, TRY, CLP,
COP, PLN, HUF, CZK, JPY e AUD: moeda barata pela PPP (câmbio real bilateral contra os EUA vs média de 10 anos, em z de 10 anos) e com
juro real alto (política BIS − CPI 12m do BIS, contra o mesmo dos EUA) aprecia; o stop (3%/5% por moeda, bloqueia até o fim do mês
seguinte) evita o erro clássico do valor em moeda (lira, iene).

**Implementação.** Ranks cross-section de cada sinal centrados em zero, neutro ao dólar, peso inverso à vol, vol-alvo 8%, teto 25% por
moeda, mensal; retorno = spot + diferencial de política (70% nas NDF: INR, IDR, KRW, CLP, COP); CPI com 1 mês de defasagem. Custos 2 bps
(JPY/AUD) a 25 bps (TRY).

**Números.** escolhido no IS `{'sinal': 'ppp+juro_real', 'stop': 0.03}` | IR IS 0,74 | OOS 8,1% vs CDI 11,4% | IR OOS -0,53 | vol OOS 5,4% | pior queda OOS -5,7% | P(bater) 7% | PBO 31% | Sharpe deflac. 2% | custo x2 -4,1 pp | +1 dia -2,8 pp | período todo 12,1% vs 9,9% (IR 0,35, pior queda -7,9%)

**Excesso sobre o CDI por ano (pp):** 2009: -0.4, 2010: +5.5, 2011: -2.5, 2012: +9.7, 2013: +22.5, 2014: +0.9, 2015: +1.8, 2016: +1.4, 2017: -6.2, 2018: +12.4, 2019: +10.1, 2020: +3.5, 2021: -5.9, 2022: -2.1, 2023: -4.6, 2024: -3.5, 2025: -6.5, 2026: +4.3

**Variantes (IR IS → excesso OOS pp/ano):** {sinal: ppp, stop: 0} +0.41 → -8.5; {sinal: ppp, stop: 0.03} +0.47 → -7.7; {sinal: ppp, stop: 0.05} +0.32 → -7.1; {sinal: juro_real, stop: 0} +0.30 → +2.9; {sinal: juro_real, stop: 0.03} +0.23 → +4.6; {sinal: juro_real, stop: 0.05} +0.18 → +3.5; {sinal: ppp+juro_real, stop: 0} +0.69 → -3.5; {sinal: ppp+juro_real, stop: 0.03} +0.74 → -2.7; {sinal: ppp+juro_real, stop: 0.05} +0.53 → -3.7

Negócios: 478 | acerto 38%

10 melhores:

| ativo    | lado     | entrada    | saida      |   dias |   retorno % |   contrib %PL |   sinal |
|:---------|:---------|:-----------|:-----------|-------:|------------:|--------------:|--------:|
| TRY=X    | comprado | 2024-10-01 | 2026-10-14 |    511 |        48.3 |          9.88 |   0.346 |
| MXN=X    | comprado | 2017-03-01 | 2021-09-01 |   1135 |        26.6 |          5.85 |   0.385 |
| ZAR=X    | comprado | 2010-07-01 | 2011-06-01 |    231 |        19.5 |          5.16 |   0.212 |
| AUDUSD=X | comprado | 2010-07-01 | 2012-12-03 |    610 |        37   |          5.1  |   0.173 |
| TRY=X    | vendido  | 2013-02-01 | 2014-02-03 |    252 |        22.6 |          4.43 |  -0.115 |
| JPY=X    | vendido  | 2011-09-01 | 2013-02-01 |    355 |        18.3 |          4.22 |  -0.266 |
| ZAR=X    | comprado | 2016-02-01 | 2016-12-01 |    212 |        20.5 |          4.21 |   0.385 |
| AUDUSD=X | vendido  | 2012-12-03 | 2018-03-01 |   1319 |        16.7 |          4.21 |  -0.077 |
| IDR=X    | vendido  | 2013-03-01 | 2014-01-02 |    212 |        16.9 |          4.02 |   0.038 |
| MXN=X    | vendido  | 2014-06-02 | 2015-08-03 |    295 |        20.5 |          3.95 |  -0.192 |

10 piores:

| ativo   | lado     | entrada    | saida      |   dias |   retorno % |   contrib %PL |   sinal |
|:--------|:---------|:-----------|:-----------|-------:|------------:|--------------:|--------:|
| TRY=X   | vendido  | 2022-03-01 | 2024-10-01 |    650 |        40.5 |         -3.27 |   0.038 |
| PLN=X   | vendido  | 2018-03-01 | 2025-07-01 |   1843 |        -7.3 |         -3.01 |  -0.077 |
| TRY=X   | comprado | 2020-11-02 | 2021-11-19 |    265 |        -9.1 |         -2.7  |   0.231 |
| MXN=X   | comprado | 2011-01-03 | 2011-09-20 |    180 |        -7.8 |         -2.35 |   0.067 |
| COP=X   | comprado | 2019-10-01 | 2020-03-10 |    110 |        -9.3 |         -2.21 |   0.231 |
| CZK=X   | vendido  | 2010-01-04 | 2010-09-30 |    187 |        -2.7 |         -1.93 |  -0.096 |
| HUF=X   | comprado | 2013-04-01 | 2015-01-05 |    445 |        -6.5 |         -1.76 |   0.192 |
| MXN=X   | comprado | 2016-11-01 | 2016-11-10 |      7 |        -6.4 |         -1.56 |   0.423 |
| INR=X   | comprado | 2013-07-01 | 2013-08-20 |     35 |        -5.6 |         -1.44 |   0.308 |
| CLP=X   | comprado | 2012-06-01 | 2014-03-13 |    446 |        -4   |         -1.42 |   0.115 |


**O que deu certo (IS).** PPP+juro real escolhia bem em 2012–13 e 2018–19: vendido em lira 2013–14 (+22,6%), vendido em iene 2011–13
(+18%), comprado em rand 2010–11 e 2016, comprado em AUD 2010–12; comprado em MXN 2017–21 (+27%). **O que deu errado (OOS).** O iene: o
PPP mandou comprar o iene "mais barato em 40 anos" em 2021–24 e ele caiu mais 30% (−6,1% do PL no OOS mesmo com stop); HUF e PLN também.
O PPP sozinho faz −8 pp/ano no OOS. O **juro real sozinho** é a única variante positiva no OOS (+2,9 a +4,6 pp/ano) — consistente com o
JF6 (real tático) e com o achado do JF7 (excluir moeda com juro real negativo) —, mas o IS escolheu a combinação.

**Próximo passo.** Juro real puro (sem PPP) com stop de 3% como fundo próprio na próxima amostra; usar breakeven/expectativa (Focus-like)
em vez de CPI realizado onde houver.

---

## IM6 — CTA global com risco de mesa

**Tese de mesa.** Rodada 1: o CTA bateu o CDI até 2021 e perdeu depois. Melhorias: sinal contínuo (retorno de L dias / vol·√L, limitado
a ±2, média de 3 janelas), vol-alvo 10% por ativo com teto de 50% do PL por ativo (evita SHY/IEF alavancados), vol-alvo 10% no livro,
stop de crise (drawdown de 8% em 63 dias corta pela metade até recuperar metade) e camada de crise (vende ações quando o crédito abre).

**Implementação.** 28 ETFs (ações EUA e países, Treasuries, TIPS, crédito, ouro/prata/petróleo/gás/agro/metais) + 9 moedas com carry,
semanal, custos 2–8 bps, alavancagem acima de 1x paga T-bill + 0,5%.

**Números.** escolhido no IS `{'modo': 'cta', 'janelas': 'lento'}` | IR IS 0,28 | OOS 9,2% vs CDI 11,4% | IR OOS -0,13 | vol OOS 11,0% | pior queda OOS -11,6% | P(bater) 29% | PBO 8% | Sharpe deflac. 27% | custo x2 -3,2 pp | +1 dia -2,8 pp | período todo 11,1% vs 9,9% (IR 0,15, pior queda -22,8%)

**Excesso sobre o CDI por ano (pp):** 2009: +4.5, 2010: +16.2, 2011: -5.7, 2012: -0.8, 2013: +7.5, 2014: +1.5, 2015: +5.9, 2016: +4.6, 2017: +16.7, 2018: -11.1, 2019: -6.8, 2020: +5.6, 2021: +4.4, 2022: +4.3, 2023: -13.8, 2024: -6.6, 2025: -2.2, 2026: +1.5

**Variantes (IR IS → excesso OOS pp/ano):** {modo: cta, janelas: rapido} +0.14 → -5.7; {modo: cta, janelas: lento} +0.28 → -1.3; {modo: cta+stop, janelas: rapido} +0.12 → -5.3; {modo: cta+stop, janelas: lento} +0.27 → -2.2; {modo: cta+crise, janelas: rapido} +0.04 → -5.5; {modo: cta+crise, janelas: lento} +0.15 → -1.2; {modo: cta+crise+stop, janelas: rapido} +0.12 → -6.1; {modo: cta+crise+stop, janelas: lento} +0.25 → -3.0

Negócios: 2651 | acerto 23%

10 melhores:

| ativo   | lado     | entrada    | saida      |   dias |   retorno % |   contrib %PL |
|:--------|:---------|:-----------|:-----------|-------:|------------:|--------------:|
| USO     | vendido  | 2014-08-04 | 2016-07-05 |    483 |       134.1 |          5.53 |
| GLD     | comprado | 2023-10-16 | 2026-06-08 |    662 |        98.8 |          4.89 |
| SLV     | comprado | 2010-06-14 | 2011-09-26 |    325 |        66.5 |          4.1  |
| GLD     | comprado | 2009-04-20 | 2011-12-19 |    674 |        77.7 |          3.96 |
| QQQ     | comprado | 2012-11-26 | 2015-08-24 |    690 |        56.6 |          3.13 |
| UNG     | vendido  | 2011-06-13 | 2012-07-23 |    280 |        80.5 |          3.09 |
| SPY     | comprado | 2012-06-11 | 2015-08-24 |    805 |        53.9 |          2.93 |
| QQQ     | comprado | 2016-07-11 | 2018-11-19 |    596 |        45   |          2.9  |
| SLV     | comprado | 2024-03-11 | 2026-06-29 |    576 |       199.3 |          2.85 |
| GLD     | comprado | 2019-06-03 | 2021-02-08 |    425 |        35.2 |          2.8  |

10 piores:

| ativo   | lado     | entrada    | saida      |   dias |   retorno % |   contrib %PL |
|:--------|:---------|:-----------|:-----------|-------:|------------:|--------------:|
| EWT     | comprado | 2019-03-25 | 2019-05-20 |     39 |        -3.6 |         -1.55 |
| CPER    | comprado | 2025-01-13 | 2025-08-18 |    149 |         0.3 |         -1.54 |
| INDA    | comprado | 2019-03-11 | 2019-07-29 |     97 |        -2.1 |         -1.12 |
| EWU     | comprado | 2022-11-28 | 2023-08-21 |    182 |         2.5 |         -0.94 |
| EWU     | comprado | 2019-02-19 | 2019-05-28 |     68 |        -1.6 |         -0.94 |
| FXI     | comprado | 2019-02-19 | 2019-05-13 |     58 |        -6.6 |         -0.91 |
| MXN=X   | vendido  | 2018-05-07 | 2018-08-13 |     68 |        -3.5 |         -0.86 |
| ZAR=X   | vendido  | 2023-01-23 | 2023-11-06 |    199 |         2.8 |         -0.84 |
| USO     | vendido  | 2023-01-30 | 2023-04-10 |     48 |        -3.7 |         -0.83 |
| EFA     | comprado | 2019-03-18 | 2019-06-03 |     53 |        -3   |         -0.82 |


**O que deu certo.** As tendências longas de commodities: vendido em petróleo ago/2014–jul/2016 (+134% na perna, +5,5% do PL), ouro
comprado 2009–11 e out/2023–jun/2026 (+99%), prata 2010–11 e 2024–26 (+199%), gás vendido 2011–12, Nasdaq 2012–15. **O que deu errado.**
2018, 2019, 2023 e 2024: reversões rápidas em ações e juros (os piores negócios são pequenos e muitos — acerto de 17% por segmento, o
CTA vive da cauda direita). Nenhuma das "melhorias" ajudou no OOS: o stop piora 0,9 pp/ano, a camada de crise é neutra (+0,1) e as duas juntas pioram 1,7; o OOS de todas as
variantes é negativo (−1,2 a −6,1 pp/ano). O OOS 2021–26 é ruim para trend de ativos financeiros (2022 foi bom, 2023–24 devolveram).

---

## IM7 — Tendência de crises (vendido em ações só quando o crédito abre)

**Tese de mesa.** Carregar CTA o tempo todo é caro; o que paga é a cauda. Fico em caixa e só vendo SPY/EFA/EEM (abaixo da média de 200
dias) quando o fator crédito HYG−IEF cai 1,5/2,5/4% do topo de 21 dias; opcionalmente compro TLT.

**Números.** escolhido no IS `{'thr': 0.015, 'tlt': 1}` | IR IS 0,01 | OOS 9,8% vs CDI 11,4% | IR OOS -0,18 | vol OOS 6,6% | pior queda OOS -8,3% | P(bater) 25% | PBO 8% | Sharpe deflac. 13% | custo x2 -1,9 pp | +1 dia -3,6 pp | período todo 9,0% vs 9,9% (IR -0,05, pior queda -10,7%)

**Excesso sobre o CDI por ano (pp):** 2009: -8.2, 2010: -6.3, 2011: -6.1, 2012: +1.0, 2013: +0.7, 2014: +5.8, 2015: -9.2, 2016: +9.5, 2017: -0.2, 2018: -3.7, 2019: -3.8, 2020: +14.6, 2021: +0.7, 2022: +6.1, 2023: -3.1, 2024: -1.2, 2025: -9.3, 2026: -2.1

**Variantes (IR IS → excesso OOS pp/ano):** {thr: 0.015, tlt: 0} -0.02 → +0.1; {thr: 0.015, tlt: 1} +0.01 → -1.1; {thr: 0.025, tlt: 0} -0.37 → -2.4; {thr: 0.025, tlt: 1} -0.34 → -3.3; {thr: 0.04, tlt: 0} -0.45 → -1.8; {thr: 0.04, tlt: 1} -0.49 → -1.4

Negócios: 279 | acerto 45%

10 melhores:

| ativo   | lado     | entrada    | saida      |   dias |   retorno % |   contrib %PL |
|:--------|:---------|:-----------|:-----------|-------:|------------:|--------------:|
| EFA     | vendido  | 2020-03-06 | 2020-04-13 |     25 |         5.6 |          6.24 |
| EEM     | vendido  | 2020-03-06 | 2020-04-13 |     25 |         5.5 |          4.68 |
| EEM     | vendido  | 2015-11-10 | 2016-01-13 |     43 |        14.6 |          3.73 |
| EFA     | vendido  | 2015-11-10 | 2016-01-13 |     43 |         9.1 |          3.5  |
| EEM     | vendido  | 2013-05-30 | 2013-07-09 |     27 |         8.5 |          3.42 |
| SPY     | vendido  | 2020-03-06 | 2020-04-13 |     25 |        -0   |          3.4  |
| EFA     | vendido  | 2022-01-19 | 2022-02-28 |     27 |         5.8 |          2.45 |
| SPY     | vendido  | 2016-01-04 | 2016-01-13 |      7 |         6.3 |          2.36 |
| TLT     | comprado | 2016-01-14 | 2016-02-23 |     26 |         6.3 |          2.35 |
| EEM     | vendido  | 2015-08-07 | 2015-08-31 |     16 |         6.4 |          2.22 |

10 piores:

| ativo   | lado     | entrada    | saida      |   dias |   retorno % |   contrib %PL |
|:--------|:---------|:-----------|:-----------|-------:|------------:|--------------:|
| EFA     | vendido  | 2025-04-07 | 2025-04-21 |      9 |        -9.8 |         -2.81 |
| TLT     | comprado | 2025-04-04 | 2025-04-24 |     13 |        -5.2 |         -2.12 |
| SPY     | vendido  | 2025-04-04 | 2025-04-24 |     13 |        -8.9 |         -2.1  |
| EEM     | vendido  | 2015-09-23 | 2015-10-09 |     12 |        -9.6 |         -2.06 |
| TLT     | comprado | 2013-05-30 | 2013-07-09 |     27 |        -6   |         -2.04 |
| EFA     | vendido  | 2022-03-04 | 2022-03-18 |     10 |        -6.9 |         -1.96 |
| SPY     | vendido  | 2015-08-24 | 2015-08-31 |      5 |        -4.4 |         -1.94 |
| EFA     | vendido  | 2015-09-23 | 2015-10-09 |     12 |        -6.6 |         -1.79 |
| EEM     | vendido  | 2009-02-24 | 2009-03-24 |     20 |       -15.1 |         -1.68 |
| SPY     | vendido  | 2026-03-30 | 2026-04-01 |      2 |        -3.6 |         -1.66 |


**O que deu certo.** Covid (mar/2020: EFA/EEM/SPY vendidos de 06/03 a 13/04, +14% do PL somando as pernas), China/petróleo nov/2015–jan/2016,
taper tantrum EM mai/2013. **O que deu errado.** O gatilho dispara depois que a queda já aconteceu e perto do fundo: abr/2025 (tarifas:
vendido em 04/04 e 07/04, recompra 2 semanas depois: −7% do PL somando SPY/EFA/TLT), set/2015, mar/2022, fev/2009. Com TLT comprado piora
no OOS (2022: juros e ações caíram juntos). Só a variante de gatilho sensível (1,5%) fica perto de zero.

---

## IM8 — Calendário global

**Tese de mesa.** Fluxos com data marcada: salário/aporte na virada do mês (Japão, Alemanha, Brasil: −1 a +3 ou −3 a +3), quem zera risco
antes de feriado longo e volta depois (véspera de feriado nos EUA — excluídos fechamentos imprevistos: Ford 2007, Sandy 2012, Bush 2018,
Carter 2025 —, véspera de feriado no Japão + 3 pregões antes da Golden Week, 5 pregões antes do Ano-Novo Lunar em HK/Taiwan/Coreia),
Ramadã (Golfo, Turquia, Indonésia, Malásia: comprado durante o mês) e "Sell in May" como L/S no tempo (comprado nov–abr, vendido
mai–out — testa a sazonalidade e não o prêmio de ações). Índices locais com hedge (futuros, 2 bps), ETFs do Golfo (30–50 bps × 2),
BOVA11 no calendário B3.

**Números.** escolhido no IS `{'comp': 'tudo'}` | IR IS 0,31 | OOS 9,3% vs CDI 11,4% | IR OOS -0,08 | vol OOS 13,1% | pior queda OOS -23,5% | P(bater) 39% | PBO 88% | Sharpe deflac. 26% | custo x2 -4,8 pp | +1 dia -2,0 pp | período todo 11,5% vs 9,9% (IR 0,17, pior queda -33,5%)

**Excesso sobre o CDI por ano (pp):** 2009: +7.2, 2010: +16.0, 2011: +6.3, 2012: +16.1, 2013: +5.4, 2014: -6.8, 2015: +14.9, 2016: -8.1, 2017: +5.3, 2018: -4.9, 2019: +5.5, 2020: -11.8, 2021: +8.7, 2022: -14.4, 2023: +31.7, 2024: -7.3, 2025: -16.9, 2026: -7.8

**Variantes (IR IS → excesso OOS pp/ano):** {comp: tom} +0.17 → +0.4; {comp: tom-3+3} +0.18 → +1.9; {comp: feriados} +0.06 → +1.8; {comp: religioso} -0.07 → -5.5; {comp: halloween} +0.30 → +1.0; {comp: tudo} +0.31 → -0.9

Negócios: 1303 | acerto 53%

10 melhores:

| ativo              | lado     | entrada    | saida      |   dias |   retorno % |   contrib %PL |
|:-------------------|:---------|:-----------|:-----------|-------:|------------:|--------------:|
| Halloween Japão    | comprado | 2012-10-31 | 2013-04-30 |    119 |        55.2 |          9.49 |
| Halloween Alemanha | comprado | 2023-10-31 | 2024-04-30 |    125 |        18.4 |          5.54 |
| Halloween S&P      | comprado | 2020-10-30 | 2021-04-30 |    124 |        28.7 |          5.36 |
| Halloween S&P      | comprado | 2023-10-31 | 2024-04-30 |    124 |        17.8 |          5.29 |
| Halloween Japão    | comprado | 2020-10-30 | 2021-04-30 |    122 |        25.5 |          5.14 |
| Halloween Japão    | comprado | 2023-10-31 | 2024-04-30 |    120 |        24.5 |          4.97 |
| Halloween Alemanha | vendido  | 2011-04-29 | 2011-10-31 |    130 |        16.3 |          4.95 |
| Halloween Alemanha | comprado | 2020-10-30 | 2021-04-30 |    124 |        31   |          4.61 |
| Halloween S&P      | comprado | 2016-10-31 | 2017-04-28 |    123 |        12.8 |          4.57 |
| Halloween Brasil   | vendido  | 2015-04-30 | 2015-10-30 |    127 |        27.8 |          4.54 |

10 piores:

| ativo              | lado     | entrada    | saida      |   dias |   retorno % |   contrib %PL |
|:-------------------|:---------|:-----------|:-----------|-------:|------------:|--------------:|
| Halloween Japão    | vendido  | 2025-04-30 | 2025-10-31 |    125 |       -32.2 |         -6.18 |
| Halloween Alemanha | comprado | 2019-10-31 | 2020-04-30 |    123 |       -15.6 |         -5.51 |
| Halloween Brasil   | comprado | 2019-10-31 | 2020-04-30 |    123 |       -26.7 |         -5.37 |
| Ramadã UAE         | comprado | 2026-02-17 | 2026-03-19 |     22 |       -18.2 |         -4.97 |
| Halloween Japão    | vendido  | 2017-04-28 | 2017-10-31 |    125 |       -13.2 |         -4.71 |
| Halloween S&P      | vendido  | 2017-04-28 | 2017-10-31 |    129 |        -8.1 |         -4.24 |
| TOM Japão          | comprado | 2024-07-30 | 2024-08-05 |      4 |       -18.3 |         -4.1  |
| Halloween Japão    | comprado | 2019-10-31 | 2020-04-30 |    120 |       -11.9 |         -3.81 |
| Ramadã QAT         | comprado | 2026-02-17 | 2026-03-19 |     22 |        -8.5 |         -3.45 |
| Halloween S&P      | vendido  | 2013-04-30 | 2013-10-31 |    129 |       -10.7 |         -3.44 |


Por manga (soma da contribuição, % do PL, IS → OOS): Halloween Alemanha +15,1 → +10,3; Halloween S&P +21,1 → −5,9; Halloween Japão +15,3 →
−5,6; Halloween Brasil +10,1 → +2,9; virada de mês Brasil +10,1 → +0,9 (no fundo "tudo"); Alemanha −0,1 → +1,1; Japão −2,4 → −1,6;
véspera de feriado EUA +2,5 → +2,2 (a única manga positiva e estável, mas pequena); Japão/Golden Week −0,5 → +1,1; Ano-Novo Lunar
Taiwan −1,4 → +1,7, Kospi +0,8 → +0,1, HSI ~0; Ramadã: Catar −3,7 → −6,2, Emirados −1,2 → −6,1, Malásia −1,8 → −3,4, Indonésia +2,4 → −2,0,
Turquia ~0, Arábia +0,6 → +0,7.

**O que deu certo.** Sell in May na Alemanha (vendido mai–out/2011 +16%, comprado inverno 2023–24 +18%). **O que deu errado.** Sell in May
nos EUA e Japão depois de 2020 (vendido no verão de 2025 com o Nikkei +32%); Ramadã 2026 (guerra/petróleo: Emirados −18% no mês); TOM do
Japão em ago/2024 (crash do carry trade do iene: −18% em 4 dias). PBO 88% — escolher "tudo" pelo IS é overfitting puro.

---

## IM9 — Eleições: compra depois do pânico, com hedge cambial

**Tese de mesa.** O estrangeiro vende primeiro e pergunta depois; o governo eleito costuma moderar. Lista com TODAS as eleições nacionais/
referendos de 20 países 2006–2026 (BR, MX, AR incl. PASO, TR, IN, ZA, ID, KR incl. lei marcial dez/2024, TW, MY, TH incl. golpe 2014, PH, CL
incl. plebiscitos, PE, PL, GB incl. Brexit, FR incl. dissolução 2024, IT incl. referendo 2016, ES, GR incl. referendo 2015) — a regra
decide, não a escolha das datas. Pânico = queda > 3%/6% do fechamento anterior à eleição até o 1º pregão depois; compra no fechamento
seguinte, segura 21/63 pregões, 10% de vol por evento. Veículo: índice local − juro local (futuro) ou ETF em dólar; Turquia/Argentina só ETF.

**Números.** escolhido no IS `{'queda': 0.03, 'dias': 63, 'veiculo': 'etf'}` | IR IS -0,04 | OOS 13,2% vs CDI 11,4% | IR OOS 0,30 | vol OOS 5,8% | pior queda OOS -8,6% | P(bater) 76% | PBO 82% | Sharpe deflac. 66% | custo x2 1,6 pp | +1 dia 1,3 pp | período todo 10,1% vs 9,9% (IR 0,05, pior queda -8,8%)

**Excesso sobre o CDI por ano (pp):** 2009: -0.2, 2010: +6.5, 2011: +1.1, 2012: -0.9, 2013: +3.6, 2014: -5.5, 2015: -8.9, 2016: -0.2, 2017: -0.2, 2018: -3.1, 2019: +1.1, 2020: -0.2, 2021: -4.1, 2022: +4.9, 2023: +4.6, 2024: -1.9, 2025: +7.8, 2026: -0.1

**Variantes (IR IS → excesso OOS pp/ano):** {queda: 0.03, dias: 21, veiculo: hedge} -0.15 → +0.2; {queda: 0.03, dias: 21, veiculo: etf} -0.11 → +0.1; {queda: 0.03, dias: 63, veiculo: hedge} -0.14 → +2.7; {queda: 0.03, dias: 63, veiculo: etf} -0.04 → +1.9; {queda: 0.06, dias: 21, veiculo: hedge} -0.34 → +0.0; {queda: 0.06, dias: 21, veiculo: etf} -0.24 → +0.7; {queda: 0.06, dias: 63, veiculo: hedge} -0.20 → +1.9; {queda: 0.06, dias: 63, veiculo: etf} -0.14 → +2.1

Negócios: 20 | acerto 50%

10 melhores:

| ativo   | lado     | entrada    | saida      |   dias |   retorno % |   contrib %PL |   sinal |
|:--------|:---------|:-----------|:-----------|-------:|------------:|--------------:|--------:|
| CL      | comprado | 2021-12-21 | 2022-03-23 |     63 |        29.5 |          7.59 |  -0.11  |
| AR      | comprado | 2025-09-09 | 2025-12-08 |     63 |        26.6 |          7.1  |  -0.106 |
| GB      | comprado | 2010-05-07 | 2010-08-06 |     63 |        14   |          6.19 |  -0.047 |
| TR      | comprado | 2023-05-16 | 2023-08-16 |     63 |        20.1 |          4.27 |  -0.084 |
| IN      | comprado | 2024-06-05 | 2024-09-05 |     63 |         6.4 |          4.04 |  -0.061 |
| BR      | comprado | 2018-10-30 | 2019-02-01 |     63 |        13.5 |          3.7  |  -0.035 |
| IT      | comprado | 2013-02-26 | 2013-05-28 |     63 |         9.7 |          3.57 |  -0.057 |
| MY      | comprado | 2018-05-10 | 2018-08-09 |     63 |         2   |          1.49 |  -0.06  |
| PE      | comprado | 2011-06-07 | 2011-09-06 |     63 |         3.5 |          1.27 |  -0.138 |
| GR      | comprado | 2015-01-27 | 2015-04-28 |     63 |        -3.8 |          0.45 |  -0.035 |

10 piores:

| ativo   | lado     | entrada    | saida      |   dias |   retorno % |   contrib %PL |   sinal |
|:--------|:---------|:-----------|:-----------|-------:|------------:|--------------:|--------:|
| MX      | comprado | 2024-06-04 | 2024-09-04 |     63 |       -12.7 |         -5.32 |  -0.108 |
| PE      | comprado | 2021-06-08 | 2021-09-07 |     63 |       -14.8 |         -5.3  |  -0.085 |
| TR      | comprado | 2015-06-09 | 2015-09-08 |     63 |       -15.5 |         -4.83 |  -0.066 |
| BR      | comprado | 2014-10-28 | 2015-01-29 |     63 |       -11.7 |         -3.37 |  -0.054 |
| AR      | comprado | 2019-08-13 | 2019-11-11 |     63 |       -14   |         -3.34 |  -0.244 |
| IT      | comprado | 2018-05-30 | 2018-08-28 |     63 |        -5.5 |         -2.68 |  -0.058 |
| GR      | comprado | 2015-07-07 | 2015-12-21 |    117 |       -18.8 |         -2.55 |  -0.075 |
| TR      | comprado | 2014-08-12 | 2014-11-10 |     63 |        -5   |         -1.61 |  -0.032 |
| CL      | comprado | 2022-09-07 | 2022-12-06 |     63 |        -6.1 |         -1.31 |  -0.033 |
| GR      | comprado | 2012-05-08 | 2012-08-07 |     63 |        -6.8 |         -0.5  |  -0.063 |


**O que deu certo.** Chile dez/2021 (Boric, IPSA −11% no dia: +30% em 3 meses), Argentina set/2025 (derrota de Milei em Buenos Aires,
−11%: +27% até dez), Turquia mai/2023 (+20% em dólar), Índia jun/2024 (Modi sem maioria, −6%: +6%), Reino Unido mai/2010, Brasil
out/2018, Itália fev/2013. **O que deu errado.** México jun/2024 (Sheinbaum + reforma judicial: o pânico continuou, −13%), Peru jun/2021
(Castillo, −15%), Turquia jun/2015, Brasil out/2014 (Dilma reeleita: −12%), Argentina PASO 2019 (−24% no dia e mais −14% depois),
Grécia jul/2015 (referendo + controle de capital). Quando a eleição muda de fato o regime de política econômica (AR 2019, MX 2024, PE
2021), o pânico é informação; quando é ruído de transição (CL 2021, IN 2024, AR 2025), é oportunidade. 20 negócios: amostra pequena
demais para separar as duas coisas com regra.

**Próximo passo.** Condicionar no que o mercado de câmbio faz no mesmo dia (moeda caindo mais que a bolsa = saída de capital, não comprar)
e incluir CDS/eurobonds soberanos como veículo.

---

## Ideias pedidas e não feitas (por quê)

- **"Qualidade barata" (lucro estável e P/L baixo):** sem fundamento gratuito com histórico para Japão/Europa; nos EUA o XBRL da SEC (2009+)
  daria, mas o preço das que saíram do índice não existe no Yahoo (mesmo viés documentado na frente global). Feito o substituto por preço
  (IM3) e a reversão (IM2).
- **CAPE/PL de país:** pago (MSCI/Barclays/Research Affiliates). Usei REER do BIS + reversão de 5 anos.
- **Futuros de índice/moeda diretamente (CME/Eurex/OSE):** sem histórico gratuito contínuo confiável; usei índice local − juro local
  (aproxima o futuro, sem base/dividendos: índices de preço — Nikkei, HSI — rendem menos que o futuro em ~2% a.a. de dividendos; nos
  calendários de poucos dias o efeito é desprezível).

## Lições para quem reler

1. A maior parte das estratégias "de mesa" de ações e macro global tem IS fraco e OOS fraco com custos reais; nenhuma passa no critério
   IS bom + OOS bom + PBO baixo. O que melhorou no OOS (reversão mensal Japão com VIX alto, eleições, juro real em moedas) tem IS ≈ 0.
2. Pânicos de crédito pós-2009 são para comprar, não para vender (IM3/IM7 vs a variante oposta) — mesma lição do G6 e do E9.
3. Valor em moeda (PPP) sem stop é catastrófico no ciclo do iene/lira; juro real é o componente que sobrevive.
4. Pares clássicos morrem no custo e nas mudanças de fundamento lentas (Hynix/HBM, Kering/Gucci, BAC/Treasuries): z-stop não pega deriva lenta.
5. Rodar cada mercado no próprio calendário e limpar pares no PAR; cuidado com o OAS do FRED (só 3 anos) e com erros do Yahoo em moedas
   que voltam em 2–3 dias.
