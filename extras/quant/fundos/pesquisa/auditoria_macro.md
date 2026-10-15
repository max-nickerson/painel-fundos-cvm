# Auditoria (red team) — candidatos macro ao top 5

Código: `ideias_aud_macro.py` (fundos corrigidos com sufixo " [auditado]" + `analise()`); saída das tabelas em
`resultado/ideias_aud_macro_analise.txt`, rodada do motor em `resultado/ideias_aud_macro_log.txt`, resultado em `resultado/ideias_aud_macro.pkl`.
Dado novo: `dados/aud_cme_fx.parquet` (futuros contínuos de moeda da CME no Yahoo: 6E, 6J, 6B, 6A, 6C, 6S, 6M, 6N, 6Z, 6L, 6R).
Não alterei base.py, motor.py, rodar.py, regimes.py nem nenhum ideias_* existente.

## Achado transversal: o `dd_stop` de regimes.py executa no mesmo fechamento do sinal
`_dd_stop` usa a cota até o fechamento de t−1 e já zera o retorno de t, ou seja, opera no mesmo fechamento que gerou o sinal.
Os regimes de mercado usam t−2 (correto); o da própria curva não. Em estratégias com perdas em sequência (venda de vol), isso
é quase olhar o futuro: o primeiro dia ruim já desliga a estratégia antes do pior dia (ex.: 2/fev/2018 desliga e 5/fev/2018, −23% no
swap de variância, passa em branco). Com a execução em t+1:

| fundo | IS IR mesmo fech. → t+1 | OOS ativo / IR mesmo fech. → t+1 | DD OOS |
|---|---|---|---|
| 11 Carry | 0,08 → 0,08 | +10,9 / 1,54 → +10,8 / 1,53 | −5,1 → −5,7 |
| IAC4 VS_EUA | **0,57 → 0,07** | +9,6 / 1,01 → **+7,6 / 0,67** | −11,5 → −18,8 |
| IAC9 perp | igual (dd_stop nunca dispara) | igual | igual |

No IAC4 o `dd_stop` foi escolhido no IS **por causa** desse artefato. Corrigido em `com_regime_t1` (só neste módulo).
**Recomendação:** corrigir `regimes.serie_exposicao`/`aplica_regime` (shift(1) no dd_stop e hmm_propria) e re-rodar a rodada final.

## 1. "11 Carry de moedas global" — APROVADO COM CORREÇÃO (rebaixado)
**Suspeita do brief:** carry pela taxa de política do BIS, não pelo forward.

**Medição do carry implícito.**
- *Futuros CME no Yahoo:* inservíveis. A base ln(F/S) dos contínuos tem ruído de ±1% por dia (fechamento não simultâneo do spot
  Yahoo x ajuste CME, e rolagem desconhecida — o contínuo parece rolar mensalmente em alguns contratos). Ex.: 6M (MXN) em 2023,
  diferencial ~6% a.a., deveria mostrar base ≈ −1,5% com 90 dias para o vencimento; mostrou +0,97%. Não usei.
- *BRL (B3):* carry de quem fica comprado em real = CDI − cupom (1º FRC). Fica **~1,1 pp abaixo** do Selic−FF do BIS todo ano
  (2019–26; ex. 2022: 10,8 BIS x 9,6 B3). O original usava BIS x 0,7 (mais conservador que o real, 3 pp a menos). Corrigido para o medido.
- *G10 e EM entregáveis (MXN, ZAR, PLN, HUF, CZK, ILS):* paridade coberta vale com desvio de dezenas de bps; apliquei −0,5 pp nos EM.
- *NDF (INR, IDR, KRW, CLP, COP, THB, PHP, CNY):* x0,5 (sem dado gratuito; haircut conservador pedido).
- *TRY:* a evidência publicada NÃO confirma que o offshore pagou menos que a política em todo o período: em 2024 o implícito
  overnight offshore chegou a 61% com a política em 50% (Bloomberg, ago/2024), e em 2023 bancos turcos captavam lira offshore via swap
  sintético a ~30% com política de 7–8,5% (Türkiye Today). Ou seja, em 2022–23 o offshore pagava MAIS que o BIS. Testei x1, x0,5 e x0.
- *Custos:* o original cobrava 3 bps por troca para TODAS as moedas (inclusive TRY e NDFs). Corrigido: G10 2, EM 10, NDF 20, TRY 30 bps.

**Sensibilidade (n=3, ls, sem regime; IS 2010–20, OOS 2021+):**

| variante | IS ativo / IR | OOS ativo / IR / DD |
|---|---|---|
| original | −0,8 / −0,07 | +9,5 / 1,29 / −8,2 |
| BIS puro, custos por moeda | +0,2 / 0,06 | +9,4 / 1,29 / −7,9 |
| realista, TRY x1 | −1,8 / −0,19 | +8,2 / 1,12 / −10,7 |
| realista, TRY x0,5 | −1,1 / −0,11 | **+5,2 / 0,72** / −11,1 |
| realista, sem TRY | +1,4 / 0,21 | +9,1 / 1,21 / −8,2 |

O TRY é a fragilidade: com haircut de 50% ele continua no topo (carry nominal enorme) mas o carry não paga a depreciação → −17 pp de
contribuição OOS. Sem TRY o resultado vem de **vendido em JPY (+12,8 pp), comprado em MXN (+9,4) e BRL (+7,6)** — o carry trade clássico
do ciclo de alta do Fed com o BoJ em zero (USDJPY 103→160). Isso é real, mas é um regime, não um alfa recorrente.

**O problema de verdade é o IS:** IR IS ≈ 0 (−0,07 a +0,21) em 2010–20 em todas as variantes e regimes; o OOS bom vale para todos os
regimes (IR 1,1–1,5) — não é sorte da escolha do regime, é sorte do período. Não há evidência ex-ante; a expectativa honesta para
frente é a de carry de literatura (IR 0,3–0,5, com crash de cauda).

**Versão auditada** (`11 Carry de moedas global [auditado]`, carry realista, TRY x0 escolhido no IS, regimes em t+1 → hmm_sp):
**OOS 17,0% vs CDI 11,4% (+5,6 pp), IR 0,90, pior queda −9,0%**, P 98%, PBO 18%, custo x2 +4,5 pp. Sem regime: +8,9 pp, IR 1,19, DD −8,2%.

**JF7 "Carry realista (CME/B3)":** o nome engana — o código não usa nenhum dado da CME nem da B3; é BIS x0,5 para EM. Resultado
(+3,4 pp, IR 0,50, IS −0,06) tem o mesmo problema de IS ≈ 0 e escolheu dd_stop (artefato acima). Substituído pelo auditado.

## 2. "IAC9 Base: cripto (perpétuo)" — REPROVADO para o top 5
**O que está certo no código:** spot e perpétuo da mesma corretora, mesmo candle 00h UTC (sincronia ok); financiamento recebido pelo
vendido no perpétuo com sinal certo (positivo = comprado paga); janela do financiamento alinhada ao retorno (d−1 00h, d 00h]; sinal com
média de 7 dias conhecida em d e execução em d+1; custo 15 bps por montagem (~taker spot 0,10% + perp 0,05%); o capital inteiro é cobrado
de T-bill (margem em USDT não rende), conversão `brl` correta. Sem bug de código.

**O que está errado é a hipótese de capital e o risco ausente:**
- *Margem:* capital = 1,25x o nocional = short do perpétuo com 4x de alavancagem; o spot na conta à vista não serve de margem do
  USDT-M. Uma alta de +25–30% em 1–2 dias (SOL, DOGE, XRP fizeram isso várias vezes) liquida o short. Realista: 1,5–2x.
- *Contraparte:* nenhum custo. Cobrei perda esperada de 2,5% a.a. sobre o capital na corretora (≈5% a.a. de chance x 50% de perda).

| capital | contraparte | IS ativo / IR | OOS ativo / IR |
|---|---|---|---|
| 1,25 | 0 | +17,1 / 6,09 | +1,7 / 2,81 |
| 1,5 | 2,5% | +12,1 / 5,38 | +0,4 / 0,83 |
| 2,0 | 2,5% | +8,4 / 5,12 | **−0,3 / −0,85** |

- *Alocação:* OOS só 34% dos dias com posição, 35% do PL na corretora em média (77% no IS 2020–21), máximo acima de 100% do PL.
- *Cenário FTX (nov/2022):* perder 20% do alocado com 35% do PL na corretora = −7% do PL = ~4 anos do alfa OOS (+1,7 pp);
  perder 50% no pico de alocação = −50% do PL. A vol de 0,5% e o IR 2,5 medem só o que não aconteceu na amostra.

**Versão auditada** (`IAC9 Base cripto perpétuo [auditado]`, thr 10%, capital 1,5x escolhido no IS): **OOS 13,3% vs CDI 13,1% (+0,2 pp),
IR 0,46, pior queda −0,1%** (sem o evento de contraparte), P 58%. O IR 6 do IS é 2020–21 (financiamento 22–48% a.a.), não volta.
Pode existir como livro oportunista pequeno (≤10% do PL, corretoras diferentes), não como fundo do top 5.

## 3. "IAC4 Prêmio de vol com hedge de beta (VS_EUA)" — APROVADO COM CORREÇÃO
**O que está certo:** o prêmio existe — VIX − vol realizada dos 21 dias seguintes foi positivo em todo ano exceto 2008 (média ~3,8 pts;
2018 só 1,0). Marcação diária do swap (realizada acumulada + VIX² do restante) e teto de 2,5x estão corretos; hedge de beta defasado.

**O que estava errado:**
1. `dd_stop` no mesmo fechamento (acima): IS IR 0,57 → 0,07 com t+1. Era o artefato que fazia o fundo parecer seguro em fev/2018.
2. *Tamanho:* o vol-alvo de 8% (estimado em calmaria) levava a vega-nocional a 0,9x PL antes de fev/2018 → **pior dia −23% do PL**
   (5/fev/2018), −15% em 24/ago/2015 e 5/ago/2024. Nenhum dono de fundo aguenta isso. Corrigido com teto de vega 0,25–0,4x PL.
3. *Strike:* o original vende a VIX−1 (correto como bid de dealer; o strike justo ≈ VIX, às vezes 0,5–1 acima por truncamento do VIX).
   VIX−0 (vender no meio) é otimista; VIX−2 mata a estratégia:

| strike | teto vega | IS ativo / IR | OOS ativo / IR / DD | pior dia |
|---|---|---|---|---|
| VIX−0 | 3 (orig.) | +8,9 / 0,65 | +17,3 / 1,20 / −20,8 | −25% |
| VIX−1 | 3 (orig.) | +2,1 / 0,21 | +8,9 / 0,70 / −18,8 | −23% |
| VIX−1 | 0,4 | +3,2 / 0,38 | +8,1 / 0,87 / −14,9 | −10% |
| VIX−1 | 0,25 | +2,8 / 0,44 | +5,3 / 0,84 / −10,6 | −7% |
| VIX−2 | 0,4 | −1,3 / −0,09 | +3,0 / 0,34 / −14,9 | −11% |

Caudas (VIX−1, teto 0,4, sem regime): fev/2018 −9,0%; mar/2020 −0,3% (o hedge de beta pagou); ago/2024 −3,8%; abr/2025 −14,1%;
set–nov/2008 −20%; ago/2015 −9,1%.

**Versão auditada** (`IAC4 Variância EUA vendida [auditado]`, VIX−1, teto 0,4, regime risco_global escolhido no IS com t+1):
**OOS 19,0% vs CDI 11,4% (+7,6 pp), IR 1,42, pior queda −3,6%**, P 100%, PBO 3%, custo x2 +6,3 pp. Com o regime de mercado (VIX,
tendência do S&P e crédito, defasados 2 dias) a exposição média é 0,75 e cai a ~0 em abr/2025 e 2008; fev/2018 ainda custa −6,3%
(pior dia −6,8%). Sem regime: +5,1 pp, IR 0,81, DD −10,6%. IS IR 0,70 (antes 0,57 com artefato).

**Execução real:** swap de variância exige ISDA com dealer; alternativas viáveis: vender strangle/straddle de SPX 1m com delta-hedge
(sem dado gratuito de histórico de opções SPX aqui) ou vender futuros de VIX (IAC5, VIXY/VIXM) — o IAC5 mostrou que o roll de VIX é
sobretudo beta, então não é substituto do prêmio de variância. Antes de operar: cotar 3 dealers o bid do var swap 1m vs VIX por 1 mês.

## Veredito
| fundo | veredito | OOS a.a. vs CDI | IR OOS | pior queda OOS |
|---|---|---|---|---|
| 11 Carry de moedas [auditado] | APROVADO COM CORREÇÃO (sem evidência IS; regime de 2021–25) | 17,0% vs 11,4% (+5,6) | 0,90 | −9,0% |
| IAC9 Base cripto [auditado] | REPROVADO | 13,3% vs 13,1% (+0,2) | 0,46 | −0,1% (+ risco de corretora) |
| IAC4 Variância EUA [auditado] | APROVADO COM CORREÇÃO | 19,0% vs 11,4% (+7,6) | 1,42 | −3,6% |

Fontes TRY: Bloomberg, "Turkish Lira's Offshore Rates Jump as Carry Positions Unwind" (29/ago/2024);
Türkiye Today, "Türkiye's banking watchdog warns local lenders over cheap offshore lira swaps".
