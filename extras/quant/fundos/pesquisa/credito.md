# Caderno de pesquisa — Crédito privado, debêntures e fundos listados (rodada 2)

Código: `quant/fundos/ideias_credito.py` (estratégias, `livro()` de execução, análises) e `dados_credito.py` (downloads CVM).
Resultados: `resultado/ideias_credito.pkl` (lista de dicts do `roda` + `contrib`/`trades`), `resultado/ideias_credito_analises.pkl`,
`resultado/ideias_credito_log.txt`, `resultado/ideias_credito_detalhe.txt` (variantes IS/OOS, por ano, 10 melhores/piores de
cada fundo), `resultado/ideias_credito_analises.txt` (casos de default, prêmio de isenção, fluxo do balcão, lead-lag).
Dados novos em `quant/fundos/dados/`: `cvm_fii_mensal.parquet` (informe mensal FII 2017+), `cvm_cad_cia.parquet` (setor por CNPJ),
`credito_fluxo_balcao.parquet` (agregado diário por debênture do balcão B3: volume com taxa acima/abaixo da referência, taxa mediana),
`cvm_ipe.parquet` (já existia — baixado por outra frente; uso só Categoria/Assunto/Data_Entrega).

## Resumo em uma tela (OOS = 2023-01 em diante; C5 = 2024-07 em diante; fundo = CDI + excesso líquido de custos)

| Fundo | escolhido no IS | OOS a.a. | CDI | IR OOS | P(bater) | PBO | leitura |
|---|---|---|---|---|---|---|---|
| C1 VR de spread vs pares | setor, resíduo ≥ 2 pp | 10,6% | 13,1% | −0,35 | 13% | 67% | compra "barato" que está barato por motivo (Alliança, Viveo, Elfa) |
| C2 Irmãos do mesmo emissor | resíduo ≥ 1 pp | 12,1% | 13,1% | −0,08 | 37% | 62% | diferença entre séries é ruído de print/amortização |
| C3 Carry com filtro | top 10, giro ≥ R$5 mi, sem filtro | **15,2%** | 13,1% | **0,46** | **84%** | **11%** | único positivo consistente; parte é carrego de papel ilíquido marcado na curva |
| C4 Distressed | <80% da curva, todos | 12,3% | 13,1% | −0,03 | 46% | 97% | saúde 2023-24 pagou 20-25%/trade; Aeris, Ambipar(EESG), Braskem devolveram tudo |
| C5 Fluxo do balcão | momento, 21d | 11,1% | 13,5% | −0,79 | 6% | 53% | fluxo não prevê nada; segue o passivo com custo |
| C6 Crédito antecipa ação | vende ação, Δspread ≥ 75 bps, 21d | 16,2% | 13,1% | 0,25 | 62% | 11% | só o lado vendido funciona (Ambipar, Alliança, Viveo); vol 16%, DD −27% |
| C7 Ação antecipa crédito | ação +10% vs BOVA, 63d | 10,6% | 13,1% | −0,39 | 10% | 29% | não funciona |
| C8 IPCA+ vs NTN-B | modo mercado, z ≥ 1 | 14,1% | 13,1% | 0,34 | 87% | 36% | 2 episódios (mar/2020, fev/2023) fazem tudo; IS negativo |
| C9 FII de papel com desconto | 5 mais baratos, P/VP < 0,9 | 6,0% | 13,1% | −0,44 | 24% | 32% | desconto de FII de CRI é sinal de crédito podre (HCTR11 −72%) |

Referência passiva (não é fundo): média igual de todas as debêntures elegíveis (DI + IPCA hedgeado em DAP), sem custo:
**+2,3 pp/ano sobre o CDI desde 2023 (vol 2,4%)**; +1,4 pp desde 2024-07. Nenhuma das seleções bateu esse "índice" de forma
convincente depois de custo — o prêmio de crédito é real, a seleção de papel (com os dados públicos que temos) não agregou.

## Como o retorno foi construído (e o que estava errado na base antiga)

* Preço: VWAP do `pct_curva` (SND, 2019+) dos negócios ≥ R$100 mil. Marca = último negócio aceito (ffill sem limite enquanto
  vivo). Retorno do dia = `Pf(t)/Pf(t-1) × G(t) − 1`, G = acréscimo do PU par (CDI×(1+spread)^(1/252), 1+CDI×%, IPCA do mês ×
  (1+taxa)^(1/252)). Excesso = r + hedge − CDI.
* Hedge de IPCA+: o `Hdd` da `base_diaria.pkl` (DAP de duration mais próxima, razão D/Df escolhida no fim do mês anterior,
  P&L = −razão × variação do ajuste). **Checado**: o "ajuste anterior" da B3 já vem corrigido por (1+CDI)/(1+IPCA proj.)
  (DAPK27: 96.651,47 × 1,000166 = 96.667,50), então a variação já é o P&L em excesso — tentei "corrigir" somando IPCA−CDI e isso
  criava 8 pp/ano de alfa falso; revertido. Beta do índice IPCA hedgeado ao DAP 5a: −0,15 no mês (stale marks x hedge diário).
* Execução (`livro()`): decide no fechamento de t, executa no 1º dia ≥ t+1(+lag) em que o papel NEGOCIA, ao preço daquele dia,
  custo 30 bps por lado (100 bps em estressados). Posição entra com 1/n do PL e depois **deriva com o preço** (compra e segura).
* Bugs/armadilhas encontrados (todos corrigidos no código, em ordem de impacto):
  1. **Peso fixo diário + prints ruidosos = alfa falso.** Com rebalanceamento diário implícito, um papel que alterna 79/57/79
     (TAEE17 em mar/2025, PU estável!) "rende" +11%. C1 caiu de +2,4 para −2,0 pp OOS e C2 de +1,9 para −0,7 pp ao trocar para
     compra-e-segura. Qualquer backtest de debênture com marca ruidosa precisa disso.
  2. **`pct_curva` do SND erra em amortização.** UNIP15 (Unipar, DI+1,25) "caiu" de 99,6 para 66% no dia da 1ª amortização
     (jun/2023) com PU par não amortizado; TAEE17 alterna 79/57. O distressed "ganhava" 51% em Unipar e 33% em Taesa — nunca
     estiveram estressadas. Solução: filtro de prints (salto > 10% só vale se outro negócio em dia posterior confirmar dentro de 3%)
     e, no distressed, confirmação pela **taxa** negociada no balcão B3 (2023+). Distressed caiu de +5,4 para −0,5 pp OOS.
  3. **A base antiga (`base_diaria.P`) cortava pct_curva fora de 30–150%** — apagava justamente Light, Americanas, Ambipar e Raízen
     a 5–30%. Reconstruí P com corte 5–200%.
  4. **`Pi` da base antiga interpola até o próximo negócio** (olha o futuro). Uso só a marca do último negócio.
  5. **Papéis que só "negociam" a 100,00%** (registro/compromissada; DM Securitizadora, Urbem, Morro Redondo): carregam CDI+5
     com vol zero. Excluídos do universo quando ≥ 80% dos negócios de 126 dias foram no par. Ainda assim parte do C3 vem disso (ver C3).
  6. IPCA+ longo a 75% da curva pode ser só juro real (CSN Mineração, Raízen RESA14 em 2022). No distressed o "preço de crédito" do
     IPCA+ é `exp(−(spread sobre NTN-B − 1,5) × D)`, não o pct.
  7. Regex de RJ no IPE pegava menções a RJ de terceiros (Vale/Samarco, Equatorial/CELPA, Natura/Avon, Localiza citando Gol).
     Regra final: categoria "Informações de Companhias em RJ/RE" (ou falência) ou Fato Relevante de ajuizamento/pedido; data =
     **Data_Entrega**; subsidiárias casadas por nome só para uma lista de grupos (Light SESA → Light S.A.).
  8. FII: COTAHIST não tem dividendos. Dividendo do mês M = DY × VP do informe CVM, data-ex no 1º pregão de M+1 — confere com o
     Yahoo para KNCR11 (ref. jul/26 1,2504 vs ex 03/08 1,2493; retorno anual nosso x Yahoo 2023-25: 21,4/10,5/19,6 vs
     21,3/10,5/19,7) e com a queda média de −0,64% no 1º pregão do mês nos FIIs de papel.

## C1 — Valor relativo de spread contra pares ("CDI+6 é demais")
**Tese**: papel com spread muito acima da mediana dos pares (mesmo indexador, faixa de duration 0–2/2–4/4+ e mesmo setor CVM
ou mesma faixa de spread de emissão — "rating implícito") volta para a mediana. Compra resíduo ≥ x; sai com resíduo ≤ x/4,
preço < 70 ou 1 ano. Variante com filtro de faca caindo (spread abriu > 50 bps em 21d ou preço 3 pts abaixo do máximo de 63d).
**Resultado**: IS +3,6 a +5,3 pp sem filtro (2019-22, compressão pós-COVID), OOS −0,8 a −2,2 pp sem filtro e +0,5 a +1,9 pp com
filtro. O escolhido (setor, 2 pp, sem filtro) perdeu 2,5 pp/ano OOS; 2026 −8,4 pp.
**Melhores** (contribuição ao PL): AEGP23 Aegea IPCA (mar/24→abr/25, 98→136% da curva, +40%), LTTE15 Linhas de Taubaté
(dez/21→mar/22, 84→113, +34%), CMDT33 Cemig D (out/21→mar/22, +28%), cluster de eólicas Canta/Pau Rainha/Bonfim/Santa Luz
(dez/21→dez/22, 88,8→100,4, +19% cada — o mesmo risco em 4 CNPJs), XVII11 (jul/23→jul/24, 87→100,5), LVTC22 Livetech (+18%).
**Piores**: AALR13 Alliança (dez/25→out/26, 92,6→26,3, −71%), VVEO15 Viveo/CM Hospitalar (ago/24→jan/25, 90→51, −43%), ELFA12
(jan/23→dez/23, 99→62), AERI12 Aeris (fev/23→ago/23, 98→69), TEPA13, ONCO19 Oncoclínicas (mar/25→abr/25, 84→62), AMBP16 Ambipar,
CSNAA1 CSN, EESG13 (Ambipar), KRSA12 Kora.
**Por quê**: em 2019-22 o spread alto era prêmio de liquidez (infra/eólicas em 2021 voltaram ao par). Em 2023-26 o spread alto
era o mercado sabendo do problema antes (saúde, Ambipar, CSN): "CDI+6 é demais" estava errado — era pouco. O filtro de faca
ajuda (OOS ~+1 pp) mas não paga o custo de oportunidade vs o passivo (+2,3).
**Tentar**: VR só dentro de infra/incentivadas (onde resíduo é liquidez, não crédito); exigir que a ação do emissor (se listada) não
esteja caindo; usar a taxa indicativa ANBIMA (não temos) como "par".

## C2 — Irmãos do mesmo emissor
**Tese**: duas séries do mesmo CNPJ e indexador com duration até 2,5 anos de diferença têm o mesmo risco; compra a mais barata
(spread ≥ média das irmãs + x), sai quando a diferença < 5 bps. **Mudança após a 1ª rodada**: x passou de {0,25; 0,5} para
{0,5; 1,0} — com 0,25 pp eram 1.150 negócios de 5 dias medianos, puro ruído de print (registrado aqui por honestidade).
**Resultado**: IS −2,7 a +1,7; OOS −0,7 a +1,0 pp. Escolhido (1 pp, 10 papéis) −0,7 pp OOS, IR −0,08.
**Melhores**: SULA29 Rede D'Or (mai/23→nov/23, 91→100,5, +11%), NRTB21 (2021-22), JSMLA5 JSL (jan/26→, 91→98), MSGT33.
**Piores**: NRTB21 Norte Brasil (mai/23→ago/23, 144→101: o mesmo papel que "ganhou" antes — pct_curva de IPCA+ com taxa de
emissão alta é instável), CSNAA1 (fev/26→, 83→60), TAEE17 (artefato 93→85 em 3 dias), VERO12, AGRU12.
**Por quê**: o diferencial entre séries reflete covenants/garantias/amortização diferentes e erro do pct_curva, não ineficiência.
**Tentar**: comparar pela **taxa** do balcão (2023+) em vez do pct_curva; restringir a séries com o mesmo cronograma.

## C3 — Carry com filtro de qualidade (o único que sobrevive)
**Tese**: CDI+spread paga o spread se o emissor não quebra. Top n por spread (DI: spread; IPCA: spread sobre NTN-B/DAP) entre
papéis com giro ≥ R$5 ou 20 mi em 63d, pct ≥ 90, spread < 8 pp; sai fora do top 2n; variante com filtro de faca.
**Resultado**: IS +1,2 a +4,8 pp sem filtro, OOS +0,5 a +2,0. Escolhido (10 papéis, R$5 mi, sem filtro): **+2,0 pp OOS, IR 0,46,
P 84%, PBO 11%, vol 4,2%, DD −3,3%**, custo x2 ainda +0,5 pp, +1 dia +1,7 pp. Por ano (pp): 2020 +7,7, 2021 +4,2, 2022 +5,3,
2023 −1,1, 2024 +4,6, 2025 +3,4, 2026 +1,2. O **filtro de faca caindo piorou** nas 4 comparações pareadas (IS e OOS): sair quando o
spread abre realiza a perda no pior preço e perde a reversão — o carrego tem de ser segurado.
**Melhores**: GJAI12 GJA (abr/20→dez/24, venceu, +28%), DMCD11 DM Securitizadora (abr/23→, 100,00 parado, +20%), TBCR18
Transbrasiliana (dez/23→abr/25, +20%), CRFN12 Vert (venceu, +19%), MRER11 Morro Redondo (100,00 parado), HIAG11 Hinove (venceu,
+17%), TXXI11 Travessia, CART12 Raposo Tavares, MSGT12, JSMLA5.
**Piores**: AGAU13 Voke (set/25→, 99→70, −26%), ELFA12 (ago/22→mar/23, 101→84), SIMH16 Simpar, JSL (2 séries, out-dez/25),
KRSA11 Kora, CSNAA1, e IPCA+ de 2019 com prints a 105–115.
**Cuidado (importante)**: ~todo o excesso OOS vem de posições cuja marca quase não variou (papéis ilíquidos marcados no último
negócio). Para GJAI12, CRFN12 e HIAG11 o carrego foi **real** (os papéis venceram e pagaram). Para DMCD11 e MRER11 (ainda
abertas, sempre a 100,00) é marcação na curva — só se confirma no vencimento. Um gestor deve tratar o C3 como "CDI+2 com risco
de evento concentrado em 10 nomes", não como alfa de seleção.
**Tentar**: carry por emissor (não por papel), limite por setor, e marcar posições paradas pela taxa do balcão quando houver.

## C4 — Distressed / recuperação
**Tese**: debênture abaixo de 70–80% do par (preço de crédito: DI = pct; IPCA = efeito do spread sobre NTN-B acima de 1,5 pp) que
negociava ≥ 90 no último ano, em emissor sem RJ (ou com plano aprovado), é pânico: compra e vende a 95. Até 10 papéis, 1 por
emissor, custo 1%/lado, prazo máximo 2 anos; nas variantes "sem_rj", zera se o emissor pede RJ (Data_Entrega no IPE).
De 2023-04 em diante a entrada exige que a taxa do balcão B3 confirme o preço (bug 2).
**Resultado**: só 23 negócios em 7 anos. IS ≈ +1 pp; OOS −0,5 a +0,7 pp; PBO 97% (as variantes são quase iguais). Por ano:
2023 +6,0, 2024 0,0, 2025 −18,8, 2026 +16,3. Filtro de RJ não muda nada: os desastres (Aeris, Braskem) não tinham RJ quando
compramos, e quem tinha RJ já estava abaixo de 10–20%.
**Melhores** (todos reais): SEQL13 Sequoia (set/23 a 35%→abr/26, +32%), DASAC5 Dasa (mai/24 77→96, +26%), HSPA12 Hospital
Anchieta (jun/24 80→99,6, +25%), LVTC22 Livetech (mar/25 77→96), CBRDA8 GPA (ago/23 75→95, +25%), VAMO22 Vamos (abr/20 78→98,
COVID), AALR13 Alliança (jun/24 74→91), ANET12 Vero, KRSA11 Kora (jun/23 77→92), ONCO19 Oncoclínicas (abr/25 65→75, aberta).
→ **o "bloco saúde" de 2023-24** (Kora, Dasa, Alliança, Anchieta) pagou 18–26% por negócio: o mercado vendeu a 75% emissores que
renegociaram e não quebraram.
**Piores**: EESG13 Environmental ESG/Ambipar (set/25 72→13, −82%, RJ em 21/10/25), AERI12 Aeris (set/23 71→14, −80%), BRKMB6
Braskem (jun/25 80→46, RE em ago/26), ELFA12 (77→61), VVEO15 Viveo (78→65), CBRDB8 GPA 2025 (78→71).
**Casos famosos** (1º negócio < 80% do papel mais líquido do emissor e quanto rendeu segurar até hoje, excesso s/ CDI, sem custo):
| emissor | papel | 1º <80% | pct | mínimo | hoje | excesso até hoje | RJ/RE (CVM) |
|---|---|---|---|---|---|---|---|
| Americanas | AMERF2 (pós-plano) | set/24 | 50 | 25 (mai/25) | 28 | −40% | jan/23 |
| Light | LIGHC4 (pós-plano) | jan/25 | 47,5 | 20 | 46,5 | −9% | mai/23 |
| Ambipar | AMBP16 | ago/25 | 74 | 11 | 13 | −82% | out/25 |
| Raízen | RESA14 (IPCA, 2022 = juro real) | — | — | 35 (abr/26) | 50 | −40% | mar/26 |
| GPA | CBRDA8 | ago/23 | 78 | 74 | 88 | +18% | mar/26 (RE) |
| Kora | KRSA11 | jun/23 | 60 | 60 | 94 | +69% | mai/26 (RE) |
| Dasa | DASAC5 | mai/24 | 75 | 75 | 96 | +35% | — |
| Alliança | AALR13 | jun/24 | 79 | 26 | 26 | −65% | ago/26 |
| Oncoclínicas | ONCO19 | abr/25 | 67 | 50 | 75 | +15% | jul/26 |
| Braskem | BRKMA8 | dez/23 | 79 | 31,5 | 42 | −44% | ago/26 (RE) |
| Aeris | AERI11 | mai/25 | 29 | 13 | 13 | −54% | — |
| Casas Bahia | BHIAC0 | nunca < 80 | | 80,6 | | | abr/24 (RE) |
Gol, Azul, Oi, InterCement, Unigel: sem negócios relevantes no SND (dívida offshore ou privada) — não dá para testar aqui.
Americanas e Light só aparecem com os papéis novos pós-plano; as debêntures antigas não têm negócios na base.
**Por quê**: distressed no Brasil é binário e concentrado: 10 vagas, 3 desastres zeram 10 acertos. A recuperação veio em quem
tinha ativo real e dono capitalizado (Dasa/Bradesco-família, Kora, Anchieta). **Tentar**: exigir ação listada que NÃO esteja em
queda livre (o C6 mostra que a ação + spread juntos discriminam), sizing menor por nome, e só pós-plano homologado com
recuperação de garantias (ler o plano — o IPE tem o link do documento).

## C5 — Fluxo do balcão ("o que o mercado está comprando")
**Tese**: negócios com taxa abaixo da mediana do pregão anterior do papel = comprador agredindo. Pressão = (vol abaixo − vol
acima)/vol em 10/21 dias. Segue o fluxo (momento) ou faz o contrário (dá liquidez a vendedor forçado). Balcão B3 2023-03+,
6,5 mi negócios de DEB (deduplicados), corte OOS 2024-07.
**Resultado**: IS +0,7 a +4,3 pp (momento) e −3,3 a +0,2 (contrário); OOS **todas as 8 variantes negativas** (−0,8 a −4,0 pp).
**Melhores**: NRTB21 (set/23→jan/24, 100→147 — artefato de pct de IPCA+ de taxa alta), ITPO14 Itapoá, CTTP11, CRTA12 Rota do
Oeste, CBAN32 Rota das Bandeiras. **Piores**: NTSDA1 NTS (mar/26), CTEE29 ISA, ONCO19 (dez/24), CPFPA5, HSPA12 (nov/23).
**Por quê**: sem lado do agressor e sem a taxa indicativa ANBIMA, "taxa abaixo da do pregão anterior" mede ruído de lote/prazo
de liquidação. 39% de acerto, giro alto, custo come tudo. Fluxo agregado (tabela em `analises.txt`): volume de DEB DI subiu de
R$61 bi/tri (2023T2) para R$197 bi (2025T4) e incentivadas de R$32 bi para R$135 bi (2026T2) — o crescimento dos fundos de
infra/isentos é o motor da compressão de spread de incentivadas (abaixo), mas isso é beta, não sinal de papel.
Obs.: CRI 2023T2 mostra R$1 tri — erro de registro na base de balcão.

## C6 — Crédito antecipa ação (vende a ação)
**Tese**: o debenturista vê o problema antes; spread do emissor abriu ≥ x em 21 dias (mediana dos papéis negociados, preço ≥ 80)
e a ação ainda não caiu (> −5% vs BOVA11 em 21d) → vende a ação contra BOVA11 por h dias (10% do PL por ideia, revisão semanal,
aluguel 2% a.a., 20 bps por giro). Espelho: spread fechou e ação não subiu → compra. Ações por CNPJ (`acoes_diario`), 89 emissores.
**Resultado**: "ambos" negativo em tudo (IS −1 a −7, OOS −3,5 a −8,7 pp); **"só venda" OOS positivo nas 4 variantes (+2,6 a
+9,8 pp)** mas IS negativo (−0,7 a −14 pp). Escolhido (75 bps, 21d, venda): +3,1 pp OOS, IR 0,25, vol 16%, DD −27%.
**Melhores**: Ambipar (vendida jun/25 com spread +93 bps, ação −83% até out/25, +7,7% do PL), Alliança (jan/25, −91%), Viveo
(abr/24, −68%), Aeris (out/24), Qualicorp (nov/23), Sequoia (jun/23), Raízen (set/25), Magalu (jan/23), CSN Mineração (out/25).
**Piores**: Movida (set/26, ação +41% contra), CSN Mineração (set/23), C&A (2023 e 2024), Magalu (fev/25), Vale (2020, COVID),
Oncoclínicas (dez/24), Guararapes.
**Por quê**: assimetria: crédito informa a cauda de baixo (quem vai quebrar), não a de cima. Em 2019-22 a regra vendia
alta-beta em recuperação (Vale, varejo) e perdia. Correlação simples (janelas de 21d sem sobreposição, 4.635 obs.): Δspread
passado × ação futura = +0,03 (nada); ação passada × Δspread futuro = −0,07 (a ação antecipa levemente o crédito, como na
literatura). **Tentar**: só venda, h = 63, e só quando o spread abre **e** o emissor tem dívida curta (vencimento < 2 anos);
combinar com C4 (comprar a debênture quando a ação já caiu e o spread estabilizou = estrutura de capital).

## C7 — Ação antecipa crédito (compra a debênture)
**Tese**: ação subiu ≥ 10/20% vs BOVA11 em 63d e o spread ainda não fechou → compra a debênture. **Resultado**: negativo em todas
as variantes, IS e OOS (−2 a −4 pp). Piores: ONCOA1 (fev/25, 91→60), CBRDB8 GPA (jul/23, 87→70), Ambipar (jun/25), Movida e Klabin
(2020). A alta da ação de empresa alavancada muitas vezes é "opção" (aumento de capital, M&A) que não melhora o credor.
Descartar.

## C8 — Incentivadas IPCA+ contra NTN-B (hedge DAP)
**Tese**: (papel) spread sobre a NTN-B de mesma duration largo contra o próprio histórico de 1 ano; (mercado) mediana do spread
das IPCA+ larga contra o histórico → compra os 15 mais líquidos, sai quando normaliza.
**Resultado**: modo papel IS −3,6 a −5,6 / OOS −1,2 a +1,3; modo mercado IS −0,6 a −1,6 / OOS +1,0 a +1,2. Escolhido (mercado,
z 1): +1,0 pp OOS, IR 0,34, vol 2,7%, P 87%. Na prática são **dois episódios**: compra em 16/03/2020 (COVID; ENMI21 +14%, ELET42
+10%, ENTV12 +9%) e em 09/02/2023 (pós-Americanas, resgates de fundos de crédito; QUAT13, CGMG18, HARG11, ENEV19, CCROB6 +6–8% em
7 meses). Pior: entrada de ago/2019 que pegou o crash de mar/2020 (ENTV12 −12%, PETR26 −11%).
**Prêmio de isenção** (spread mediano sobre NTN-B, IPCA+ elegíveis): incentivadas 0,2–0,5 pp em 2019 → 2,2 em 2020T2 → 1,7 em
2023T1 → **−0,4 pp em 2026T1** (abaixo da NTN-B!); não incentivadas 1,8 → 3,7 → 3,1 → 1,6. O prêmio de isenção (diferença) foi de
~1,5 pp para ~2,0 pp: o comprador PF/fundo isento paga a isenção inteira e mais. Índice EW hedgeado de IPCA+: +5,0/+5,2/+4,1 pp
sobre CDI em 2023/24/25 (compressão de spread), −2,7 pp em 2026 (reabertura).
**Tentar**: o sinal certo é a **reversão** desse prêmio — com incentivada abaixo da NTN-B, o trade é ficar fora (ou vender
incentivada e comprar NTN-B/não incentivada do mesmo emissor). Episódios de pânico são raros (2 em 7 anos): tamanho com cuidado.

## C9 — FIIs de papel com desconto ao VP
**Tese**: em pânico o mercado vende FII de CRI abaixo do VP; compra o desconto e espera fechar. Universo: FIIs com segmento
"Títulos e Val. Mob." em ≥ 50% dos informes (inclui FoFs), giro ≥ R$500 mil/dia; VP do informe CVM a partir da **Data_Entrega**;
mensal; n vagas de 1/n do PL. Modo "pânico": só quando a mediana do P/VP do segmento < thr, compra os n mais líquidos.
**Resultado**: "barato" IS +0,4 a +4,8 / **OOS −4,4 a −6,4 pp**; "pânico" IS +0,5 a +1,0 / OOS −4,6 a 0,0. Escolhido: −7,1 pp OOS.
Por ano: 2020 +17,8 (compra em abr/20: XPCI11, MCCI11), 2021 +6,5, 2023 −20,6, 2024 −13,1, 2025 +15,8, 2026 −7,2.
**Piores**: HCTR11 Hectare (set/22 a 0,89 do VP → set/23 a 0,28, −72%, −23% do PL), AJFI11 (mar/24, −31%), DEVA11 Devant
(abr/23 a 0,56 → 0,40), MGFF11, HGFF11, IRDM11 (2024), RBRF11, BCRI11 (2026). **Melhores**: KORE11 (fev/25 0,71→0,85, +27%),
KIVO11, CPTS11, BCRI11 (todos jan-mai/25: o "pânico" de dez/24 com Selic subindo), XPSF11, XPCI11 (abr/20).
**Por quê**: o VP de FII de CRI é marcado pelo gestor e atrasa a perda; desconto grande e persistente = mercado precificando
inadimplência que o VP ainda não mostra (Hectare, Devant). O desconto "de pânico" (abr/20, dez/24) funciona, mas aparece em 2
datas. Média do segmento líquido: −5,8% em 2024 e +1,5% em 2026 até out. FI-Infra (JURO11, KDIF11...) não testado: o VP diário
exigiria baixar o informe diário de todos os fundos (GBs); fica para depois.

## Ideia 8 (CRA/CRI × debênture do mesmo devedor) — não testável com o que temos
O `balcao.parquet` identifica o CRA/CRI pela securitizadora (ECOAGROSEC, etc.), não pelo devedor; o cadastro de CRA/CRI com o
devedor (B3/CVM "Informe Mensal de CRA/CRI") seria necessário. Fica registrado.

## O que levar daqui
1. **O prêmio de crédito existe e é o resultado**: o índice EW hedgeado deu +2,3 pp/ano OOS com 2,4% de vol. C3 (carry) só repete
   isso com mais concentração. Para um fundo próprio, um livro amplo de debêntures DI líquidas, hedge de IPCA+ em DAP e **sem**
   regra de stop (a faca caindo custou dinheiro em todas as variantes) é a base.
2. **A melhor informação de crédito é para VENDER risco**: C6 só-venda e os piores negócios de C1/C3/C4 apontam o mesmo grupo
   (saúde 2024-26, Ambipar, CSN, Braskem, Aeris). Próxima rodada: livro de crédito + venda de ação dos emissores cujo spread abre.
3. **Distressed pagou em saúde 2023-24 e devolveu em 2025**: precisa de análise de caso (garantia, dono, plano), não de regra.
4. Dados: `pct_curva` do SND não serve sozinho; a taxa do balcão B3 (2023+) é melhor. Qualquer pesquisa nova deveria marcar pela
   taxa do balcão e usar compra-e-segura.
