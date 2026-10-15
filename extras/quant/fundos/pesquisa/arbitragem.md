# Frente ARBITRAGENS ESTRUTURAIS E OPÇÕES — caderno de pesquisa (rodada 2, out/2026)

Código: `ideias_arbitragem.py` (estratégias + `FUNDOS` + main), `arb_dados.py` (downloads com cache), `arb_mapa.py` (mapa BDR→EUA).
Resultado: `resultado/ideias_arbitragem.pkl` (cada dict tem `contrib` e `trades`, e `capacidade_R$_por_negocio` quando há volume),
log em `resultado/log_arbitragem.txt`. Convenções do BRIEF: decisão no fechamento de t, execução no fechamento de t+1,
custos com bid/ask real do COTAHIST/opções, benchmark CDI (A6 = Ibovespa).

## Dados novos (quant/fundos/dados)
| arquivo | o que é | observação |
|---|---|---|
| `arb_bdr_vista.parquet` | BDRs re-lidos dos COTAHIST locais (CODBDI 34/35/36 + padrão de ticker) | **bug encontrado**: `b3_vista` NÃO tem BDRs depois de 07/10/2022 (a B3 mudou o CODBDI dos BDRs para 34/36 e o leitor só pegava 02/12/14). 788 mil linhas, 1.286 BDRs |
| `arb_us.parquet` | fechamento EUA não ajustado por dividendos (Yahoo, `Close`) de ~220 ativos-objeto + BTC=F/ETH=F | ATVI, TWTR, JNPR, X, ARNC sem dados (deslistados) |
| `arb_cripto_1h.parquet` | BTC/ETH hora a hora, Binance (2017-08+) | para casar com o fechamento da B3 (20h/21h UTC) |
| `arb_cripto_fut.parquet` | futuros trimestrais COIN-M Binance (contínuo trimestre atual/próximo), diário 00h UTC, 2020-08+ | usado no lugar do CME (ver A7) |
| `arb_proventos.parquet` | proventos em dinheiro B3 (API pública listedCompaniesProxy): **data de aprovação**, data-com, valor, DIVIDENDO/JCP, 92 empresas | ARZZ, BRDT, BTOW, BVMF, CCRO, ELET, KROT, MRFG, RRRP, VIIA, VVAR falharam (códigos antigos) |
| `arb_ind.parquet` (+ `arb_ind_dias/`) | ajustes IND/WIN do boletim BVBG.086 nos 12 pregões antes de cada vencimento, 2019-2026 (643 dias) | só janela de vencimento para não baixar 10 GB |

Evento de resultado: `cvm_itr_dfp.parquet` (já existia; DT_RECEB = 1ª entrega do ITR/DFP = divulgação).

## Resumo (OOS = desde o `corte`; IR vs bench; robustez do motor)
| fundo | params IS | OOS a.a. | bench | IR OOS | P(bater) | PBO | custo x2 | +1 dia |
|---|---|---|---|---|---|---|---|---|
| A1 BDR x EUA | thr 3%, jan 20, compra | 10,6% | 13,1% | -2,27 | 0% | 0% | -4,2 | -2,0 |
| A2 ETFs B3 x NAV | thr 2%, ETFs | 12,8% | 13,1% | -2,29 | 0% | 5% | -0,4 | -0,2 |
| A3 Units x componentes | thr 2%, jan 20 | 10,8% | 11,4% | -0,37 | 7% | 0% | -1,4 | -0,2 |
| A4 Venda de vol | put 5% OTM, filtro IV-RV, sem hedge | 10,4% | 11,4% | -0,20 | 28% | 8% | -1,5 | -0,8 |
| A5 Vol de evento | vender straddle | 9,2% | 11,4% | -1,45 | 0% | 21% | -3,8 | -1,2 |
| A6 Covered call PETR/VALE | call 10% OTM só c/ IV alta | 23,7% | 10,5% (Ibov) | 0,69 | 95% | 45% | +12,9 | +15,5 |
| **A7 Cash-and-carry cripto** | BTC, base > T-bill+10% | **15,4%** | 13,1% | **0,98** | **96%** | 18% | +1,9 | +2,3 |
| A8 Dividendos/JCP (hedge índice) | vendido em JCP, yield ≥1% | 11,2% | 11,4% | -0,07 | 43% | 4% | -4,0 | -0,3 |
| **A9 Base IND x BOVA11** | thr 2%, 5 dias antes | **13,8%** | 13,1% | **0,65** | **94%** | 30% | +0,2 | +0,7 |

Leitura: só A7 e A9 sobrevivem; A6 bate o Ibovespa mas **não por causa das opções** (ver A6).

---

## A1 — BDR x ação nos EUA (prêmio/desconto)
**Tese de mesa**: BDR não patrocinado com formador fraco negocia com desconto sobre (ação EUA × dólar ÷ razão); compro o BDR, vendo a ação lá
fora e dólar futuro, e espero o desconto fechar.
**Implementação**: razão estimada pela mediana móvel (20/60 d, só passado) de log(BDR/(EUA×DOL)); quebras >15% (desdobramento/troca de
razão) bloqueiam o par por uma janela; o **fator comum** (mediana do prêmio dos BDRs líquidos — erro de horário do câmbio: o ajuste do DOL é
~16h, a B3 fecha 17/18h) é subtraído. Sinal no preço de **oferta de venda** do fechamento (o que eu pagaria); execução no fechamento seguinte e
só se o BDR negociou; custo = meio spread real do BDR + 3 bps EUA + 1 bp dólar; até 10% do PL por BDR, saída na reversão ou 20 dias.
Mapa validado (razão estável, correlação > 0,3): 175 BDRs; os NYSE/Nasdaq fecham junto com a B3 (corr. contemporânea 0,91–0,98, defasada ~0).
**Resultado**: negativo em todas as 12 variantes, inclusive **bruto** (~-1% a.a. sem custo). O retorno hedgeado tem autocorrelação de -0,42
(ruído do fechamento que se desfaz no dia seguinte) — capturável só no mesmo fechamento, que o BRIEF proíbe. O meio spread mediano dos BDRs
(1,28%) é 4x o |prêmio| mediano (0,28%).
**Negócios**: ganhos concentrados em INBR32 (16 negócios) e M1TA34; perdas espalhadas (W1DC34, AAPL34, GEOO34, GDXB39, NFLX34) — acerto 20%.
**Bugs achados**: (1) BDRs ausentes de `b3_vista` após out/2022; (2) `limpa` perna a perna criava P&L falso (M1TA34 em 27/10/2022: a perna EUA caiu
24,6%, o BDR >25% e foi zerado → +25% fictício). Corrigido filtrando no PAR (|R|>15% num dia = quebra). (3) 10 mapeamentos errados
(RIOT34, GROP31, B1IL34, ELCI34, BEGU39...) removidos pela validação.
**Próximo**: só faz sentido como formador de mercado (passivo, no mesmo pregão), não como tomador.

## A2 — ETFs da B3 x NAV
**Tese**: IVVB11/NASD11/GOLD11/XINA11/EURP11/ACWI11 (vs SPY/QQQ/GLD/MCHI/IEUR/ACWI × dólar) e ETFs de cripto (HASH11, BITH11, QBTC11, ETHE11,
QETH11 vs BTC/ETH Binance no horário de fechamento da B3) se descolam do NAV.
**Resultado**: ETFs tradicionais têm |desvio| mediano 0,12–0,20% com meio spread 0,03–0,7% e meia-vida < 1 dia → nada sobra (IR -2,3).
Cripto: |desvio| 0,4–0,9%, bruto +1 a +3% a.a., líquido ≈ 0. HASH11/QBTC11 têm meia-vida ~1,5 dia — mas parte disso é erro do meu NAV de HASH11
(proxy 80% BTC/20% ETH do índice Nasdaq Crypto). Melhores: QBTC11 vendido em 12/01/2024 (prêmio 10% no dia seguinte à aprovação dos ETFs spot nos
EUA, +0,9% do PL), HASH11 vendido em nov/2022 (FTX).
**Próximo**: NAV oficial diário dos gestores (CVM informe diário) para HASH11; execução intradiária ao vivo.

## A3 — Units x componentes
**Tese**: unit = n ON + m PN (TAEE11 1+2, KLBN11 1+4, SAPR11 1+4, ENGI11 1+4, ALUP11 1+2, SANB11 1+1, BPAC11 1+2 PNA, TIET11 1+4, IGTI11 1+2,
SULA11 1+2, CPLE11 1+4 PNB, BIDI11 1+2, MODL11 1+2 — composições estimadas por mínimo erro, batem com o estatuto); a diferença tem âncora de
conversão.
**Resultado**: desvio executável raramente passa de 1–2% depois de três meio-spreads; 30 negócios em 12 anos, acerto 23%. O que deu certo:
BIDI11 em mar/2020 (+4,1% do PL, unit 2,7% barata no crash) e BPAC11 jul/2021 (unit 7% barata, fechou em 25 dias). Deu errado: os ON/PN
componentes são ilíquidos (BPAC3, TIET3, SANB3) e o "desvio" é spread, não preço.
**Próximo**: só vale com custo de montagem/desmontagem real (corretora) e execução passiva.

## A4 — Venda de volatilidade B3
**Tese**: "o brasileiro paga caro por proteção". Vendo put (5% OTM), strangle (±5%) ou put spread (−5%/−10%) de ~1 mês em BOVA11, PETR4, VALE3,
ITUB4, BBDC4, no **bid**, segurando até o vencimento (marcação no meio das ofertas, nunca abaixo do intrínseco), com ou sem hedge de delta diário
(BS com a IV de entrada, ação com retorno total, 5 bps + aluguel 1%).
**Medida da IV (BS com CDI, 2014-2026)**: IV ATM − RV21 mediana = +1,3 (BOVA), +1,5 (PETR), +1,8 (VALE), +0,3 (ITUB), +0,2 (BBDC) pontos; IV > RV em
52–63% dos ciclos. Skew (IV put 90% − ATM) mediano 4,5–7 pontos. **O prêmio de vol existe, mas é pequeno perto do spread das opções.**
**Resultado**: escolhido put + filtro IV−RV (IR IS 0,66, PBO 8%) → OOS -1,0 pp vs CDI. Variantes "sempre" (excesso a.a.): put 0,7%, put+hedge 1,3%,
strangle -5,5% (vender call perde: as altas de PETR/VALE são violentas), put spread -1,7%.
**Risco de cauda (put 5% OTM sobre 100% do PL, sem hedge; com hedge entre parênteses)**: Covid mar/2020 -21,9% (-4,5%); greve/Pedro Parente mai-jun/2018
-9,7% (-1,8%); troca do CEO da Petrobras fev/2021 -7,0% (-3,2%); Joesley 18/05/2017 -2,8% (-2,0%); eleição 2022 +2,4%. Pior mês -15% (sem hedge).
Melhores: VALE/PETR 2015-16 (IV 60–180%, puts vendidas no pânico pagaram 1–2,7% do PL). Piores: PETR/ITUB fev/2021, BBDC mai/2018.
**Bug achado**: a raiz da opção mistura classes (VALE5 até 2017, BBDC3, PETR3): séries de VALE5 apareciam como "calls ITM a R$ 0,14" de VALE3. Filtro:
série que viola o intrínseco do nosso ativo em ≥20% dos dias é descartada; ofertas absurdas (venda a 99,99) não marcam. Antes do filtro havia dias
de -586% do PL (ITUB 09/03/2020).
**Capacidade**: o put escolhido negocia R$ 0,1–0,5 mi/dia de prêmio (≈ R$ 10–50 mi de nocional) → R$ 2–10 mi de nocional por ativo por ciclo.
**Próximo**: vender só BOVA11 com hedge e put spread no skew alto (variante `filtro="skew"` existe), vencimentos semanais (2024+).

## A5 — Vol de evento (straddle em resultados)
**Tese**: IV "justa" na véspera = sqrt((RV21²·(T−2/252) + m²)/T), m = RMS dos 8 últimos movimentos de 2 dias em resultados da empresa. Compro
straddle ATM se IV < justa·(1−margem), vendo se IV > justa·(1+margem); entrada na véspera (ask/bid), saída 1 pregão após o evento.
20 ações, 1.016 eventos CVM.
**Resultado**: negativo em comprar, vender e ambos. A IV na véspera já embute o evento (IV mediana 39% vs justa 33%), e o straddle de ação BR
custa 10–30% do prêmio em spread de ida e volta. Piores: vender ABEV fev/2025 (+10,5% em 2 dias), BBAS mai/2025 (-14,8%), VALE abr/2022.
**Bug corrigido**: vendia no bid de pernas com spread de 80% (LREN): agora só agride livro com spread ≤ 25% do meio.

## A6 — Covered call PETR4/VALE3 (bench Ibovespa)
OOS 23,7% vs Ibov 10,5% (IR 0,69), MAS a decomposição mostra: **ações − CDI = +14,3% a.a. OOS (PETR com dividendos gigantes 2021-23); overlay de
calls = -1,0% a.a. OOS e -3,9% a.a. IS.** Vender call nos meses de IV alta perdeu menos que vender sempre (-6 a -12% a.a.), mas sempre perdeu.
Pior: call PETR fev/2016 (PETR +60% em um mês: -28,7% da posição). **Não é alfa de opções; é PETR4 vs Ibovespa.** Drawdown total -73% (2015-16).

## A7 — Cash-and-carry cripto  ★
**Tese**: a demanda alavancada comprada faz o futuro trimestral negociar 5–30% a.a. acima do spot em mercados de alta. Compro spot, vendo o
futuro, recebo a base até a véspera do vencimento (última sexta de mar/jun/set/dez), sem risco de preço.
**Implementação**: futuro trimestral COIN-M da Binance (contínuo, dia 00h UTC) vs spot Binance no MESMO horário. CME via Yahoo foi descartado
para execução: o `BTC=F` diário tem desvio-padrão de 1,1% na base contra o spot no horário de liquidação (o horário do "close" do Yahoo é
inconsistente; base no dia do vencimento de jan/2024 aparecia -1,6%). Média mensal do CME confirma a ordem de grandeza (≈ +0,2–0,35% ao mês em
2020/21/23/24). Capital = 125% do nocional (margem), custo 14 bps por entrada/saída, excesso sobre T-bill convertido para R$ com hedge (`brl`).
**Resultado**: base mediana BTC 12% a.a. (2020-21), 1,6% (2022), 5,5% (2023), 10% (2024). Com filtro base − T-bill > 10%: 12 negócios, acerto 83%,
OOS 15,4% vs CDI 13,1% (IR 0,98), P(bater) 96%, robusto a custo x2 e +1 dia; todas as 9 variantes batem o CDI no OOS.
**O que deu certo**: mar–jun/2021 entrou a 24,7% a.a. (+4,6% do PL em 89 dias), mar–jun/2024 a 28,7% a.a. (+4,1%, ETFs spot), dez/2020–mar/2021
a 20% a.a. (+3,5%). Errado: entradas com < 10 dias para o vencimento (mar/2023, dez/2023) só pagaram custo.
**Riscos não modelados**: contraparte (FTX 2022 — o mesmo trade na corretora errada perdia tudo), margem chamada em alta violenta do BTC
(precisa de colchão de caixa), limites de remessa/câmbio de um fundo BR. No CME o carry é igual com custódia mais segura (ETF spot + CME).
**Capacidade**: livros de dezenas de US$ milhões/dia; não é limitante para fundo próprio.

## A8 — Dividendos/JCP na data-ex (com hedge de índice)
**Medida**: em 1.420 eventos com yield bruto > 1%, a ação cai em média **100% do provento bruto** (mediana 0,97); JCP-pesado cai 92% do bruto, dividendo
104%. Ou seja, o preço desconta o JCP quase pelo bruto: o investidor que paga 15% de IR perde; o **isento** (fundo de investimento não sofre
retenção de JCP) ganharia ~8% do JCP — 0,08–0,15% por evento, menos que o custo de ida e volta (meio spread + 4 bps x2).
**Resultado**: comprado perde (IS e OOS); vendido em JCP ≈ CDI (OOS 11,2% vs 11,4%). Sem o hedge de índice (primeira versão) o resultado era
dominado pelo mercado do dia (VBBR3 -7,4% em 26/11/2025). Só eventos com aprovação ≤ pregão anterior à data-com (sem look-ahead).
**Próximo**: só para quem já tem a ação em carteira (custo zero de entrada): adiar a venda para depois da data-com em JCP.

## A9 — Base IND x BOVA11 no vencimento  ★ (pequeno)
**Tese**: nos 5 pregões antes do vencimento a taxa implícita do IND contra o Ibovespa se afasta do CDI (rolagem); compro BOVA11 e vendo IND se a
taxa > CDI+2%, ou o inverso (vendo BOVA11 com aluguel 1%, compro IND) se < CDI−2%; seguro até o vencimento.
**Resultado**: 35 negócios, acerto 66%, +0,12% por negócio; OOS 13,8% vs 13,1% (IR 0,65, P(bater) 94%). Ganho real ≈ +0,7 pp a.a. sobre o CDI com
vol de 1% — é renda fixa sintética, como o box. A taxa implícita medida fica quase sempre ABAIXO do CDI (o `^BVSP` do Yahoo e o ajuste do IND
não são simultâneos; o ajuste final é média, não fechamento) — por isso o lado "reverso" domina; parte do ganho pode ser esse descasamento.
**Próximo**: Ibovespa oficial no horário do ajuste e o preço médio de liquidação; aluguel real de BOVA11.

---

## Conclusão de mesa
1. Arbitragem de preço (BDR, ETF, units) na B3 está arbitrada pelos formadores dentro do mesmo pregão; com t+1 e custo de tomador não sobra nada.
2. O prêmio de volatilidade na B3 existe (+1 a +2 pontos), mas o spread das opções de ação come quase tudo; a cauda é real (-22% em mar/2020 por
   100% de nocional). Delta hedge melhora o perfil (pior mês -2,7% vs -15%).
3. O único carry estrutural grande e persistente foi a base de cripto (A7) — pago por quem quer alavancagem comprada. Exige gestão de contraparte.
4. Dividendo/JCP: o mercado precifica pelo bruto; vantagem só para quem é isento E já está posicionado.
