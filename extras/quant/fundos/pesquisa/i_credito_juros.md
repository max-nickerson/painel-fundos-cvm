# Frente i_credito_juros — crédito e juros do Brasil replicados lá fora (fase 2, out/2026)

Código: `quant/fundos/ideias_i_credito_juros.py` (`python ideias_i_credito_juros.py dados` baixa com cache; sem argumento roda tudo).
Resultado: `resultado/ideias_i_credito_juros.pkl` (lista de dicts do `roda` + `contrib` diário por ativo em R$ e `trades`),
saída do console em `resultado/ideias_i_credito_juros_saida.txt`.
Benchmark CDI; fundo = CDI + excesso em USD convertido com hedge cambial (`brl`). IS 2010–2020, OOS 2021-01 → 2026-10
(I7: dados de eurobonds desde 2019, IS 2019-06 → 2022, OOS 2023+).

## Dados novos (`quant/fundos/dados/`)
| arquivo | fonte | conteúdo |
|---|---|---|
| `icj_fred_d.parquet` | FRED | DFII5/7/10/20/30 (TIPS), DGS1–30, DFF, T5YIE, T10YIE, T5YIFR, DTB3 (diário; usado com 1 dia de defasagem, o H.15 sai no dia seguinte) |
| `icj_fred_m.parquet` | FRED | MICH, EXPINF1/5/10YR (Cleveland Fed), IRLTLT01 de 13 países (10 anos, média mensal OECD) |
| `icj_boe_real.parquet` | Banco da Inglaterra (zip `glcrealddata`) | curva real UK (gilts indexados) 5/10/20 anos, diária, 2005+ |
| `icj_cpi.parquet` | BIS `WS_LONG_CPI` | inflação 12m mensal de 26 países (usada com 2 meses de defasagem) |
| `icj_yahoo.parquet` | Yahoo | LTPZ, STIP, SCHP, INXG.L, SJNK, ANGL, FALN, IHYG.L, IEAC.L, EMHY, CEMB, HYEM, PCY, VWOB, IGOV, BWX, ZQ=F, GOVT, VCIT, IHYU.L |

**Não há dado gratuito para:** spreads OAS da ICE/BofA antes de out/2023 (o FRED agora só publica 3 anos: `BAMLH0A0HYM2` etc. começam em
2023-10 — não servem para histórico); títulos soberanos em default/stress (Argentina GD30/AL30, Ucrânia, Egito, Gana, Sri Lanka — não existem
no Yahoo; EGPT/UKRN também não); bonds corporativos individuais dos EUA (a API do FINRA TRACE exige cadastro/credencial — não usamos; a
consulta web é por papel e sem histórico em lote); spread de HY por setor; SPF da Filadélfia (não está no FRED em formato útil); futuros de
Bund/Gilt/JGB. ZQ=F (fed funds) existe só como contínuo do 1º vencimento — não dá a curva esperada.

## Resumo (OOS 2021+ ; I7 2023+)
| fundo | escolhido no IS | OOS a.a. | CDI | IR OOS | P(bater) | PBO | custo x2 / +1 dia (pp) | leitura |
|---|---|---|---|---|---|---|---|---|
| I1 Juro real de valor (TIPS/linkers) | nível 1%, TIP | 9,4% | 11,4% | −0,37 | 11% | 62% | −2,1 / −2,0 | comprou TIPS a 1–1,5% real em set/2022; juro real foi a 2,5% e não voltou |
| I2 Inflação implícita x expectativas | **segue** o gap, z 1,5, Cleveland | **13,9%** | 11,4% | **0,45** | **88%** | **20%** | +2,4 / +2,6 | 1 negócio: comprado em inflação jun/2020→jun/2022 |
| I3 Prêmio do 2a x fed funds | thr 1 pp, sem filtro, recebe | 9,3% | 11,4% | −0,96 | 1% | 38% | −2,2 / −2,2 | recebeu 2 anos em jan/2022 (Fed subiu 425 bps) |
| I4 Inclinação 2s10s pelo ciclo | realizado, 25 bps, ambos | 11,4% | 11,4% | 0,00 | 47% | 58% | −0,1 / −0,1 | sem alfa (igual ao JF4) |
| I5 Crédito HY carry/pânico | pânico, HY global | 10,8% | 11,4% | −0,12 | 37% | 66% | −0,7 / −0,5 | o pânico de 2022 não foi pânico; o carry puro dá +0,8 pp |
| I6 Crédito antecipa ação (vendido) | 1,5%, IWM, 63d | 10,9% | 11,4% | −0,05 | 39% | 17% | −0,6 / −1,3 | IS negativo; lado vendido não paga nos EUA |
| I7 Eurobonds BR em stress (safra) | evento, 40–80 | **15,3%** | 13,1% | 0,31 | 79% | 82% | +2,1 / +2,2 | 2 safras (mar/2020, jul/2022); 100% das variantes > CDI |
| I8 Juros globais relativos | carry, n3, G7 | 6,5% | 11,4% | −0,78 | 3% | 85% | −5,0 / −4,9 | carry de inclinação perdeu 27 pp em 2021-22 |
| I9 Carry realista / real tático EM | real tático EM, sem regime, sem cauda | 12,8% | 11,4% | 0,28 | 76% | 17% | +0,4 / +1,6 | TRY explica tudo; o carry G10+LatAm (não escolhido) fez +7,5 pp OOS |

Resumo honesto: a mesma lição do Brasil. **Previsão de juros (I1, I3, I4, I8) não sobrevive fora da amostra; o que paga é prêmio de risco
(carry de moeda, crédito carregado em stress) e "seguir" o choque de inflação (I2), não apostar contra ele.** Nenhum fundo tem Sharpe
suspeito (o maior IR OOS é 0,45).

---

## I1 — Juro real de valor (TIPS / linkers UK) ↔ JF1
**Tese.** Igual ao JF1 ("IPCA+6,5% numa NTN-B é demais"): juro real de 10 anos muito acima do neutro (r* ~0,5% + prêmio) é prêmio de risco
que volta. Compra duração real e espera.
**Implementação.** Sinal: DFII10 (EUA) e curva real do BoE 10 anos (UK). Regras: nível (EUA 1% / 2%; UK 0% / 1% — linkers RPI têm ~1 pp a
menos pela cunha RPI−CPI, definido ex-ante) com saída 1 pp abaixo; ou percentil de 5 anos (80/90) com saída na mediana. Veículos: TIP (1x PL,
duration ~7), LTPZ (0,35x, duration ~20) ou TIP 0,5 + INXG.L 0,175 (UK, excesso sobre o juro de política BoE = hedge cambial). Custo 3 bps.
**Resultado.** IS +0,2 a +2,2 pp/ano; **OOS negativo em todas as 12 variantes (−0,4 a −2,0)**. Escolhido (nível 1%, TIP): 3 negócios
desde 2005 — comprado jan/2005→ago/2011 (+28,8 pp, o QE derrubou o juro real de 2% para −0,1%), out/2018→ago/2019 (+6,5 pp, o Fed parou
de subir) e **set/2022→hoje (−8,9 pp): DFII10 a 1,0–1,3% em set/2022 foi a 2,5% em out/2023 e ainda está ~1,8–2,0%**. UK: a regra de nível
0% só disparou em out/2022 (crise do LDI/mini-budget, juro real de −2,9% para +0,4% em 10 meses) e o fundo comprou no meio da subida.
**Por quê.** Nos EUA o "neutro" mudou: o r* de 2010-21 (0–0,5%) virou 1,5–2% com déficit de 6% do PIB. É a mesma falha do JF1 com percentil
(âncora móvel) e a mesma da posição aberta de 2024 da NTN-B: carry real de 1,5% contra T-bill de 5% é negativo enquanto o Fed está apertado.
**Tentar.** Âncora = estimativa de r* (Laubach-Williams/HLW, Fed NY, trimestral) + 1 pp; só entrar com a curva real−T-bill positiva (carry
não negativo); UK com nível 1,5%+ (já atingido em 2025-26).

## I2 — Inflação implícita x expectativas ↔ JF2 — o único "previsão" que funcionou, e ao contrário da tese original
**Tese de mesa original:** breakeven 5a muito acima do que pesquisas esperam = prêmio de inflação caro → vender inflação. **Tese
alternativa (lição do JF2):** o gap é informação — o mercado vê o choque antes dos economistas → seguir.
**Implementação.** gap = T5YIE − Cleveland Fed EXPINF5YR (ou Michigan 1a), com 1 mês de defasagem na pesquisa; z de 3 anos. Posição: TIP
contra 0,9 x IEF (razão de durations 7,0/7,7 = DV01-neutro), 1,5x o PL, financiamento 0,25% a.a. sobre o bruto acima de 1. "vende" = só vende
inflação (z > z_in, sai z < 0); "ambos"; "segue" = compra inflação com z > z_in e vende com z < −z_in.
**Resultado.** "vende": IS −0,5 a +0,2, **OOS −1,5 a −3,6 pp em todas** — a tese brasileira de novo reprovada. "segue" com Cleveland: IS +0,6/+0,7,
**OOS +2,4/+2,7 pp**; com Michigan ≈ 0 (Michigan é 1 ano e muito ruidoso). Escolhido no IS: segue, z 1,5, Cleveland: OOS 13,9% vs 11,4%,
IR 0,45, P 88%, PBO 20%, sobrevive a custo x2 e +1 dia.
**Negócios.** Melhor de todos: **comprado em inflação 23/jun/2020 → 02/jun/2022 (breakeven 5a de 1,2% para 3,0%; +25,7 pp no total, +18 pp no
OOS)** — o gap ficou acima do normal porque a pesquisa do Cleveland subia devagar. Outros: vendido ago/2008→mai/2009 (+10,8, o colapso
das commodities), vendido set/2014→mar/2015 (+5,6, petróleo), vendido jul/2015→abr/2016 (+3,4). Piores: vendido mar-mai/2020 (−4,5:
a pesquisa caiu menos que o breakeven, o Fed comprou TIPS), vendido out/2022→nov/2024 (−3,6), comprado fev/2012→jul/2013 (−3,3).
**Cuidado (importante).** TIP − 0,9 x IEF não é breakeven puro: o beta da perna contra o IEF é −0,25 (TIPS reagem só ~70% ao juro
nominal). Em jun/2020→jun/2022 o spread rendeu +16,5%; ~4 pp disso foi duração vendida (IEF −14,8%) e ~12 pp foi o breakeven (+1,76 pp x ~7).
Ou seja, metade do OOS é um evento (2021) e uma parte é o viés vendido em juro num período de alta de juros. **Tentar:** hedge por beta
(h ~0,65) em vez de DV01 nominal; usar o swap de inflação/futuros de CPI se houver; repetir com UK (BoE tem curva de inflação implícita).

## I3 — Prêmio do 2 anos sobre o fed funds ↔ JF3
**Tese.** "O mercado paga demais por proteção": quando o Treasury de 2 anos paga muito acima do fed funds, recebe (2008, 2010…).
**Implementação.** prêmio = DGS2 − DFF; recebe acima de thr (0,5/1 pp), sai abaixo de thr/3; Treasury 2a sintético a partir da taxa (carry
− D·Δy + convexidade; contra o SHY desde 2010: correlação diária 0,91, mensal 0,95, vol 1,40% x 1,34%; o 10a sintético x IEF: 0,95 mensal), 2x o PL, custo de futuro 1 bp. Filtro (lição do JF3, definido no
Brasil, novo para os EUA): não recebe se o breakeven 5a subiu > 25 bps em 3 meses (choque de inflação). "ambos" paga quando o prêmio < −thr.
**Resultado.** IS ~0 a +0,4; OOS −0,5 a −2,5 pp, exceto "thr 1, filtro, ambos" (+0,2). Escolhido (thr 1, sem filtro, recebe): **um negócio
destrói: recebeu 31/jan/2022 com 2a a 1,2% e fed funds 0,08% — o Fed subiu 4,25 pp em 2022: −9,8 pp**. Ganhos: out/2008→ago/2010 (+7,5),
jun/2008 (+1,7). O filtro teria evitado 2022 (breakeven subindo), mas o IS não o escolheu (não havia episódio de inflação em 2010-20).
**Por quê.** Exatamente o JF3: o prêmio é real quando o choque é de risco (2008) e falso quando o BC está atrás da curva (2022, como Brasil 2021/24).
Sem a curva esperada (ZQ só tem 1 vencimento; SOFR futuros não estão no Yahoo) não dá para separar prêmio de expectativa. **Tentar:** a curva
de futuros de SOFR (CME, sem dado grátis histórico) ou as projeções do FOMC (SEP, trimestral) como "Focus" americano.

## I4 — Inclinação 2s10s pelo ciclo do Fed ↔ JF4 — sem alfa
Steepener (comprado 2a, vendido 10a, DV01 de 5 anos por PL) quando o ciclo é de corte (esperado: DGS1−DFF < −thr; realizado: fed funds caiu > thr em
6 meses); flattener no ciclo de alta. IS +0,05 a +0,6, OOS −0,1 a +1,1 (75% das variantes acima do CDI, mas tudo ±1 pp, vol 1–3%). Melhores:
steepener set/2007→set/2008 (+5,2 pp), flattener dez/2016→dez/2017 (+3,6), steepener set/2019→set/2020 (+2,3), steepener set/2024→jun/2025 (+1,3).
Piores: steepener nov/2025→jun/2026 (−0,8), mai/2009 (−1,1). Como no Brasil, a curva já precifica o ciclo; o que sobra é o carry negativo do
steepener no fim do ciclo de alta. Útil como hedge de um livro de crédito (inclina quando o Fed corta em crise), não como fundo.

## I5 — Crédito HY: carry e "comprar o pânico" ↔ C3 (carry), C8 (pânico) e índice EW
**Tese.** O prêmio de crédito existe (no Brasil o índice EW hedgeado deu +2,3 pp/ano com 2,4% de vol). Lá fora: carregar HY com hedge de
Treasury; ou só comprar quando o crédito despenca (mar/2020, 2022, 2015-16, 2011).
**Implementação.** Retorno de crédito "sem juro" = ETF − beta móvel (126d, defasado, limitado a 0–1) x IEF (perna em futuro). Universos: HY EUA (HYG,
JNK), HY global (+IHYG.L em euro com hedge, +EMHY), fallen angels (ANGL). Modos: carry (sempre, peso igual, mensal), carry com filtro de faca
(sai se o índice hedgeado caiu em 63d), pânico (índice hedgeado > 6% abaixo do máximo de 1 ano; sai em −1% ou 1 ano), pânico + 50% carry.
Custo 7,5 bps + 1 bp do futuro.
**Referência por ETF (hedgeado, excesso a.a. em USD; não é fundo):**

| ETF | IS 2010-20 | OOS 2021+ | vol | pior queda |
|---|---|---|---|---|
| HYG / JNK | +5,3 / +5,4 | +0,8 / +0,7 | 8,0 | −22% |
| SJNK (HY curto) | +3,6 | **+1,7** | 5,7 | −20% |
| BKLN (loans) | +2,2 | +1,6 | 5,8 | −24% |
| ANGL / FALN (fallen angels) | +7,8 / +8,3 | +0,7 / +1,2 | 8,9 | −29% |
| IHYG.L (HY euro) | +3,5 | +0,5 | 6,5 | −26% |
| EMHY / HYEM / EMB / CEMB / PCY | +3,6 a +5,4 | −0,4 a +1,2 | 7–10 | −22 a −34% |
| LQD / VCIT / IEAC.L (IG) | +3,2 / +2,9 / +1,8 | +0,5 / +0,7 / −0,9 | 3,6–5,3 | −15 a −22% |

ANGL − HYG (prêmio de fallen angel sobre o HY): +3,1 pp/ano IS, **−0,1 OOS** — a venda forçada dos rebaixados foi arbitrada depois que o
efeito virou produto (ANGL/FALN têm US$ 5+ bi).
**Resultado do fundo.** Carry: IS +4,9 a +6,1, OOS +0,8/+0,9 (IR OOS ~0,1). Filtro de faca: **piora em todas as 3 comparações (OOS −1,1 a −2,7)** —
idêntico ao C3 brasileiro (sair quando o spread abre realiza no fundo). Pânico: IS +2,1 a +4,6, OOS −0,9 a +0,5. Escolhido (pânico, HY global):
OOS −0,6 pp/ano vs CDI.
**Negócios (pânico).** Melhores: HYG jul/2007→set/2007 (+10,6 pp), JNK fev-mar/2010, EMHY mar/2020→nov/2020 (+2,8), HYG/JNK ago/2011→jan/2012 (+2,8
cada), EMHY set/2015→jun/2016 (+2,6, petróleo/China). Piores: **JNK/HYG nov/2007→nov/2008 (−23,7 e −15,2 pp: comprou −6% e o crédito caiu mais 30%;
prazo de 1 ano saiu no fundo)** — pré-2010, fora da conta do motor, mas é o risco de cauda da regra; e mar/2022→mar/2023 (−1,8 pp no total: a
queda de 2022 foi juro e não default, o hedge por beta deixou resíduo).
**O que levar.** O prêmio de crédito lá fora existe mas é pequeno depois de 2021 (spread HY em 3–3,5%): +0,7 a +1,7 pp/ano hedgeado. SJNK/BKLN
(curto/flutuante) têm o melhor carry por risco no OOS. O "comprar o pânico" só funciona em pânico de verdade (2008 só depois de nov/2008; 2020);
uma regra de 6% compra cedo demais em crise de default e compra choque de juros em 2022. **Tentar:** gatilho por spread (OAS) quando houver
série longa — o FRED cortou; reconstruir o spread do HYG pelo yield-to-worst do iShares (o site publica histórico mensal); exigir VIX em
backwardation que já começou a normalizar (comprar a segunda perna do pânico, não a primeira).

## I6 — Crédito antecipa ação (só vendido) ↔ C6
**Tese.** No Brasil, a debênture abrindo spread com a ação parada antecipou Ambipar/Alliança/Viveo (só o lado vendido). Nos EUA, sem dado por
emissor, versão agregada: índice HY hedgeado caiu > x em 21 dias e a ação (IWM ou SPY) ainda não (> −2%) → vende 50% do PL por h dias (aluguel 0,5%).
**Resultado.** IS negativo em todas as 8 (−1,2 a −4,5 pp/ano); OOS −1,5 a +0,5. Escolhido (1,5%, IWM, 63d): OOS −0,5 pp vs CDI, P 39%.
Melhores: IWM vendido jun/2008→mar/2009 (+20 pp), jun→set/2011 (+9,0, rebaixamento dos EUA), jun→out/2015 (+6,7, energia), fev→dez/2022 (+2,2).
Piores: mai→out/2020 (−10,6: o crédito tinha caído no Covid, a bolsa subiu com o Fed), nov/2011→mar/2012 (−7,9), jun/2013 (taper, −4,8),
ago/2024 (−3,6: o susto do carry de iene).
**Por quê.** No agregado o sinal é "o crédito caiu"; com o Fed comprando crédito (2020) ou em choques de juro (2013, 2022) a bolsa não segue.
O C6 funcionava por ser **por empresa** (o credor vê a dívida curta de uma companhia específica). Sem TRACE por emissor, não replicável.
**Tentar:** a versão por empresa com preços de bonds via FINRA (cadastro gratuito, não usado aqui por exigir credencial) ou com CDS
(sem fonte gratuita); proxy setorial: energia 2015 (HY de energia era 15% do índice) — não há ETF de HY setorial com histórico.

## I7 — Eurobonds BR em stress (safra, compra-e-segura) ↔ atribuição 06 / A2
**Tese.** No stress sistêmico o mercado vende a 60–80 empresas que não quebram; compra a safra com hedge de câmbio e Treasury e carrega até o par.
**Implementação.** Dados da atribuição (`af.eb_insumos()`: preços FINRA, excesso diário em R$ já com hedge de DOL e Treasury, 2019+). Gatilho:
spread mediano dos corporativos (preço 50–110) abriu > 75 bps em 3 meses ou acima do percentil 80 desde 2019 (mensal, vale a partir do mês
seguinte); compra nos 6 meses seguintes. "sempre" = sem gatilho. Entrada com preço entre lo (40/60) e hi (80/85), 1 por emissor, até 10 de 1/10 do PL,
custo 25 bps/lado. **Diferença para o A2:** compra-e-segura — não vende quando o FINRA fica sem negócio (o A2 vendia por "sumiu" em 53 de 64
negócios, irreal), marca no último preço por até 21 dias; sai em 97, em 2 anos ou após 3 meses sem preço.
**Resultado.** IS +7,8 a +9,5 pp/ano; OOS +1,7 a +6,5; **100% das variantes acima do CDI no OOS**, custo x2 e +1 dia ok. Escolhido (evento, 40–80):
OOS 15,3% vs 13,1%, IR 0,31. PBO 82% porque as variantes são quase iguais (lo 40 ≡ 60: não havia bond entre 40 e 60 nas janelas).
Gatilhos: mar/2020→jul/2020 (Covid) e jul/2022 (spread 4,07% em jun/2022). **A safra de 2023 (Americanas) não disparou o gatilho** (spread
mediano +68 bps em 3 meses) — foi stress de nomes, não sistêmico; o modo "sempre" a pegou (OOS +6,5 com hi 85).
**Negócios (21, todos com contribuição positiva).** Covid: Petrobras 2115 a 74 (abr/2020) → 98 em 30 dias (+3,6 pp), BRF a 70,4 (mar/2020) → 98,8
(+3,5), Ultrapar a 70 → 97 em 22 dias (+3,2), Vale 78 → 99 em 5 dias, Gerdau, Raízen, Rede D'Or, AXIA. Jul/2022 (carregados 2 anos): BRF 2050
a 79 → 91 (+2,7), Globo 78,8 → 88,6 (+2,3), Simpar 77,7 → 83 (+2,1), Petrobras (+2,1), MC/Acelen, Hidrovias, Movida, Rumo, Klabin; pior:
Braskem 79,4 → 74,6 (ainda +0,7 pp com o carrego).
**Cuidado.** (1) "Abaixo de 80" em 2022 pegou bonds de cupom baixo cujo preço caiu por juro (a regra pedida é por preço; o P&L é só spread porque o
Treasury está hedgeado, mas a seleção mistura juro e crédito); (2) os preços de mar/2020 vêm de prints FINRA esparsos: Vale de 78 a 99 em 5 dias é
o mercado de verdade, mas executar 10% do PL a 78 naquela semana é otimista; (3) 2 episódios em 7 anos. **Tentar:** filtrar por spread (não
preço), estender para EMHY/CEMB como veículo líquido do mesmo gatilho, e a safra de 2015-16 (Petrobras) com preços de dealer.
**Soberanos em crise (Argentina, Ucrânia, Egito, Gana, Sri Lanka):** sem preço gratuito — não testável. O análogo líquido é o EM HY (EMHY/PCY,
tabela do I5): OOS ~0 a +1,2 pp hedgeado.

## I8 — Juros globais relativos (10 anos) — reprovado
**Tese.** Carry (inclinação local 10a − juro de política) e reversão do spread contra a média dos países, com hedge cambial.
**Implementação.** IRLTLT01 (média mensal OECD) de 7 (G7) ou 13 países; excesso local hedgeado = (y10 − juro de política BIS)/12 − D·Δy.
Sinal com dado do mês m, posição no mês m+2 (a média de m+1 não entra no sinal). n comprados x n vendidos, 1x por perna (mesma duration).
O retorno do mês entra no último dia útil (espalhar pelos dias subestimava a vol em 4,6x — bug corrigido antes de rodar o motor).
Custo 2 bps por perna (futuro).
**Resultado.** Carry: IS +2,2 a +3,9, **OOS −3,0 a −6,3 pp**; reversão: ±0,9; combinado −2,7 a 0. Escolhido (carry, n3, G7): OOS 6,5% vs 11,4%,
pior queda −16,8%. 2021 −14,3 e 2022 −12,6 pp.
**Negócios.** Melhores: comprado Itália ago/2010→abr/2021 (+18 pp: Draghi/"whatever it takes"), comprado EUA 2008-19 (+9,5), Reino Unido 2010-16,
vendido gilt jun→set/2022 (+4,6, mini-budget). Piores: **vendido Alemanha abr/2008→ago/2022 (−20,6: o Bund de curva achatada pelo BCE com juro
negativo rendia muito)**, comprado EUA mai/2020→set/2022 (−7,7) e Canadá (−7,0): o carry de inclinação comprou as curvas mais inclinadas
exatamente antes da alta de juros global, em que elas subiram mais. Comprado Itália 2022-26 (−7,2) e Japão 2023-26 (−6,4: o BoJ saindo do YCC).
**Por quê.** O carry de inclinação é um short de volatilidade de juros: paga na era de QE (2010-20) e devolve tudo no choque de inflação.
Dados mensais médios e sem futuros = teste indicativo. **Tentar:** carry + roll medido com a curva inteira e beta-neutro (o JGB e o Bund têm
volatilidade muito menor que o Treasury: equal-notional não é risco igual).

## I9 — Carry de moedas realista / real tático EM ↔ A1 (vencedor da atribuição), JF6, JF7
**Tese.** Carry G10+LatAm é o prêmio que pagou na atribuição; tornar realista: teto de 20% por moeda depois do vol-alvo, sem moeda de juro real
negativo, com regime (VIX em contango) e hedge de cauda. E o "real tático" do JF6 aplicado a 10 EM (MXN, ZAR, INR, IDR, KRW, TRY, CLP, COP, PLN, HUF):
ranquear a variação do diferencial de juro real (juro de política − CPI 12m BIS defasado 2 meses, contra os EUA; z de 5 anos).
**Implementação.** n=3 x 3, inverso da vol, vol-alvo 8%, mensal; carry = diferencial BIS (NDF com 70%); custo G10 2 bps, EM 15 bps, TRY 30 bps.
Hedge de cauda: put de 1 mês 5% OTM em AUDJPY sobre o notional comprado, preço Black-Scholes com vol = 1,15 x realizada (mín. +1 pp), payoff no
vencimento (sem marcação intermediária). Regime: zera com VIX > VIX3M.
**Resultado.** Carry G10+LatAm: **IS −0,8, OOS +7,5 pp/ano** (vol 6%); carry com filtro de juro real: IS −0,3, OOS +6,4; real tático: IS +0,4,
OOS +1,4. **O regime VIX em contango custa 2,5–3 pp/ano em todos** (sai no fundo, volta tarde — igual ao JF7); a put de AUDJPY custa ~0,5–0,6 pp/ano
e pagou em out/2008 (+5,3 pp), mai/2010 (+2,9), mai/2012, mar/2020 (+1,8) e jul/2024 (+1,8), mas não o suficiente (2009: −5,8 pp de prêmio caro).
O IS escolheu o real tático (IR IS 0,10 contra −0,1 do carry): OOS 12,8% vs 11,4%, IR 0,28, PBO 17%.
**Negócios do real tático.** **A lira explica tudo:** vendido TRY nov/2021→jun/2023 (juro real despencando com Erdogan cortando: +11,3 pp) e comprado
TRY set/2024→hoje (choque ortodoxo de Şimşek, juro real subindo: +8,5 pp) = +19 pp do OOS; MXN comprado set/2022→abr/2024 (+5,8), COP 2026 (+3,7).
Piores: ZAR comprado jan→abr/2020 (−4,9), PLN 2014-15, KRW 2008, HUF/ZAR no OOS (−5,0/−5,7). Sem TRY o real tático seria negativo no OOS.
**Carry G10+LatAm no OOS (não escolhido):** JPY vendido +10,8 pp, COP +9,6, MXN +7,8, BRL +7,2 comprados; perdas CLP −0,1. Anos: 2022 +11,6,
2023 +12,9, 2025 +5,2, 2026 +11,2; IS: 2008 −9,4, 2015 −9,1, 2020 −8,2.
**Bug encontrado (afeta A1/F11 de outras frentes):** o Yahoo cotou COP=X a 26,2 em vez de 2.600 em 04-05/jun/2015 — dois dias seguidos, então o
`limpa_fx` da base (que só pega reversão no dia seguinte) não remove: **+9.789% em um dia** para quem estava comprado em COP. Antes da correção o
carry "rendia" +26 pp/ano no IS com vol de 355%. Também: IDR nov-dez/2013 (+22%/−19%), NOK 20/mar/2020 (+39%/−34%), EURUSD 08/dez/2008 (+17%/−13%).
Corrigido aqui com `limpa_nivel` (salto > 8% desfeito em até 8 dias, em log); `base.py` não foi alterado — **sugestão: aplicar a mesma limpeza em
`fg._fx()`** e reconferir A1/F11 (o A1 está comprado/vendido em COP).
**Tentar.** Carry G10+LatAm puro como fundo (o IS 2010-20 ~0 é o problema: o prêmio é do regime de diferenciais altos de 2021+); real tático
excluindo TRY ou com teto de 10%; put de AUDJPY só quando a vol implícita (não temos) estiver abaixo da realizada.

## Bugs e cuidados gerais desta frente
- Treasuries sintéticos: o retorno usa a taxa do dia (`fd0`) e o sinal a taxa defasada 1 dia (`fd`); na 1ª versão o retorno também estava defasado (sem viés, mas desalinhado do SHY) — corrigido.
- Erros de cotação de 2+ dias no Yahoo FX (acima). Sempre rodar `limpa_nivel` antes de usar `FXY`.
- FRED: séries ICE/BofA (OAS) truncadas a 3 anos desde 2025 — o `fred_diario.parquet` também começa em 2023-10 para elas.
- Retorno mensal espalhado em dias úteis subestima a vol (e infla o IR) em ~√21: lançar no último dia do mês.
- TIP − h·IEF com h por duration não é breakeven puro (beta −0,25 ao IEF).
- Hedge de crédito por beta ao IEF limitado a [0,1]: para IG (LQD, duration 8,5 > IEF 7,5) sobra duração comprada — o IS de IG é parcialmente juro.
- Preços de eurobonds (FINRA) são esparsos: compra-e-segura e marcação no último preço; desconfie de ganhos de 20% em 5 dias.

## O que levar
1. **Carry de moedas G10+LatAm** continua sendo o prêmio mais forte fora do Brasil (+6 a +7,5 pp OOS), sem regime VIX e sem put cara; mas o IS
   2010-20 é zero — dimensionar como prêmio de regime, não como alfa.
2. **Eurobonds BR em safra de stress** replica (I7: 100% das variantes > CDI OOS), com compra-e-segura; 2 episódios — sizing de evento.
3. **Inflação implícita: seguir o choque, não vendê-lo** (I2, e o JF2 no Brasil pelo avesso). Um episódio (2021) — guardar como regra de
   gestão de risco de livros de juros (não vender inflação com o gap abrindo), mais do que como fundo.
4. Juros (I1, I3, I4, I8) e o "crédito antecipa ação" agregado (I6): descartar nos EUA/global com dados gratuitos.
