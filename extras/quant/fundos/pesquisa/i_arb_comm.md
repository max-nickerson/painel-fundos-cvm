# Frente i_arb_comm — arbitragens estruturais, vol e ações x commodity fora do Brasil (fase 2, out/2026)

Código: `ideias_i_arb_comm.py` (9 fundos IAC1–IAC9 + `analises()`), downloads em `dados_i_arb_comm.py`.
Resultados: `resultado/ideias_i_arb_comm.pkl` (cada dict com `contrib` diária por par/perna em R$ e `trades`), log
`resultado/log_i_arb_comm.txt`, tabelas completas `resultado/i_arb_comm_tabelas.md`, medições `resultado/i_arb_comm_analises.txt`
(`python ideias_i_arb_comm.py analise`).

## Dados novos (quant/fundos/dados)
| arquivo | conteúdo | observação |
|---|---|---|
| `i_arb_px / i_arb_close / i_arb_vol.parquet` | Yahoo: 360 tickers (fech. ajustado, não ajustado e volume financeiro local) — classes de ações EUA/Europa, preferenciais coreanas, 26 pares A/H, holdings e participações, ~80 ações de commodities, ~35 futuros contínuos, ETFs de vol, câmbio | `i_arb_tentados.txt` lista o que falhou: Shell RDS-A/B, Unilever NV (UN/UNA antigos), BHP plc ADR (BBL), Carnival plc (CUK, CCL.L), Jardine Strategic (J37.SI), Exor antes de 2022 (EXO.MI), Roche GS (ROG.SW), BMW pref, Telecom Italia savings, LBRDK, LSXMA/K, X, ARCH/CEIX. **Shell A/B e Unilever NV/PLC não puderam ser testados** (Yahoo apagou as linhas extintas). BHP.L vem contínuo: até 31/01/2022 é a BHP plc (DLC), depois a listagem secundária da Ltd. |
| `i_arb_cboe.parquet` | CBOE (cdn.cboe.com, desde 1986): PUT, BXM, BXMD, BXY, PPUT, CNDR, CLL, BFLY, WPUT, PUTR, CMBO, VXTH, BXMW, SPEN | requests precisa seguir o redirect (307) |
| `i_arb_v2x.parquet` | VSTOXX (stoxx.com, 1999+) | requests falha na cadeia SSL do stoxx.com nesta máquina → baixado via `curl` |
| `i_arb_funding.parquet` | financiamento 8h dos perpétuos USDT-M Binance (BTC, ETH, SOL, BNB, XRP, DOGE), 2019-09+ | |
| `i_arb_cripto_d.parquet` | diário 00h UTC spot e perpétuo dos mesmos | |
| sem fonte gratuita | Nikkei VI (site da Nikkei 404), futuros de V2X, preço spot de urânio (usei Yellow Cake YCA.L, que detém U3O8 físico), café robusta (RC=F não existe), spark spread (sem eletricidade) | |

## Convenções (além do BRIEF)
- Tudo em dólar, excesso sobre o T-bill, calendário seg–sex com ffill ≤ 5 dias; `brl()` converte para R$ com hedge. Pares com
  moedas diferentes: o spread do sinal é em US$; a perna rende em moeda local (hedge cambial).
- Decisão no fechamento de t (Ásia, Europa e EUA já fecharam), execução no fechamento de t+1+lag de cada perna. Isso mata a "arbitragem"
  de fuso: quem fecha antes (Ásia) já absorveu no t+1 a notícia que a Europa/EUA viu no t.
- Custos de uma via pela liquidez mediana (3 bps > US$500 mi/dia … 60 bps < US$1 mi/dia) + impostos: selo UK 0,5% na compra (.L),
  HK 0,1–0,13%, imposto de venda coreano ~0,2%, A-share 0,05–0,1%, FTT França 0,3% e Itália 0,1%. Aluguel 0,5% (líquidas)/2%
  (ilíquidas)/8% (A-share). **Coreia: venda a descoberto proibida** 10/2008–05/2009, 08–11/2011, 16/03/2020–30/03/2025 para
  preferenciais (fora do KOSPI200) e 03/2020–05/2021 + 11/2023–03/2025 para as ordinárias — o código não abre o lado que exigiria vender
  o papel proibido.
- Tamanho fixado na ENTRADA do negócio (risco igual por par com vol do passado, teto por par e bruto total). Primeira versão recalculava
  o tamanho todo dia pela vol → giro de rebalanceamento custava 3–4 pp/ano no IAC1 (bug de desenho corrigido).
- Máquina de reversão: depois de saída por prazo (tmax) ou stop (|z|>4), só reentra quando |z| volta abaixo do limiar. Sem isso o
  par "saía e reentrava no mesmo dia" (negócios de 240 dias com tmax=120) — o mesmo vício existe no `histerese` da frente de commodities.
- Pares limpos no PAR (|r_A − r_B| > 15% num dia → 0).

## Resumo (OOS = 2021+; IAC9 = 2023+; bench CDI)
| fundo | params IS | OOS a.a. | CDI | IR OOS | P(bater) | PBO | custo x2 | +1 dia | % var > CDI |
|---|---|---|---|---|---|---|---|---|---|
| IAC1 Classes e dual-listed EUA/Europa | z 2, desvio > 5x custo | 10,9% | 11,4% | -0,08 | 37% | 8% | -5,2 | -1,8 | 0% |
| IAC2 Ásia: pref. coreanas + A/H | neutro ao fator, sem vender A | 10,1% | 11,4% | -0,29 | 27% | 54% | -5,5 | -1,7 | 38% |
| IAC3 Descontos de holdings | só comprado no desconto, z 2,5, 1 ano | 12,4% | 11,4% | 0,21 | 70% | 30% | -0,5 | +0,8 | 75% |
| **IAC4 Prêmio de vol c/ hedge de beta** | **swap de variância S&P, sempre** | **20,2%** | 11,4% | **0,68** | **94%** | **2%** | +8,2 | +7,6 | 42% |
| IAC5 Futuros de VIX vendidos | VIXM, contango + VVIX, sem hedge | 11,3% | 11,4% | 0,01 | 49% | 42% | -0,5 | +2,3 | 75% |
| IAC6 Energia vs commodity | momentum do resíduo, 126d | 1,9% | 11,4% | -0,62 | 3% | 62% | -10,4 | -9,3 | 38% |
| IAC7 Metais/agro vs commodity | momentum do resíduo, 126d | 11,0% | 11,4% | 0,03 | 46% | 36% | -1,5 | +0,5 | 0% |
| IAC8 Spreads físicos | todos, z 1,5, 126d | 7,3% | 11,4% | -0,33 | 19% | 18% | -4,9 | -5,6 | 0% |
| **IAC9 Base cripto/S&P** | **perpétuos, financiamento > T-bill+10%** | **14,6%** | 13,1% | **2,53** | **98%** | **0%** | +0,9 | +1,5 | 100% |

Leitura curta: **duas coisas sobrevivem** — o prêmio de variância do S&P com o beta vendido (IAC4) e o carry de financiamento dos perpétuos
de cripto (IAC9, mas só em mercado de alta alavancado; OOS pequeno). O resto replica o que vimos no Brasil: a arbitragem de preço de classes/
dual-listed/A/H **existe bruta (+5–6 pp/ano) e morre no custo**; ações x commodity é regime (reversão perdeu em 2008–20 e ganhou em 2021+,
momentum o contrário); holdings só pagam como "compra no pânico".

---

## IAC1 — Classes de ações e dual-listed (análogo a units/ON-PN)
**Tese.** Duas classes com o mesmo fluxo (GOOG/GOOGL, BRK-A/B, FOX/FOXA, NWS/NWSA, FWONA/K, BATRA/K, UA/UAA, LEN/LEN-B, HEI/HEI-A,
MOG-A/B, BF-A/B, Z/ZG, GEF/GEF-B; Heineken Holding/Heineken, Lindt PS/NR, VW ON/PN, Henkel, Sartorius, Fuchs, Atlas/Ericsson/Investor/
Volvo/SKF/Essity A/B, Schindler, Carlsberg, Maersk, Swatch) e a mesma empresa em duas bolsas (Rio Tinto plc x Ltd — DLC ainda vivo —,
BHP plc x Ltd, Unilever Amsterdã x Londres). Compro a barata/vendo a cara quando |z| > z_in e o desvio paga 3–5x o custo de ida e volta.
**Resultado.** Bruto **+6,4 pp/ano** (2008–26, z 2/63d), sobrevive a +1 dia sem custo (+3,8 pp OOS) — é preço real, não ruído de
fechamento. Líquido ≈ 0 ou negativo em todas as 8 variantes; o filtro "desvio > 5x custo" levou o IS a +0,6 pp e o OOS a −0,4 pp.
Como no Brasil (A3), o spread executável raramente cobre o custo de quatro meias-pernas.
**O que deu certo.** Linhas ilíquidas: MOG-B x MOG-A (+1,0 pp/ano OOS), FWONK x FWONA (+0,6), Lindt NR x PS, Carlsberg A x B; vender
Z/comprar ZG em nov/2016 (+4,5% em 14 dias); comprar Heineken Holding no pânico de 13/03/2020 (desconto 5,8% maior que o normal, fechou em
3 dias); BHP plc x Ltd na unificação de jan/2022 (+12,6% em 6 dias — o plc negociava com desconto que a fusão eliminou).
**O que deu errado.** VW ON x PN (o squeeze da Porsche em 2008 e o pânico de 2020: −16% e −8%), LEN-B x LEN em mar/2020 (−7% em 3 dias),
NWS x NWSA 2024–25 (desconto da classe votante abriu sem voltar — o mercado reprecificou o valor do voto dos Murdoch).
**Rio Tinto plc x Ltd.** O DLC tem desconto estrutural (Ltd mais cara pelo franking credit australiano), negociou poucas vezes e deu −0,03 pp OOS.
**Próximo.** Só como formador de mercado passivo nas linhas ilíquidas (MOG, FWON, Lindt, Carlsberg). Não é fundo de tomador.

## IAC2 — Preferenciais coreanas e prêmio A/H
**Medições.** Desconto mediano da preferencial (1 − pref/ord): Samsung 9–41% (mínimo 9% em 2021–22, 29% em 2026), Hyundai 24–71%,
LG Chem 27–69%, Amorepacific 40–75%. Prêmio A/H mediano dos 26 pares: −8% (2014, antes do Connect) a +50% (2007, 2024); 2021–24 entre
+41 e +50%, recuou para +29% em 2026. **Os dois "spreads" têm tendências de vários anos** (reforma de governança coreana; liquidez do Connect).
**Implementação.** Spread em US$, z 126/252d; variante `neutro` tira o fator comum (prêmio médio do grupo) e faz o hedge com a carteira dos
pares; variante "sem vender A" (estrangeiro não aluga A-share na prática) só compra A via Connect e vende H.
**Resultado.** Bruto positivo em quase todos os nomes (o A/H rende +0,2 a +0,7 pp/ano por par sem custo). O IS escolheu Coreia + A/H
neutros, sem vender A (IR IS 0,67), mas o OOS deu −1,3 pp: 2026 sozinho −11 pp (Hyundai pref comprada em dez/2025–jan/2026, a ordinária
disparou com a reforma de governança e a pref ficou 27% para trás). Melhor variante OOS: só A/H, neutro, sem vender A (+2,4 pp, IR 0,48) —
não escolhida no IS. **A/H é o único par desta família em que o desvio é grande o bastante para pagar o custo** (+0,1 a +0,3 pp/ano por par líquido OOS).
**Negócios.** Bons: vender pref LG H&H set–dez/2018 (+22,6%); Anhui Conch out/2008 (+54% no par). Ruins: comprar H/vender A do ICBC
dez/2014 (Connect + bolha de A-share: −21%), Hyundai pref 2025–26.
**Próximo.** A/H neutro com 26–50 pares e só do lado executável (comprar A via Connect/vender H); Coreia só com alguma âncora de evento
(recompra/cancelamento de pref, mudança de payout) — reversão pura contra reforma de governança é vender put.

## IAC3 — Descontos de holdings
**Tese.** Holding = carteira listada × (1 − desconto). Naspers/Prosus x Tencent, Porsche SE x VW, Dior x LVMH, Wendel x Bureau Veritas,
Heineken Holding, Exor (só 2022+), Investor, Industrivärden, GBL, SoftBank, Jardine (Jardine Strategic sem dados).
**Implementação.** Resíduo em US$ da holding contra a cesta (pesos aproximados das participações listadas, beta 1 ano em retornos de 5 dias);
z do resíduo acumulado. Não tenho NAV oficial/quantidade de ações → o "desconto" é estimado; a cesta ignora não listados (Patricia, Sienna,
Vision Fund) e dívida líquida.
**Resultado.** Vender a holding quando o desconto fecha perde sempre (o desconto tem tendência a abrir: Naspers −300 pp em log contra Tencent
desde 2005, Porsche −120, Wendel −130). Só comprado no desconto extremo (z 2,5, 1 ano): IS ≈ 0, OOS +1,0 pp (IR 0,21, P 70%, robusto a
custo x2 e +1 dia). O ganho vem de COMPRAR NO PÂNICO: Porsche SE ago/2009 (+14,5% em 4 dias), Wendel set/2008, out/2010 e nov/2025
(+13–27%), Industrivärden set/2008, SoftBank mar/2020 (+30% em 32 dias, recompra de ¥4,5 tri anunciada). Errado: comprar em 05/03/2020
(Wendel −14,7%, Dior −9,3% em uma semana — o desconto abre MAIS no meio da queda); GBL 2010–11.
**Próximo.** NAV oficial (relatórios mensais de Investor/GBL/Prosus) e gatilho de evento (recompra/venda de participação anunciada).

## IAC4 — Prêmio de vol com hedge de beta ★
**Pergunta da rodada 1:** o "prêmio de vol" era beta de S&P? **Resposta (tabela em `i_arb_comm_analises.txt`):**
| estrutura (US$, excesso sobre T-bill) | beta | IS 2008–20 sem hedge | IS com hedge | OOS sem hedge | OOS com hedge |
|---|---|---|---|---|---|
| PUT (put-write ATM mensal) | 0,63 | +5,1% | −1,8% | +6,8% | +1,1% |
| BXMD (buy-write 30 delta) | 0,83 | +7,3% | −1,4% | +8,0% | −0,3% |
| CNDR (condor) | 0,14 | −1,9% | −3,0% | −0,8% | −1,3% |
| WPUT (put-write semanal) | 0,56 | +1,9% | −3,7% | +1,2% | −4,6% |
| swap de variância S&P (por 1 de vega) | 0,88 | +19,2 pts | +11,8 pts (SR 0,45) | +28,9 | +19,2 (SR 0,84) |
| swap de variância Euro Stoxx 50 | 0,63 | +10,2 pts | +10,9 pts (SR 0,38) | +26,8 | +17,9 (SR 0,89) |

1. **Nos índices CBOE de opções o prêmio é beta.** Com o beta vendido, put-write, buy-write, condor e borboleta perdem 1–6% a.a. (custo de
   rolagem de 0,6–1,2% a.a. incluído). Confirma a rodada 1 com 14 índices desde 1986.
2. **No swap de variância o prêmio sobrevive ao hedge.** IV − RV futura: S&P média 3,75 pontos (IV > RV em 85% dos dias), Europa 3,76 (81%).
   O swap captura a convexidade inteira (vende vol nos dois lados e a cauda), o put-write ATM só uma parte e tem gama mal coberto pelo hedge
   linear. Vendendo a variância 1 vol abaixo do VIX (EUA) / 1,5 do VSTOXX (Europa), teto de 2,5x, hedge diário do beta: IS +2,75 pp/ano, OOS
   +8,5 pp/ano sobre o CDI (vol-alvo 8%, vol realizada 12%), PBO 2%, robusto a custo x2 e +1 dia.
3. **Cauda.** 2008 −16 pp, 2015 −11 (ago/2015), 2018 −20 (Volmageddon + Q4), 2025 −12,6 (tarifas abr/2025); DD total −27%. É vender seguro
   com Sharpe ~0,5–0,8, não arbitragem.
**Ressalva.** O swap é sintético (strike = VIX² − custo; dealers cotam 0,5–1,5 vol acima); não testei o efeito de margem/limite de vega.
**Próximo.** Swap de variância real (ou réplica com strip de opções) e corredor (corridor variance) para cortar a cauda; combinar EUA+Europa.

## IAC5 — Futuros de VIX vendidos
**Bug do SVXY tratado:** SVXY era −1x até 27/02/2018 e −0,5x depois (desvio relativo a −VIXY 1,12 → 0,50; correlação 0,88 → 0,997);
05–06/02/2018: SVXY −32% e −83%. Usei −VIXY/−VIXM (índice de futuros 1x vendido, aluguel 3% a.a.), que é o antigo SVXY sem a troca de alavancagem.
Acumulado 2012–26: −VIXY 17,8x; SVXY "corrigido para −1x" 4,4x (a diferença é aluguel/taxa do ETF e o desastre de fev/2018 com −1x).
**Resultado.** IS escolheu VIXM (médio prazo, menos cauda) com contango + VVIX < p80: IS +4,4 pp/ano, OOS +0,2 (P 49%). Curto prazo
(VIXY) sem filtro dá +11,7 pp OOS mas com cauda (SR 0,7). **Com hedge de beta quase tudo some** (VIXY contango: IS +8,7 → +2,1% a.a.) —
igual ao IAC4: o roll do VIX paga principalmente o beta. Melhores: VIXM jul–dez/2012 (+43%), out/2022–mar/2023 (+25%); piores: ago–out/2018,
02→03/04/2025 (Liberation Day: −11% em 1 dia, o t+1 de novo).

## IAC6/IAC7 — Ações x commodity com hedge de 2 fatores (commodity + mercado)
**Implementação.** 26 pares de energia (refinadoras x crack 3:2:1, majors x Brent, aéreas x diesel/QAV, carvoeiras x carvão Rotterdam) e
32 de metais/agro (BHP/RIO/FMG/VALE x minério SGX, FCX/SCCO/ANTO/TECK/GLEN/AAL x cobre, NEM/AEM/KGC/GOLD/NST/EVN x ouro, CCJ/NXE/UEC/DNN x
urânio físico (YCA.L), NUE/STLD/CLF/MT x HRC, CF/MOS/NTR/YAR x milho, TSN x boi, PPC x milho, HRL x porco, S32 x alumínio).
Resíduo = ação − β_c commodity − β_m mercado (SPY ou EFA), 1 ano de retornos de 5 dias; z semanal; reversão (tese) ou momentum.
**Resultado — é regime, não alfa.** Reversão: IS 2008–20 **−5 a −11% a.a.**, OOS 2021+ **+4 a +5% (energia)**. Momentum: o espelho
(IS +2,5 a +5,4%, OOS −8 a −10% em energia). O IS escolheu momentum nos dois livros → energia OOS −9,5 pp (P 3%), metais ≈ CDI.
O momentum ganhou em 2008–20 porque o resíduo de ações de commodities tem tendência nos ciclos de falência/recuperação: vender UAL e AAL x
querosene dez/2019–mai/2020 (+124% e +98% no par), Yancoal 2014–15 (+198%), PBR comprada pós-2008 (+184%); 2020 deu +82 pp no livro de
energia. Depois de 2021 o resíduo voltou a reverter (C1/C4 da frente BR acharam o mesmo). Filtro "pânico" (só entra com vol da commodity
> p75) reduz as perdas da reversão no IS (−3%) mas não cria alfa.
**O que tirar daqui.** A mesma tese do Brasil (PETR4 x Brent, GDXJ x GDX) só funcionou no OOS; globalmente, com 58 pares e 18 anos, a
reversão do resíduo ação-commodity tem sinal instável entre décadas. Não vale como fundo sistemático.

## IAC8 — Spreads com arbitragem física
Crack 3:2:1, crush, trigo KC x Chicago, boi gordo x bezerro, porco x milho, diesel x gasolina, Brent x WTI; variante com spreads "de
qualidade" (prata/ouro, platina/paládio, trigo/milho, soja/milho, café/açúcar) e gás vendido no inverno.
**Resultado.** IS escolheu "todos" (+0,5 pp), OOS −4 pp. Os que pagam: **crack 3:2:1 OOS +1,3 pp/ano** (vender crack em mar/2026 +11,6%),
gás vendido no inverno (out/2015 +74%, out/2011 +67%, out/2022 +99%), trigo KC x Chicago e trigo x milho no IS. Os que perdem: Brent x WTI
(2014 shale, 2026), diesel x gasolina (2020: diesel despencou com o fim do transporte), boi x bezerro, prata x ouro 2010–11 (−37%).
Com a mesma lógica do C6 da rodada BR o resultado OOS é pior porque aqui os 13 pares têm o mesmo peso e os "físicos" ruins diluem o crack.
**Próximo.** Só crack + gás de inverno (os dois com arbitragem física de verdade e assimetria sazonal), tamanho pela vol implícita.

## IAC9 — Base: cripto e S&P ★ (com ressalva)
**Medições.** Financiamento anual dos perpétuos: 2021 22–48% (todas as moedas), 2022 −37% (SOL) a +4%, 2023 0–10%, 2024 12–14%,
2025–26 0–5%. Taxa implícita do ES (ln(F/S)/T + dividend yield) − T-bill: mediana +0,3 pp/ano, **+0,95 pp em 2024 e +0,65 em 2025**
(o famoso "equity repo" caro dos bancos); −0,3 em 2022.
**Resultado.** IS escolheu os perpétuos com limiar T-bill + 10%: IS IR 6,1 (2020–22), OOS 14,6% vs CDI 13,1% (IR 2,5, vol 0,5%, P 98%,
PBO 0%, todas as 8 variantes > CDI). **Regra anti-autoengano (Sharpe > 1,5):** verifiquei — spot e perpétuo da mesma corretora no mesmo
candle (00h UTC; base |P/S − 1| mediana 5 bps), sinal pelo financiamento de 7 dias JÁ pago, execução no dia seguinte, sinal do
financiamento correto (positivo = comprado paga vendido), custo 15 bps/montagem e capital 1,25x. O Sharpe alto é real para a base em si
**porque o risco não está na série**: contraparte (FTX 2022), ADL/liquidação do lado vendido num pico, congelamento de saques. Em 2021
o livro rendeu +29,5 pp; no OOS só 2024 pagou (+4,5) — o resto do tempo o dinheiro fica parado no T-bill (o excesso OOS sobre o CDI é
+1,5 pp). Trimestral COIN-M (A7 da rodada BR com BTC+ETH): IS +4,5%, OOS +2,3% a.a.; SPY x ES: +0,2 pp/ano com SR 0,1 (o close do
ES=F no Yahoo e o dividendo estimado pelo histórico geram ruído do tamanho da base).
**Próximo.** Livro único "base alta" (perp + trimestral + CME + ES quando a taxa implícita > T-bill + 0,5) com limite por corretora;
ES/SPY só com preços de liquidação oficiais e dividendos futuros.

## ADRs indianos (item 7)
Não retomado: INFY/WIT/HDB/IBN x NSE já foi testado na rodada global (G8); a NSE fecha antes da abertura de NY, então com execução t+1 o
prêmio estrutural (HDB 5–20% por limite de capital estrangeiro) é carregar a diferença de demanda, não arbitragem — sem ideia nova.

## Bugs/armadilhas encontrados
1. Tamanho recalculado diariamente pela vol → giro falso (−3 a −4 pp/ano no IAC1). Tamanho travado na entrada.
2. Reentrada imediata após saída por prazo/stop → negócios "eternos" que mascaravam o tmax (afeta `ideias_commodities.histerese`).
3. SVXY troca de −1x para −0,5x em 27/02/2018: qualquer série longa de SVXY mistura dois produtos. Use −VIXY/−VXX com aluguel.
4. ES=F do Yahoo no dia do vencimento (3ª sexta) traz a liquidação especial (SOQ) da abertura contra o fechamento do índice — excluí os
   dias de rolagem (r_ES = 0 quando o contrato muda).
5. Yahoo sem linhas extintas (Shell A/B, Unilever NV, BHP plc ADR, Jardine Strategic, Exor antigo): os pares históricos mais famosos não
   são testáveis com fonte gratuita — viés de sobrevivência a favor dos pares que continuam vivos.
6. stoxx.com: falha de certificado no Python (cadeia SSL incompleta no Windows) → curl.

## Conclusão de mesa
1. **Arbitragem de classes, dual-listed, preferenciais e A/H**: o desvio existe e reverte (bruto +5–6 pp/ano, sobrevive a +1 dia), mas o
   tomador paga 4 meias-pernas + impostos e fica com zero — idêntico a units/BDR no Brasil. Só como formador de mercado passivo.
2. **Vol**: o prêmio de vol "puro" (sem beta) não existe nos índices de put-write/buy-write, mas existe no swap de variância (S&P e
   Europa, ~3,7 pontos de IV sobre RV): é o único livro de vol que sobrevive ao hedge — com cauda de −15 a −20% em 2008/2018/2025.
3. **Base**: carry de quem quer alavancagem (perpétuos de cripto, ES caro em 2024–25) paga, mas é episódico; o risco é de contraparte.
4. **Ações x commodity**: sinal instável entre regimes (reversão perdeu em 2008–20 e ganhou em 2021+). Não sistematizar.

---
# Apêndice — tabelas do motor (contribuição por perna IS/OOS, 10 melhores e 10 piores negócios; contrib em pp do PL)

| fundo | params IS | IR IS | OOS a.a. | CDI | IR OOS | P(bater) | PBO | custo x2 (pp) | +1 dia (pp) | mediana variantes (pp) | % var > CDI |
|---|---|---|---|---|---|---|---|---|---|---|---|
| IAC1 Classes de ações e dual-listed EUA/Europa | {'conj': 'eua+eur+dlc', 'z_in': 2.0, 'k_custo': 5.0} | 0.16 | 10.9% | 11.4% | -0.08 | 37% | 8% | -5.2 | -1.8 | -1.4 | 0% |
| IAC2 Ásia: preferenciais coreanas e prêmio A/H | {'conj': 'coreia+ah', 'neutro': 1, 'lado_ah': 'sem_vender_A'} | 0.67 | 10.1% | 11.4% | -0.29 | 27% | 54% | -5.5 | -1.7 | -1.3 | 38% |
| IAC3 Descontos de holdings | {'jan': 252, 'z_in': 2.5, 'lado': 'desconto'} | 0.01 | 12.4% | 11.4% | 0.21 | 70% | 30% | -0.5 | +0.8 | +1.0 | 75% |
| IAC4 Prêmio de vol com hedge de beta (CBOE + variância EUA/Europa) | {'estrutura': 'VS_EUA', 'filtro': 'sempre'} | 0.21 | 20.2% | 11.4% | 0.68 | 94% | 2% | +8.2 | +7.6 | -0.6 | 42% |
| IAC5 Futuros de VIX vendidos (roll do contango) | {'perna': 'VIXM', 'filtro': 'vvix', 'hedge': 0} | 0.78 | 11.3% | 11.4% | 0.01 | 49% | 42% | -0.5 | +2.3 | +1.5 | 75% |
| IAC6 Energia: refinadoras, petroleiras, aéreas e carvão vs commodity | {'jan': 126, 'filtro': 'nenhum', 'modo': 'momentum'} | 0.41 | 1.9% | 11.4% | -0.62 | 3% | 62% | -10.4 | -9.3 | -0.9 | 38% |
| IAC7 Metais, urânio, aço, fertilizantes e proteína vs commodity | {'jan': 126, 'filtro': 'nenhum', 'modo': 'momentum'} | 0.28 | 11.0% | 11.4% | 0.03 | 46% | 36% | -1.5 | +0.5 | -2.3 | 0% |
| IAC8 Spreads de commodities com arbitragem física | {'jan': 126, 'z_in': 1.5, 'conj': 'todos'} | 0.13 | 7.3% | 11.4% | -0.33 | 19% | 18% | -4.9 | -5.6 | -5.3 | 0% |
| IAC9 Base: cripto (trimestral e perpétuo) e S&P (SPY x ES) | {'livro': 'perp', 'thr': 0.1} | 6.09 | 14.6% | 13.1% | 2.53 | 98% | 0% | +0.9 | +1.5 | +1.7 | 100% |

### IAC1 Classes de ações e dual-listed EUA/Europa
params {'conj': 'eua+eur+dlc', 'z_in': 2.0, 'k_custo': 5.0} | vol OOS 4.8% | DD OOS -3.8% | DD total -6.9%
| perna | IS pp/a | OOS pp/a |
|---|---|---|
| VOW x VOW3 | -0.16 | -0.56 |
| UA x UAA | +0.14 | -0.44 |
| NWS x NWSA | -0.06 | -0.42 |
| LEN-B x LEN | -0.27 | -0.35 |
| SRT x SRT3 | +0.13 | -0.32 |
| INVE A x B | -0.00 | -0.23 |
| GEF-B x GEF | +0.26 | -0.20 |
| UNA.AS x ULVR.L (dupla listagem) | +0.00 | -0.09 |
| HEN x HEN3 | -0.05 | -0.08 |
| SKF A x B | +0.00 | -0.08 |
| BHP.L x BHP.AX (DLC até jan/22) | -0.19 | -0.07 |
| MAERSK A x B | -0.01 | -0.06 |
| RIO.L x RIO.AX (DLC) | -0.02 | -0.03 |
| BRK-B x BRK-A | +0.18 | -0.03 |
| ATCO A x B | +0.06 | -0.01 |
| SCHN x SCHP | +0.12 | +0.00 |
| UHR x UHRN (Swatch) | -0.10 | +0.00 |
| VOLV A x B | +0.04 | +0.00 |
| ERIC A x B | +0.04 | +0.00 |
| FPE x FPE3 | -0.05 | +0.01 |
| BF-A x BF-B | +0.03 | +0.03 |
| HEI-A x HEI | -0.10 | +0.04 |
| HEIO x HEIA (Heineken Holding) | +0.17 | +0.07 |
| BATRK x BATRA | +0.00 | +0.08 |
| FOX x FOXA | +0.04 | +0.15 |
| LISN x LISP (Lindt) | +0.26 | +0.20 |
| Z x ZG | +0.07 | +0.26 |
| GOOG x GOOGL | -0.14 | +0.32 |
| CARL A x B | +0.12 | +0.32 |
| FWONK x FWONA | +0.13 | +0.56 |
| MOG-B x MOG-A | +0.15 | +0.99 |
negócios: 889 | acerto 62% | dias mediana 16

10 melhores:
| ativo | lado | entrada | saida | dias | retorno | contrib |
|---|---|---|---|---|---|---|
| Z x ZG | vendido | 2016-11-17 | 2016-12-07 | 14 | +4.5% | +1.83 |
| HEIO x HEIA (Heineken Holding) | comprado | 2020-03-13 | 2020-03-18 | 3 | +5.8% | +1.42 |
| HEI-A x HEI | vendido | 2008-10-06 | 2008-10-13 | 5 | +14.3% | +1.25 |
| LEN-B x LEN | comprado | 2012-10-26 | 2012-11-06 | 7 | +5.2% | +1.22 |
| BF-A x BF-B | vendido | 2020-12-16 | 2020-12-29 | 9 | +10.1% | +1.04 |
| VOW x VOW3 | vendido | 2008-09-16 | 2008-09-19 | 3 | +9.7% | +0.98 |
| LEN-B x LEN | vendido | 2018-10-11 | 2018-11-14 | 24 | +3.9% | +0.91 |
| HEI-A x HEI | comprado | 2024-01-18 | 2024-02-14 | 19 | +2.6% | +0.85 |
| BHP.L x BHP.AX (DLC até jan/22) | vendido | 2022-01-21 | 2022-01-31 | 6 | +12.6% | +0.79 |
| Z x ZG | comprado | 2016-12-07 | 2017-02-09 | 46 | +2.1% | +0.79 |

10 piores:
| ativo | lado | entrada | saida | dias | retorno | contrib |
|---|---|---|---|---|---|---|
| LEN-B x LEN | comprado | 2020-03-13 | 2020-03-18 | 3 | -7.3% | -3.15 |
| NWS x NWSA | vendido | 2024-10-23 | 2025-03-25 | 109 | -5.2% | -2.79 |
| HEI-A x HEI | vendido | 2012-02-13 | 2012-05-24 | 73 | -9.8% | -2.00 |
| VOW x VOW3 | vendido | 2008-01-21 | 2008-07-07 | 120 | -16.2% | -1.96 |
| VOW x VOW3 | vendido | 2020-03-11 | 2020-03-17 | 4 | -7.9% | -1.95 |
| SRT x SRT3 | vendido | 2021-06-01 | 2021-09-29 | 86 | -20.8% | -1.74 |
| GOOG x GOOGL | comprado | 2015-03-26 | 2015-09-10 | 120 | -2.8% | -1.57 |
| UA x UAA | comprado | 2024-09-17 | 2025-01-29 | 96 | -6.1% | -1.50 |
| LEN-B x LEN | vendido | 2020-08-11 | 2020-11-25 | 76 | -4.4% | -1.49 |
| HEI-A x HEI | comprado | 2011-09-14 | 2011-10-06 | 16 | -5.6% | -1.39 |

excesso por ano (pp, soma): 2008: +5.0, 2009: -1.8, 2010: +1.7, 2011: +0.1, 2012: +1.4, 2013: -1.0, 2014: -0.3, 2015: -1.9, 2016: +3.9, 2017: -0.9, 2018: +5.5, 2019: +0.5, 2020: -2.2, 2021: +1.0, 2022: -1.1, 2023: -1.0, 2024: +0.7, 2025: +0.0, 2026: +0.8

### IAC2 Ásia: preferenciais coreanas e prêmio A/H
params {'conj': 'coreia+ah', 'neutro': 1, 'lado_ah': 'sem_vender_A'} | vol OOS 3.8% | DD OOS -8.6% | DD total -10.2%
| perna | IS pp/a | OOS pp/a |
|---|---|---|
| Hyundai Motor pref x ord | +0.37 | -0.66 |
| Hyundai Motor 2pref x ord | +0.34 | -0.54 |
| Amorepacific pref x ord | +0.07 | -0.44 |
| Samsung SDI pref x ord | -0.09 | -0.33 |
| Samsung Elec pref x ord | -0.07 | -0.28 |
| LG H&H pref x ord | +0.32 | -0.22 |
| LG Chem pref x ord | +0.18 | -0.19 |
| AH Jiangxi Copper | +0.09 | -0.18 |
| AH Chalco | +0.06 | -0.16 |
| AH CRRC | +0.01 | -0.15 |
| AH GreatWall | +0.02 | -0.15 |
| AH ABC | +0.07 | -0.13 |
| AH CREC | -0.10 | -0.12 |
| AH ICBC | -0.18 | -0.09 |
| AH Minsheng | -0.09 | -0.09 |
| AH Shenhua | +0.05 | -0.08 |
| AH CITICSec | +0.14 | -0.02 |
| AH Weichai | +0.06 | -0.01 |
| AH AirChina | +0.05 | +0.01 |
| AH ChinaShenhuaCoal | +0.01 | +0.03 |
| LG Corp pref x ord | +0.18 | +0.04 |
| Samsung Fire pref x ord | +0.22 | +0.07 |
| AH ChinaLife | +0.12 | +0.08 |
| AH CRCC | -0.02 | +0.09 |
| AH CPIC | +0.07 | +0.10 |
| LG Elec pref x ord | +0.14 | +0.12 |
| AH Vanke | +0.09 | +0.13 |
| AH BoCom | +0.16 | +0.14 |
| AH CCB | +0.09 | +0.17 |
| AH CMB | -0.01 | +0.19 |
| AH PingAn | +0.00 | +0.22 |
| AH PetroChina | +0.04 | +0.22 |
| AH Conch | +0.18 | +0.23 |
| Samsung EM pref x ord | +0.02 | +0.24 |
| AH BOC | +0.17 | +0.24 |
| AH Zijin | +0.06 | +0.28 |
| AH Sinopec | -0.17 | +0.30 |
negócios: 861 | acerto 71% | dias mediana 34

10 melhores:
| ativo | lado | entrada | saida | dias | retorno | contrib |
|---|---|---|---|---|---|---|
| LG H&H pref x ord | vendido | 2018-09-11 | 2018-12-19 | 71 | +22.6% | +1.27 |
| Amorepacific pref x ord | comprado | 2013-05-15 | 2013-06-05 | 15 | +21.6% | +1.10 |
| AH Conch | vendido | 2008-10-10 | 2008-12-01 | 36 | +54.2% | +1.01 |
| Hyundai Motor 2pref x ord | comprado | 2008-09-10 | 2008-10-22 | 30 | +15.1% | +1.00 |
| Samsung EM pref x ord | vendido | 2008-09-02 | 2008-10-23 | 37 | +15.4% | +0.95 |
| Samsung EM pref x ord | comprado | 2021-09-29 | 2021-11-01 | 23 | +10.8% | +0.88 |
| Samsung Fire pref x ord | comprado | 2008-06-06 | 2008-07-08 | 22 | +17.1% | +0.87 |
| AH Vanke | vendido | 2016-07-06 | 2016-08-16 | 29 | +21.2% | +0.77 |
| AH CCB | vendido | 2008-09-18 | 2008-10-08 | 14 | +13.0% | +0.76 |
| LG Corp pref x ord | vendido | 2008-09-02 | 2008-09-29 | 19 | +12.3% | +0.75 |

10 piores:
| ativo | lado | entrada | saida | dias | retorno | contrib |
|---|---|---|---|---|---|---|
| Hyundai Motor pref x ord | comprado | 2025-12-11 | 2026-05-28 | 120 | -26.8% | -3.20 |
| Hyundai Motor 2pref x ord | comprado | 2026-01-08 | 2026-06-25 | 120 | -21.6% | -2.25 |
| AH ICBC | vendido | 2014-12-04 | 2015-05-21 | 120 | -21.4% | -1.95 |
| Samsung SDI pref x ord | comprado | 2021-07-22 | 2022-01-06 | 120 | -14.5% | -1.87 |
| Amorepacific pref x ord | comprado | 2019-11-29 | 2020-05-15 | 120 | -21.6% | -1.79 |
| Samsung EM pref x ord | vendido | 2010-04-26 | 2010-05-17 | 15 | -19.1% | -1.76 |
| Amorepacific pref x ord | vendido | 2026-01-12 | 2026-06-29 | 120 | -16.8% | -1.59 |
| Samsung Elec pref x ord | comprado | 2013-04-04 | 2013-05-22 | 34 | -13.9% | -1.57 |
| AH Jiangxi Copper | vendido | 2025-07-04 | 2025-10-09 | 69 | -20.6% | -1.36 |
| AH CRRC | vendido | 2014-10-10 | 2015-01-01 | 59 | -26.5% | -1.35 |

excesso por ano (pp, soma): 2008: +12.2, 2009: +5.3, 2010: +0.7, 2011: -2.6, 2012: +1.2, 2013: +0.1, 2014: +1.6, 2015: +9.6, 2016: +0.2, 2017: +7.4, 2018: +4.6, 2019: +0.4, 2020: -6.1, 2021: +3.1, 2022: +4.5, 2023: -3.1, 2024: +2.4, 2025: -1.0, 2026: -11.3

### IAC3 Descontos de holdings
params {'jan': 252, 'z_in': 2.5, 'lado': 'desconto'} | vol OOS 4.7% | DD OOS -6.2% | DD total -14.8%
| perna | IS pp/a | OOS pp/a |
|---|---|---|
| Heineken Holding x Heineken | -0.11 | -0.36 |
| Exor x Ferrari/Stellantis/Philips | +0.00 | -0.15 |
| Industrivarden x carteira | +0.41 | -0.14 |
| Porsche SE x VW pref | +0.29 | +0.00 |
| Prosus x Tencent | +0.06 | +0.04 |
| Dior x LVMH | -0.57 | +0.05 |
| SoftBank x BABA/TMUS/ARM/SB Corp | +0.13 | +0.09 |
| Wendel x Bureau Veritas | +0.22 | +0.12 |
| Investor AB x carteira | +0.17 | +0.15 |
| Jardine Matheson x HK Land/JC&C | +0.11 | +0.23 |
| GBL x carteira | -0.52 | +0.53 |
| Naspers x Tencent | -0.15 | +0.56 |
negócios: 127 | acerto 61% | dias mediana 70

10 melhores:
| ativo | lado | entrada | saida | dias | retorno | contrib |
|---|---|---|---|---|---|---|
| Porsche SE x VW pref | comprado | 2009-08-11 | 2009-08-17 | 4 | +14.5% | +3.36 |
| GBL x carteira | comprado | 2021-02-19 | 2021-03-26 | 25 | +9.6% | +2.72 |
| Wendel x Bureau Veritas | comprado | 2025-11-06 | 2025-12-15 | 27 | +13.4% | +2.66 |
| Wendel x Bureau Veritas | comprado | 2010-08-31 | 2010-11-11 | 52 | +25.9% | +2.41 |
| Industrivarden x carteira | comprado | 2008-09-19 | 2008-10-14 | 17 | +18.4% | +2.31 |
| Porsche SE x VW pref | comprado | 2015-09-23 | 2015-11-10 | 34 | +7.6% | +1.92 |
| SoftBank x BABA/TMUS/ARM/SB Corp | comprado | 2020-03-19 | 2020-05-04 | 32 | +30.0% | +1.86 |
| Jardine Matheson x HK Land/JC&C | comprado | 2015-12-16 | 2016-01-18 | 23 | +13.8% | +1.70 |
| Wendel x Bureau Veritas | comprado | 2011-09-07 | 2012-01-20 | 97 | +22.9% | +1.69 |
| Wendel x Bureau Veritas | comprado | 2008-09-17 | 2008-10-31 | 32 | +27.1% | +1.69 |

10 piores:
| ativo | lado | entrada | saida | dias | retorno | contrib |
|---|---|---|---|---|---|---|
| Wendel x Bureau Veritas | comprado | 2020-03-05 | 2020-03-12 | 5 | -14.7% | -4.35 |
| Dior x LVMH | comprado | 2020-03-02 | 2020-03-13 | 9 | -9.3% | -4.24 |
| GBL x carteira | comprado | 2010-04-02 | 2010-09-17 | 120 | -12.6% | -3.66 |
| Heineken Holding x Heineken | comprado | 2021-11-29 | 2022-05-16 | 120 | -5.5% | -3.47 |
| SoftBank x BABA/TMUS/ARM/SB Corp | comprado | 2008-10-01 | 2008-10-28 | 19 | -34.2% | -2.82 |
| Industrivarden x carteira | comprado | 2018-03-26 | 2018-09-10 | 120 | -6.9% | -2.15 |
| Porsche SE x VW pref | comprado | 2020-03-04 | 2020-03-13 | 7 | -5.9% | -2.12 |
| Jardine Matheson x HK Land/JC&C | comprado | 2015-06-23 | 2015-12-08 | 120 | -11.2% | -2.03 |
| GBL x carteira | comprado | 2011-06-03 | 2011-11-18 | 120 | -6.8% | -2.00 |
| SoftBank x BABA/TMUS/ARM/SB Corp | comprado | 2015-09-16 | 2016-01-22 | 92 | -18.9% | -1.94 |

excesso por ano (pp, soma): 2008: +0.6, 2009: +6.5, 2010: -0.3, 2011: +0.8, 2012: +4.7, 2013: +2.2, 2014: +1.1, 2015: +1.1, 2016: +1.2, 2017: -1.5, 2018: -3.8, 2019: -0.8, 2020: -11.4, 2021: +1.1, 2022: -2.9, 2023: +0.3, 2024: +1.7, 2025: +6.9, 2026: -0.6

### IAC4 Prêmio de vol com hedge de beta (CBOE + variância EUA/Europa)
params {'estrutura': 'VS_EUA', 'filtro': 'sempre'} | vol OOS 12.1% | DD OOS -18.8% | DD total -27.2%
| perna | IS pp/a | OOS pp/a |
|---|---|---|
| VS_EUA | +2.75 | +8.46 |

excesso por ano (pp, soma): 2008: -16.3, 2009: +20.5, 2010: +17.2, 2011: +3.5, 2012: +19.3, 2013: +3.6, 2014: +4.0, 2015: -11.0, 2016: +4.9, 2017: +11.2, 2018: -20.0, 2019: -1.9, 2020: +0.8, 2021: +16.1, 2022: +14.5, 2023: +17.7, 2024: +0.1, 2025: -12.6, 2026: +13.0

### IAC5 Futuros de VIX vendidos (roll do contango)
params {'perna': 'VIXM', 'filtro': 'vvix', 'hedge': 0} | vol OOS 5.5% | DD OOS -6.8% | DD total -7.7%
| perna | IS pp/a | OOS pp/a |
|---|---|---|
| VIXM | +4.35 | +0.21 |
negócios: 196 | acerto 44% | dias mediana 4

10 melhores:
| ativo | lado | entrada | saida | dias | retorno | contrib |
|---|---|---|---|---|---|---|
| VIXM | comprado | 2012-07-27 | 2012-12-31 | 111 | +43.0% | +9.30 |
| VIXM | comprado | 2022-10-17 | 2023-03-13 | 105 | +24.9% | +5.85 |
| VIXM | comprado | 2011-11-28 | 2012-02-10 | 54 | +24.7% | +5.72 |
| VIXM | comprado | 2014-04-15 | 2014-07-18 | 68 | +24.0% | +5.48 |
| VIXM | comprado | 2013-01-01 | 2013-02-26 | 40 | +22.3% | +5.19 |
| VIXM | comprado | 2023-10-31 | 2024-04-15 | 119 | +18.7% | +4.51 |
| VIXM | comprado | 2016-11-10 | 2017-02-09 | 65 | +18.3% | +4.28 |
| VIXM | comprado | 2018-04-12 | 2018-05-30 | 34 | +15.4% | +3.67 |
| VIXM | comprado | 2015-02-13 | 2015-06-30 | 97 | +14.3% | +3.53 |
| VIXM | comprado | 2016-02-15 | 2016-06-14 | 86 | +13.3% | +3.47 |

10 piores:
| ativo | lado | entrada | saida | dias | retorno | contrib |
|---|---|---|---|---|---|---|
| VIXM | comprado | 2018-08-17 | 2018-10-11 | 39 | -13.4% | -3.45 |
| VIXM | comprado | 2011-10-28 | 2011-11-01 | 2 | -12.5% | -3.25 |
| VIXM | comprado | 2024-11-07 | 2024-12-19 | 30 | -11.9% | -3.07 |
| VIXM | comprado | 2025-04-02 | 2025-04-03 | 1 | -11.0% | -2.77 |
| VIXM | comprado | 2024-09-02 | 2024-09-04 | 2 | -9.6% | -2.45 |
| VIXM | comprado | 2020-11-05 | 2021-01-28 | 60 | -8.2% | -1.92 |
| VIXM | comprado | 2016-01-06 | 2016-01-08 | 2 | -7.2% | -1.84 |
| VIXM | comprado | 2015-09-17 | 2015-09-18 | 1 | -7.3% | -1.84 |
| VIXM | comprado | 2022-02-09 | 2022-02-11 | 2 | -7.1% | -1.82 |
| VIXM | comprado | 2018-11-08 | 2018-11-13 | 3 | -6.7% | -1.72 |

excesso por ano (pp, soma): 2011: -0.3, 2012: +12.4, 2013: +11.5, 2014: +4.0, 2015: +4.0, 2016: +3.2, 2017: +10.3, 2018: +0.1, 2019: -0.6, 2020: -3.0, 2021: -1.4, 2022: -6.7, 2023: +12.4, 2024: -5.7, 2025: -2.3, 2026: +4.9

### IAC6 Energia: refinadoras, petroleiras, aéreas e carvão vs commodity
params {'jan': 126, 'filtro': 'nenhum', 'modo': 'momentum'} | vol OOS 13.0% | DD OOS -21.2% | DD total -28.1%
| perna | IS pp/a | OOS pp/a |
|---|---|---|
| COP x Brent | -0.24 | -1.63 |
| DAL x diesel/QAV | -0.16 | -1.29 |
| EQNR x Brent | -0.31 | -1.14 |
| CVX x Brent | -0.31 | -0.99 |
| PBR x Brent | +0.65 | -0.94 |
| SHEL x Brent | +0.16 | -0.89 |
| YAL.AX x carvão | +0.38 | -0.86 |
| XOM x Brent | +0.89 | -0.72 |
| WHC.AX x carvão | +0.23 | -0.69 |
| TTE x Brent | -0.18 | -0.61 |
| BP x Brent | -0.19 | -0.57 |
| LUV x diesel/QAV | +0.94 | -0.43 |
| AAL x diesel/QAV | +0.66 | -0.39 |
| PBF x crack | +0.32 | -0.20 |
| PSX x crack | +0.46 | -0.03 |
| UAL x diesel/QAV | +0.81 | -0.02 |
| MPC x crack | +0.02 | -0.01 |
| AF.PA x diesel/QAV | +0.60 | +0.01 |
| DINO x crack | +0.42 | +0.04 |
| NHC.AX x carvão | +0.09 | +0.19 |
| VLO x crack | +0.51 | +0.22 |
| DK x crack | +0.73 | +0.24 |
| BTU x carvão | +0.45 | +0.25 |
| RYAAY x diesel/QAV | -0.47 | +0.29 |
| LHA.DE x diesel/QAV | +0.23 | +0.43 |
| AMR x carvão | +0.00 | +1.78 |
negócios: 816 | acerto 36% | dias mediana 70

10 melhores:
| ativo | lado | entrada | saida | dias | retorno | contrib |
|---|---|---|---|---|---|---|
| UAL x diesel/QAV | vendido | 2019-12-09 | 2020-05-25 | 120 | +123.5% | +13.17 |
| AAL x diesel/QAV | vendido | 2020-01-13 | 2020-06-29 | 120 | +97.9% | +7.13 |
| SHEL x Brent | vendido | 2020-02-03 | 2020-03-16 | 30 | +40.3% | +5.94 |
| YAL.AX x carvão | vendido | 2014-11-03 | 2015-04-20 | 120 | +198.0% | +5.72 |
| PSX x crack | vendido | 2020-01-20 | 2020-07-06 | 120 | +53.5% | +5.24 |
| BTU x carvão | vendido | 2019-05-27 | 2019-11-11 | 120 | +116.2% | +4.86 |
| PBR x Brent | comprado | 2008-09-22 | 2009-03-09 | 120 | +184.2% | +4.65 |
| DK x crack | vendido | 2015-08-24 | 2016-02-08 | 120 | +86.9% | +4.50 |
| LUV x diesel/QAV | comprado | 2013-10-21 | 2014-04-07 | 120 | +36.9% | +4.49 |
| LUV x diesel/QAV | vendido | 2019-12-16 | 2020-06-01 | 120 | +36.3% | +4.49 |

10 piores:
| ativo | lado | entrada | saida | dias | retorno | contrib |
|---|---|---|---|---|---|---|
| TTE x Brent | comprado | 2022-01-17 | 2022-02-28 | 30 | -19.3% | -2.30 |
| AAL x diesel/QAV | vendido | 2014-10-13 | 2014-10-27 | 10 | -25.5% | -1.79 |
| BP x Brent | vendido | 2013-08-05 | 2013-11-04 | 65 | -10.5% | -1.75 |
| WHC.AX x carvão | comprado | 2014-08-25 | 2014-10-13 | 35 | -21.3% | -1.73 |
| DAL x diesel/QAV | vendido | 2022-03-07 | 2022-04-18 | 30 | -27.4% | -1.67 |
| PSX x crack | comprado | 2019-10-28 | 2019-12-30 | 45 | -11.8% | -1.66 |
| SHEL x Brent | vendido | 2018-03-19 | 2018-04-09 | 15 | -8.9% | -1.58 |
| DK x crack | vendido | 2011-01-10 | 2011-01-31 | 15 | -17.3% | -1.57 |
| WHC.AX x carvão | comprado | 2024-07-08 | 2024-08-05 | 20 | -22.7% | -1.56 |
| UAL x diesel/QAV | vendido | 2016-01-18 | 2016-02-29 | 30 | -18.9% | -1.54 |

excesso por ano (pp, soma): 2008: +4.4, 2009: +2.7, 2010: +0.5, 2011: +4.4, 2012: -11.1, 2013: +15.5, 2014: -2.6, 2015: -6.1, 2016: +7.7, 2017: +0.3, 2018: -6.9, 2019: -4.3, 2020: +82.5, 2021: -18.3, 2022: +6.1, 2023: -8.4, 2024: -8.3, 2025: -29.7, 2026: +12.9

### IAC7 Metais, urânio, aço, fertilizantes e proteína vs commodity
params {'jan': 126, 'filtro': 'nenhum', 'modo': 'momentum'} | vol OOS 12.4% | DD OOS -11.1% | DD total -18.7%
| perna | IS pp/a | OOS pp/a |
|---|---|---|
| PPC x milho | +0.29 | -0.72 |
| AEM x ouro | -0.21 | -0.72 |
| AAL.L x cobre | +0.00 | -0.65 |
| EVN.AX x ouro | -0.07 | -0.44 |
| FMG.AX x minério | -0.07 | -0.44 |
| DNN x urânio físico | -0.12 | -0.43 |
| NXE x urânio físico | +0.15 | -0.38 |
| TSN x boi | +0.63 | -0.34 |
| RIO x minério | -0.22 | -0.33 |
| CLF x HRC | +0.49 | -0.22 |
| NST.AX x ouro | +0.25 | -0.19 |
| YAR.OL x milho | -0.39 | -0.17 |
| KGC x ouro | +0.83 | -0.15 |
| HRL x porco | +0.05 | -0.15 |
| NEM x ouro | +0.17 | -0.11 |
| STLD x HRC | -0.22 | -0.07 |
| ANTO.L x cobre | -0.50 | +0.01 |
| CCJ x urânio físico | +0.11 | +0.08 |
| UEC x urânio físico | -0.12 | +0.10 |
| TECK x cobre | +0.34 | +0.11 |
| GOLD x ouro | -0.08 | +0.22 |
| CF x milho | -0.53 | +0.25 |
| S32.AX x alumínio | -0.04 | +0.28 |
| MOS x milho | +0.90 | +0.28 |
| BHP x minério | +0.57 | +0.31 |
| MT x HRC | +1.09 | +0.46 |
| NTR x milho | -0.16 | +0.48 |
| GLEN.L x cobre | +0.25 | +0.51 |
| SCCO x cobre | -0.10 | +0.54 |
| NUE x HRC | +0.21 | +0.58 |
| FCX x cobre | -0.01 | +0.65 |
| VALE x minério | +0.01 | +1.28 |
negócios: 938 | acerto 38% | dias mediana 75

10 melhores:
| ativo | lado | entrada | saida | dias | retorno | contrib |
|---|---|---|---|---|---|---|
| VALE x minério | comprado | 2025-11-03 | 2026-04-20 | 120 | +53.4% | +4.60 |
| FCX x cobre | vendido | 2014-09-08 | 2015-02-23 | 120 | +47.9% | +4.50 |
| EVN.AX x ouro | vendido | 2013-01-21 | 2013-07-08 | 120 | +120.3% | +4.40 |
| NUE x HRC | comprado | 2021-03-01 | 2021-08-16 | 120 | +78.3% | +4.03 |
| MOS x milho | vendido | 2019-03-11 | 2019-08-26 | 120 | +70.8% | +3.69 |
| HRL x porco | comprado | 2015-08-10 | 2016-01-25 | 120 | +33.2% | +3.67 |
| MOS x milho | vendido | 2013-04-15 | 2013-09-30 | 120 | +39.1% | +3.40 |
| HRL x porco | comprado | 2012-11-19 | 2013-05-06 | 120 | +22.1% | +3.39 |
| ANTO.L x cobre | vendido | 2013-01-21 | 2013-07-08 | 120 | +45.6% | +3.36 |
| MT x HRC | vendido | 2011-05-16 | 2011-10-31 | 120 | +34.8% | +3.32 |

10 piores:
| ativo | lado | entrada | saida | dias | retorno | contrib |
|---|---|---|---|---|---|---|
| VALE x minério | comprado | 2011-04-25 | 2011-05-02 | 5 | -4.7% | -3.61 |
| PPC x milho | vendido | 2021-07-19 | 2021-08-16 | 20 | -26.1% | -2.47 |
| VALE x minério | vendido | 2016-01-25 | 2016-03-07 | 30 | -48.2% | -1.89 |
| AEM x ouro | comprado | 2018-07-02 | 2018-08-20 | 35 | -16.6% | -1.76 |
| NTR x milho | vendido | 2018-07-23 | 2018-10-08 | 55 | -9.3% | -1.75 |
| NEM x ouro | comprado | 2025-07-28 | 2025-10-27 | 65 | -20.2% | -1.68 |
| RIO x minério | vendido | 2024-07-22 | 2024-09-30 | 50 | -14.0% | -1.56 |
| HRL x porco | comprado | 2017-12-04 | 2018-02-05 | 45 | -15.1% | -1.51 |
| RIO x minério | vendido | 2020-02-10 | 2020-03-16 | 25 | -12.3% | -1.47 |
| RIO x minério | comprado | 2016-11-14 | 2017-01-09 | 40 | -18.1% | -1.44 |

excesso por ano (pp, soma): 2008: -3.0, 2009: -2.1, 2010: -4.8, 2011: +11.2, 2012: -5.0, 2013: +35.5, 2014: +3.9, 2015: +22.7, 2016: -6.4, 2017: -5.5, 2018: -11.4, 2019: +6.9, 2020: +3.2, 2021: -1.7, 2022: +5.2, 2023: -7.3, 2024: -0.9, 2025: -0.0, 2026: +8.3

### IAC8 Spreads de commodities com arbitragem física
params {'jan': 126, 'z_in': 1.5, 'conj': 'todos'} | vol OOS 10.0% | DD OOS -19.7% | DD total -28.6%
| perna | IS pp/a | OOS pp/a |
|---|---|---|
| Brent x WTI | -0.53 | -1.24 |
| platina x paládio | +0.71 | -0.94 |
| boi gordo x bezerro | -0.82 | -0.92 |
| prata x ouro | -0.07 | -0.45 |
| porco x milho | -0.23 | -0.36 |
| crush soja | -0.27 | -0.34 |
| diesel x gasolina | -1.36 | -0.23 |
| trigo KC x Chicago | +0.78 | -0.06 |
| trigo x milho | +1.53 | -0.03 |
| café x açúcar | +0.48 | +0.07 |
| soja x milho | +0.33 | +0.18 |
| UNG vendido (inverno) | +1.11 | +0.34 |
| crack 3:2:1 | +0.25 | +1.29 |
negócios: 592 | acerto 64% | dias mediana 60

10 melhores:
| ativo | lado | entrada | saida | dias | retorno | contrib |
|---|---|---|---|---|---|---|
| UNG vendido (inverno) | comprado | 2015-10-02 | 2016-03-02 | 108 | +74.1% | +4.69 |
| UNG vendido (inverno) | comprado | 2011-10-04 | 2012-03-02 | 108 | +67.0% | +4.62 |
| Brent x WTI | comprado | 2008-08-11 | 2008-09-29 | 35 | +10.0% | +4.50 |
| Brent x WTI | comprado | 2020-03-23 | 2020-04-13 | 15 | +19.3% | +4.00 |
| prata x ouro | vendido | 2008-03-03 | 2008-03-24 | 15 | +15.2% | +3.10 |
| UNG vendido (inverno) | comprado | 2022-10-04 | 2023-03-02 | 107 | +98.7% | +2.96 |
| porco x milho | comprado | 2013-12-30 | 2014-03-03 | 45 | +13.6% | +2.80 |
| UNG vendido (inverno) | comprado | 2008-10-02 | 2009-03-03 | 108 | +65.0% | +2.73 |
| crack 3:2:1 | vendido | 2026-03-02 | 2026-04-13 | 30 | +11.6% | +2.67 |
| UNG vendido (inverno) | comprado | 2014-10-02 | 2015-03-03 | 108 | +40.0% | +2.42 |

10 piores:
| ativo | lado | entrada | saida | dias | retorno | contrib |
|---|---|---|---|---|---|---|
| prata x ouro | vendido | 2010-10-11 | 2011-03-28 | 120 | -37.5% | -9.41 |
| diesel x gasolina | comprado | 2020-01-20 | 2020-07-06 | 120 | -34.2% | -7.72 |
| Brent x WTI | comprado | 2014-07-21 | 2015-01-05 | 120 | -20.2% | -7.44 |
| porco x milho | vendido | 2013-05-13 | 2013-10-28 | 120 | -23.8% | -7.06 |
| diesel x gasolina | comprado | 2015-07-20 | 2016-01-04 | 120 | -28.4% | -6.18 |
| soja x milho | vendido | 2020-07-06 | 2020-12-21 | 120 | -18.2% | -5.53 |
| Brent x WTI | vendido | 2026-01-19 | 2026-03-09 | 35 | -8.6% | -4.95 |
| Brent x WTI | vendido | 2010-09-20 | 2011-03-07 | 120 | -15.7% | -4.92 |
| boi gordo x bezerro | vendido | 2013-11-18 | 2014-05-05 | 120 | -10.3% | -4.88 |
| trigo KC x Chicago | vendido | 2010-04-12 | 2010-09-27 | 120 | -8.1% | -4.43 |

excesso por ano (pp, soma): 2008: +16.4, 2009: +13.2, 2010: -16.0, 2011: +2.7, 2012: +9.1, 2013: -8.4, 2014: -3.2, 2015: +10.6, 2016: -1.9, 2017: +11.5, 2018: +2.1, 2019: -3.6, 2020: -7.8, 2021: -10.2, 2022: +0.3, 2023: +4.2, 2024: -1.6, 2025: +1.0, 2026: -9.2

### IAC9 Base: cripto (trimestral e perpétuo) e S&P (SPY x ES)
params {'livro': 'perp', 'thr': 0.1} | vol OOS 0.5% | DD OOS -0.1% | DD total -1.2%
| perna | IS pp/a | OOS pp/a |
|---|---|---|
| perp:BNBUSDT | +1.61 | +0.03 |
| perp:BTCUSDT | +2.94 | +0.24 |
| perp:ETHUSDT | +4.18 | +0.26 |
| perp:XRPUSDT | +3.25 | +0.29 |
| perp:SOLUSDT | +1.60 | +0.30 |
| perp:DOGEUSDT | +1.34 | +0.39 |
negócios: 61 | acerto 77% | dias mediana 44

10 melhores:
| ativo | lado | entrada | saida | dias | retorno | contrib |
|---|---|---|---|---|---|---|
| perp:ETHUSDT | comprado | 2020-03-25 | 2021-05-26 | 427 | +44.9% | +9.35 |
| perp:XRPUSDT | comprado | 2021-01-05 | 2021-05-27 | 142 | +33.4% | +5.48 |
| perp:BTCUSDT | comprado | 2020-11-11 | 2021-06-25 | 226 | +24.3% | +4.46 |
| perp:SOLUSDT | comprado | 2021-01-21 | 2021-05-24 | 123 | +19.3% | +3.25 |
| perp:BNBUSDT | comprado | 2020-11-08 | 2021-02-03 | 87 | +9.9% | +2.54 |
| perp:ETHUSDT | comprado | 2020-01-17 | 2020-03-18 | 61 | +6.0% | +2.24 |
| perp:XRPUSDT | comprado | 2020-10-17 | 2020-12-12 | 56 | +7.9% | +1.94 |
| perp:DOGEUSDT | comprado | 2021-03-10 | 2021-05-23 | 74 | +12.2% | +1.91 |
| perp:BTCUSDT | comprado | 2020-05-02 | 2020-09-21 | 142 | +5.3% | +1.81 |
| perp:BTCUSDT | comprado | 2020-01-16 | 2020-03-15 | 59 | +4.5% | +1.70 |

10 piores:
| ativo | lado | entrada | saida | dias | retorno | contrib |
|---|---|---|---|---|---|---|
| perp:XRPUSDT | comprado | 2020-12-21 | 2020-12-27 | 6 | -0.7% | -0.21 |
| perp:XRPUSDT | comprado | 2021-12-21 | 2021-12-25 | 4 | -0.7% | -0.20 |
| perp:BNBUSDT | comprado | 2021-10-15 | 2021-10-18 | 3 | -0.4% | -0.08 |
| perp:DOGEUSDT | comprado | 2022-03-30 | 2022-05-13 | 44 | +0.2% | -0.07 |
| perp:DOGEUSDT | comprado | 2021-06-05 | 2021-06-24 | 19 | -0.1% | -0.06 |
| perp:BNBUSDT | comprado | 2024-06-07 | 2024-06-13 | 6 | -0.1% | -0.04 |
| perp:BNBUSDT | comprado | 2021-10-28 | 2021-11-08 | 11 | -0.1% | -0.03 |
| perp:SOLUSDT | comprado | 2024-06-08 | 2024-06-25 | 17 | +0.1% | -0.03 |
| perp:XRPUSDT | comprado | 2024-06-05 | 2024-07-10 | 35 | +0.3% | -0.02 |
| perp:ETHUSDT | comprado | 2022-04-05 | 2022-04-18 | 13 | +0.0% | -0.02 |

excesso por ano (pp, soma): 2020: +15.1, 2021: +29.5, 2022: +0.0, 2023: +1.2, 2024: +4.5, 2025: -0.0, 2026: +0.0