# Frente JUROS E CÂMBIO — caderno de pesquisa (rodada 2, out/2026)

Código: `quant/fundos/ideias_juros_fx.py` (`python ideias_juros_fx.py dados` baixa; `python ideias_juros_fx.py` roda tudo).
Resultado: `resultado/ideias_juros_fx.pkl` (cada fundo tem `contrib` diário por ativo e `trades` com taxa/sinal na entrada e na saída).
Saída do console: `resultado/ideias_juros_fx_saida.txt`.

## Dados novos (em `quant/fundos/dados/`, com cache)
| arquivo | fonte | uso |
|---|---|---|
| `focus_anuais.parquet` | BCB Olinda, ExpectativasMercadoAnuais (Selic e IPCA, mediana, h = 0..4 anos), 2000+ | Selic esperada, juro neutro, IPCA esperado 3 anos |
| `focus_ipca12m.parquet` | BCB Olinda, IPCA 12 meses suavizado, 2001+ | inflação esperada / juro real ex-ante |
| `sgs_432/433/22704.parquet` | SGS: Selic meta, IPCA mensal, fluxo cambial total mensal | |
| `y_fx_fronteira.parquet` | Yahoo: EGP, NGN, KZT, PKR, ARS, KES, UAH, GHS, UYU, DOP, UZS, RSD | carry de fronteira |
| `imf_juros_fronteira.parquet` | FMI (api.imf.org, MFS_IR): mercado monetário, T-bill e taxa de política, mensal | carry de fronteira |

O Focus entra com 1 dia útil de defasagem; o CFTC com +3 dias (relatório de terça sai na sexta); o fluxo cambial mensal com +12 dias após o fim do mês; o juro do FMI com 2 meses.

## Como os títulos foram marcados (vale para JF1–JF4)
Tesouro Direto (taxa de resgate da manhã), 2005+ para sinais e 2008+ para retorno. Retorno diário de cada título = carry `(1+y)^(1/252)-1`
(+ IPCA do mês rateado por dia útil nas NTN-B) − duration modificada × Δy + ½D²Δy² − CDI do dia. Conferido contra a variação do PU da
NTN-B principal 2035: correlação 0,9997, mesmo acumulado ano a ano (diferença < 0,5 pp/ano). Na prática a mesa faria em DI1/DAP; o risco é o mesmo.
Custos: 2–3 bps de taxa × duration por perna. Vendido em NTN-B = DAP vendido (sem aluguel).

## Resultado (benchmark CDI; OOS 2021-01 → 2026-10, exceto JF5: 2023-01 →)
| fundo | escolhido no IS | OOS a.a. | CDI | IR OOS | P(bater) | PBO | custo x2 / +1 dia (pp) |
|---|---|---|---|---|---|---|---|
| JF1 Juro real de valor | regra a6.5 | 11,6% | 11,4% | 0,05 | 53% | 1% | −0,1 / +0,2 |
| JF2 Inflação implícita x Focus | z 1,0, 2a, só vende | 8,5% | 11,4% | −0,43 | 18% | 84% | −3,8 / −2,4 |
| JF3 Prêmio DI 1a x Selic Focus | thr 1,5 pp, sem filtro | 10,8% | 11,4% | −0,24 | 26% | 38% | −0,7 / −0,5 |
| JF4 Inclinação pelo ciclo | thr 1 pp, 1a x 5a | 10,5% | 11,4% | −0,18 | 30% | 46% | −1,6 / −0,7 |
| JF5 Cupom cambial x SOFR | thr 1,5 pp | 13,1% | 13,1% | 0,02 | 46% | 36% | −0,2 / 0,0 |
| JF6 Real tático | juro+fluxo, 5a | 12,4% | 11,4% | 0,23 | 71% | 35% | +0,9 / +0,9 |
| JF7 Carry realista CME/B3 | n3, sem proteção, L/S | 11,8% | 11,4% | 0,07 | 55% | 14% | −0,3 / +0,4 |
| JF8 Carry de fronteira | n5, sem filtro | 16,7% | 11,4% | 0,56 | 88% | 41% | +4,7 / +5,1 |

Resumo honesto: nenhuma ideia de juros Brasil sobreviveu como alfa consistente no OOS. As duas coisas que pagam são **prêmios de risco
(carry) mal remunerados**, não previsão: carry de fronteira (JF8) e o diferencial de juro real no real (JF6, variante "juro"). E o JF1
funciona como regra de *valor* de prazo longo, mas o OOS ainda está em aberto (a posição de 2024 está marcada a IPCA+6,8%).

---

## JF1 — Juro real de valor ("IPCA+7% numa NTN-B longa é demais")
**Tese.** O juro real neutro brasileiro (Focus: Selic 3 anos / IPCA 3 anos) fica em 4,3–6,3%. Quando a NTN-B de 10 anos paga 6,5%+ o
mercado está cobrando prêmio fiscal/de risco que historicamente foi devolvido. Compra NTN-B ~15 anos (5 anos de duration por PL),
zera quando o juro real cai 1 pp.
**Implementação.** `juro_real(regra)`: curva real interpolada no vértice de 10 anos (NTN-B principal + NTN-B com cupom), regras
`pXX` (percentil 5 anos, histórico desde 2005) ou `aX` (nível absoluto). O IS escolheu **a6.5** (entra acima de 6,5%, sai abaixo de 5,5%).
**Resultado.** Total 2010–26: +1,2 pp/ano sobre o CDI com vol 3,9%, pior queda −5,7%, 6 negócios, 5 ganhadores. OOS +0,2 pp/ano (IR 0,05).
PBO 1% (as regras de nível dominam as de percentil em quase todo sub-período). As regras de percentil perdem no OOS (−1,2 pp/ano): em 2021
o juro de 5,8% já era "caro" pelo percentil e o fundo comprou antes da alta para 8%.

Negócios (todos):
- comprei NTN-B principal 2035 a IPCA+6,51% em 11/mar/2015, zerei a 5,41% em 13/fev/2017: **+7,95% do PL** (impeachment / teto de gastos).
- comprei NTN-B principal 2024 a IPCA+6,64% em dez/2013, zerei a 5,33% em set/2014: **+7,56%**.
- comprei NTN-B 2024 a IPCA+7,40% em jan/2008 (crise), zerei a 6,40% em mar/2011: **+6,10%** (inclui o susto de out/2008).
- comprei NTN-B 2035/2040 a IPCA+6,41% em dez/2022, zerei a 5,37% em jun/2023: **+4,05%** (o "medo do governo Lula" devolvido em 6 meses).
- 2011 (NTN-B 2024, 6,39%→5,61%): +1,87%.
- **perdedor:** comprei NTN-B 2040 a IPCA+6,48% em jun/2024, ainda aberta em out/2026 a 6,78% (chegou a 8%+ em 2025): **−1,8%**. O carry
  (IPCA+6,5% contra CDI de 15%) é negativo enquanto o Copom aperta — é o custo de esperar.
**O que deu certo.** Comprar prêmio fiscal extremo e ter paciência: os 4 grandes ganhos vieram de choques políticos/fiscais que se desfizeram
em 6–24 meses. **O que deu errado.** Percentil móvel não é âncora (o regime de juro real mudou para cima em 2022–26). **Próximo:** usar o neutro
do Focus/BC como âncora e dimensionar por (y − neutro); adicionar saída por tempo ou por carry negativo quando a Selic real > 8%.

## JF2 — Inflação implícita x Focus — **reprovado**
**Tese.** Breakeven 3 anos muito acima do IPCA esperado pelo Focus = prêmio de inflação caro → vender inflação (pré comprado, NTN-B/DAP vendido, DV01 neutro).
**Resultado.** Perde no IS e no OOS em todas as 8 variantes (0% batem o CDI no OOS), PBO 84%. Pior negócio: vendi inflação em fev/2021 com
breakeven 4,06% e Focus 3,48% (gap 0,6 pp acima do normal); a inflação foi a 10%: **−12,6% do PL** em 19 meses. Também −5,5% em 2010–11 e −4,9%
em out/2024–mar/2025. Os ganhos (+3,6% em 2018, +2,8% em 2015, +2,4% em nov/2022) são menores.
**Por quê.** O Focus erra *na mesma direção* que o choque: quando o breakeven sobe acima do Focus, é porque o mercado está vendo o choque antes
dos economistas. O gap é informação, não prêmio. **Bug encontrado:** a interpolação da curva real saltava até 1,4 pp em um dia quando um
título entrava/saía (jun/2011) → usamos mediana de 5 dias. **Próximo:** testar o contrário (seguir o gap = momentum de inflação implícita) e usar DAP x DI1 2019+.

## JF3 — Prêmio do DI 1 ano sobre a Selic esperada
**Tese.** Em pânico o DI curto paga muito mais que a Selic média que o Focus espera → receber taxa (2008, 2015, 2018, 2022, 2024).
**Resultado.** IS escolheu prêmio > 1,5 pp; IS IR 0,44, OOS −0,6 pp/ano. Melhores: recebi LTN ~1a a 16,48% em 24/out/2008 com CDI esperado de 13,84%
(prêmio 2,6 pp), zerei a 13,49% em dez/2008: **+6,5% do PL em 30 dias**; recebi a 8,05% em jun/2018 (greve dos caminhoneiros, prêmio 1,5 pp): **+3,7%**;
nov/2022 (PEC da transição, 14,06%): **+2,0%**; set/2015 (15,08%): +1,9%. Piores: recebi a 10,51% em out/2021 com o Focus em 8,2% — o Focus é que
estava errado, a Selic foi a 13,75%: **−2,1%**; nov/2024 a 12,96% (Focus 11,5%, Selic foi a 15%): **−1,9%**; mar/2008: −1,6%.
**Lição.** O prêmio é real quando o choque é de *risco* (2008, 2018, 2022) e é falso quando o choque é de *inflação/BC atrás da curva* (2021, 2024).
Testei um filtro "não receber com o Focus revisando a Selic para cima" — ele melhora o OOS (+0,2 a +0,3 pp/ano, IR 0,35), mas **foi desenhado
depois de ver 2021, então o OOS dele está contaminado**; o IS não o escolheu. **Próximo:** versão Copom-a-Copom com DI1 2019+ (DI do mês da
reunião x decisão esperada), e distinguir choque de risco (CDS/dólar subindo) de choque de inflação (IPCA surpresa).

## JF4 — Inclinação pelo ciclo do Copom — sem alfa
Focus esperando cortes > 1 pp em 12m → steepener 1a x 5a; altas → flattener. Ganhos clássicos: steepener jan–jun/2009 (+5,3%), flattener 2010 (+4,6%),
steepener 2017 (+4,2%), flattener 2021 (+3,3%). Perdas quando o ciclo esperado não veio ou veio com prêmio fiscal: steepener abr/2016–jan/2017 (−4,3%),
steepener 2023 (−2,9%), flattener jan/2022 (−2,0%). Acerto 42%, OOS −0,9 pp/ano, 0% das variantes batem o CDI no OOS. A curva já precifica o ciclo do Focus.

## JF5 — Cupom cambial curto x SOFR
**Tese.** FRC de 1 mês (o único cupom com preço de verdade) muito acima da SOFR = escassez de dólar onshore → emprestar dólar onshore
(receber cupom, pagar SOFR + 0,5% de funding offshore), notional 5x PL.
**Dado:** o cupom limpo curto ficou em média **1,07 pp acima da SOFR** (2019–2026): é uma base estrutural (risco de conversibilidade, balanço de banco),
não uma anomalia. Picos: mar/2020 (FRC 2,26% x SOFR 0,06%) e set/2022–jan/2023 (4,35% x 2,27%).
**Resultado.** 4 negócios, 4 ganhadores (+1,35% set/2022–jan/2023; +1,33% mar–jul/2020), mas o limiar escolhido no IS (1,5 pp líquido) não disparou no OOS.
Com limiar 0,5 pp fica quase sempre ligado e rende CDI + 2,0 pp/ano no OOS com vol de 0,6% (IR 1,6–2,5). **Isso é Sharpe de bug pelo critério do
BRIEF — e é explicado:** a vol medida é só a da marcação (duration 0,08), o risco verdadeiro é cauda de conversibilidade/IOF que não aconteceu
na amostra; e o resultado depende inteiramente do funding de 0,5% e de ter caixa offshore. Não é alfa de mesa; é uma linha de tesouraria.

## JF6 — Real tático (juro real, CFTC, fluxo)
**Tese.** Diferencial de juro real (Selic − IPCA 12m Focus) − (Fed funds − breakeven 5a) alto em relação aos últimos 5 anos → comprado em real;
especulador (leveraged funds CFTC) em extremo → contra; fluxo cambial 3 meses (BCB) → a favor. Semanal, vol-alvo 10% na convicção cheia, via DOL
(carry = CDI − T-bill − 1%).
**Resultado.** IS escolheu "juro+fluxo" (IR IS 0,75): OOS +1 pp/ano, P(bater) 71%, 100% das variantes batem o CDI no OOS, sobrevive a custo x2 e +1 dia.
A variante só "juro" é a melhor no OOS (+5,8% a.a. de excesso, IR 0,73 no período todo). Total da escolhida 2011–26: +3,4 pp/ano, vol 5,4%, pior queda −12%. **CFTC contrarian piora tudo** (sozinho: IS −5 pp/ano).
Negócios: vendido em real nov/2011 (PTAX 1,81) → mai/2015 (3,08): **+17,5% do PL**; vendido out/2017 (3,25) → jul/2020 (5,36, Covid): **+21,6%**;
comprado mai/2025 (5,66) → out/2026 (5,01): **+6,9%**; comprado mai/2015–out/2017: +5,6%. Piores: vendido jul/2010–jan/2011 (−3,6%, o real ainda
apreciava); comprado jun/2021–ago/2024 (−1,4%: carry alto comido pela desvalorização).
**Por quê.** O sinal é a *variação* do juro real relativo (z de 5 anos), não o nível: quando o diferencial cai (2011–14 Dilma/Tombini, 2017–20
Selic indo a 2%), o real perde o suporte de carry e anda anos. **Próximo:** combinar com JF1 (juro real alto + real barato = mesma tese), testar DOL 2019+ em vez de PTAX.

## JF7 — Carry de moedas realista (CME/B3) — sem alfa, por causa da lira
Universo só com futuro líquido (G10 + MXN, ZAR, PLN, HUF, CZK, ILS, TRY, CNH), haircut 50% no carry de EM, teto 20%, vol-alvo 8%.
IS escolheu L/S top-3 sem proteção: OOS +0,4 pp/ano, IR 0,07. **A proteção por VIX piora** (sai no fundo e volta tarde) e o long-only perde (−4,5 a −8,4 pp/ano OOS).
Um único negócio explica: **comprado em lira turca de fev/2014 a out/2026: −61,8% do PL acumulado**. Os ganhos: vendido em iene out/2016–2026 (+20,0%),
vendido em coroa sueca 2014–20 (+10,8%), comprado em CNY 2011–14 (+9,6%), comprado em peso mexicano 2016–26 (+7,1%).
Sem TRY (regra ex-post!) o L/S faz +9 pp/ano no OOS — é preciso uma regra ex-ante: **excluir moeda com juro real negativo** (TRY 2021–23). **Próximo:** baixar CPI por país (BIS/FRED) e usar carry real.

## JF8 — Carry de fronteira ("o carry que ninguém arbitra") — **o mais promissor, com ressalvas grandes**
**Tese.** Moedas de fronteira pagam juro local de 10–30% e desvalorizam em média menos que isso; custo de 150 bps, controles de capital e
falta de hedge afastam o capital institucional. Comprado nas 5 de maior juro local (FMI, defasado 2 meses), peso igual, mensal.
**Resultado.** Total 2010–26: +4,4 pp/ano sobre o CDI, vol 9,0%, pior queda −16,6%. OOS +5,3 pp/ano, IR 0,56, P(bater) 88%, sobrevive a custo x2 (+4,7) e +1 dia (+5,1).
Por moeda (total, % do PL): GHS +25,7, NGN +15,6, UAH +13,3, EGP +11,4, KES +10,8, UZS +7,4, RSD +6,0; ARS −5,7, UYU −4,5.
Por ano: 2022 −14,3% e 2023 −10,5% (cedi −50%, Egito, Nigéria, Paquistão), 2024 +10,6%, **2025 +23,1%** (EGP/NGN pós-desvalorização pagando 20%+ reais).
Negócios: comprado em cedi jun/2012–mai/2026 (carry 8–25%): +23,2%; naira mai/2024–out/2026 (depois das duas desvalorizações, carry 11–12% real): +7,2%;
hryvnia abr/2018–mar/2020: +6,9%; libra egípcia 2009–14: +6,7%; naira 2012–14: +6,7%; xelim queniano dez/2023–fev/2025: +5,7%.
Piores: peso argentino mar/2013–jul/2020 (−7,2%: taxa oficial com cepo), rupia paquistanesa mar–set/2022 (−3,4%), hryvnia mar/2014 (Crimeia, −3,3% em 19 dias).
**Ressalvas (decisivas):**
1. **O resultado inteiro é a hipótese de carry.** Com o juro do FMI cheio: +3,8/+4,9 pp/ano (IS/OOS). Com 75% do juro: zero. Com 50% (como manda o
   brief para EM): −4,2/−5,6 pp/ano. Ou seja: só funciona se o fundo realmente consegue comprar T-bill local (Egito, Nigéria, Gana, Quênia
   têm acesso de estrangeiro, com fila de repatriação).
2. **Taxa oficial ≠ taxa de saída.** Nigéria 2016–17 e 2021–23, Egito 2022–23 e Argentina tiveram câmbio paralelo; o capital ficava preso. O Yahoo
   mostra a oficial, então o backtest *subestima* a perda nas crises (a desvalorização aparece de uma vez, mas o atraso para sair não).
3. **Bugs encontrados e corrigidos:** (a) Yahoo tem erros de 100x que se desfazem no dia seguinte (NGN 2011, 2015–18; PKR 2011, 2014; GHS 2011, 2020)
   e o `limpa_fx` do `base.py` não pega (testa soma aritmética, não log); (b) o `limpa_fx` **zera qualquer dia acima de 50%**, o que apagava a
   desvalorização real do peso argentino em 14/dez/2023 (−54%) — teria sido um ganho falso. Novo `limpa_log`: só remove salto desfeito em até 2 dias
   (em log, com tolerância 10%). (c) Lacunas no Yahoo escondiam saltos (diff sobre NaN) → diff sobre preço com ffill. Depois das correções o OOS caiu de +7,7 para +5,3 pp/ano.
**Próximo:** dimensionar por (carry − inflação local) e por liquidez/acessibilidade, filtro de câmbio paralelo, preços de NDF/forward quando disponíveis.

## O que não foi testado
- **Juros globais RV (ideia 8):** não há futuros de Bund/Gilt/JGB gratuitos; IGOV/BWX são cestas sem hedge cambial — o spread país não é negociável com esses dados.
- Copom reunião a reunião com DI1 (2019+) — fica como próximo passo do JF3.

## Bugs e cuidados gerais
- `futuros.parquet` tem cada linha 3 vezes → `drop_duplicates(["date","ticker"])`.
- SGS 432 (Selic meta) vem com datas futuras (meta vigente até a próxima reunião) — só usar até a data de decisão.
- Taxas do Tesouro Direto têm spread de 8–12 bps embutido; usar sempre a mesma ponta (resgate) para sinal e retorno.
- O motor escolhe pelo IR do IS; quando a melhor variante no OOS é outra (JF6 "juro", JF5 limiar baixo), isso está registrado acima e **não** deve virar a escolha sem nova amostra.
