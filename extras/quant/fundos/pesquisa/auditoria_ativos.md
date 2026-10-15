# Auditoria (red team) dos candidatos ao "top 5" — out/2026

Código: `ideias_aud_ativos.py` (versões corrigidas, sufixo " [auditado]"). Resultado: `resultado/ideias_aud_ativos.pkl`
(com `contrib` e `trades`), log em `resultado/ideias_aud_ativos_log.txt`. Nenhum arquivo existente foi alterado.
Números "OOS" = retorno ativo a.a. sobre o CDI, líquido de custos e despesas, parâmetros escolhidos só no IS.

## Resumo

| Candidato | Rodada final | Auditado | Veredito |
|---|---|---|---|
| C4 Mineradoras vs metal | +5,4 pp, IR 0,90 (selic_corte) | +2,7 pp, IR 0,59 (processo padrão: 126/2,0 + selic_corte); +11,7 pp, IR 1,01 sem regime genérico (63/1,0); mediana das variantes +3,5 a +5,2 | **APROVADO COM CORREÇÃO** |
| 06 Crédito offshore (eurobonds) | +3,8 pp, IR 0,59 (selic_corte) | +3,6 pp, IR 0,44 (n=15, sem regime); P 88% | **APROVADO COM CORREÇÃO** (é carrego de HY BR, 1 ciclo) |
| A2 Eurobonds BR em stress | +1,9 pp, IR 0,23 | +2,3 pp, IR 0,33 (selic_corte) / +2,9, IR 0,29 sem regime; IS IR ≈ 0 | **REPROVADO** (redundante com o 06, IS nulo) |
| I7 Eurobonds BR safra | +1,4 pp, IR 0,27 | +2,7 pp, IR 0,35 | **REPROVADO** como fundo separado (mesmos bonds do 06) |
| C4 Distressed debêntures | +4,4 pp, IR 0,83 (selic_corte) | −3,9 pp, IR −0,33; sem regime o ORIGINAL já era −0,5 pp | **REPROVADO** |
| IM2 Reversão Japão (VIX alto) | +5,7 pp, IR 0,57 (hmm_ibov) | 6 de 8 variantes negativas no OOS; IS ≈ 0; sem SoftBank +3,1 | **REPROVADO** |
| 01 Caixa sintético (box) | +0,4 pp, IR 9,76 | +1 dia: −14,8 pp; o box "barato" não existe no dia seguinte | **REPROVADO (artefato)** |

Achado transversal: **o regime genérico é o que fabrica os resultados "bons demais"**. Em 3 dos 5 candidatos o
regime escolhido no IS (selic_corte, hmm_ibov) não tem relação econômica com o ativo e responde por quase todo o OOS.
E `com_regime` cobra 10 bps para ligar/desligar 100% do livro — irreal para eurobonds HY (~2 pts ida e volta) e
debêntures estressadas (2 × 2,5%). No auditado, o custo de troca é 0,1% (ETFs), 2% (eurobonds) e 5% (debêntures).

---

## 1. C4 Mineradoras vs metal — APROVADO COM CORREÇÃO

**(a) Reentrada no mesmo dia — CONFIRMADO.** `ideias_commodities.histerese` zera a posição por prazo (tmax=120) ou
stop (|z|>4) e, na MESMA linha, testa a entrada de novo: se |z| continua > z_in, reabre. Como o z é semanal (constante
na semana), o limite de 120 dias nunca existia. Evidência: negócios de 175, 179 e 211 dias (COPX×CPER vendido
ago/25→jun/26, −6,7 pp; SIL×SLV vendido 2016, −4,6 pp). `negocios()` nem separava esses trechos, porque o sinal não
muda. Correção (`histerese_aud`): saída por prazo/stop bloqueia o mesmo lado até o z cruzar de volta o z_out (0).

**(b) Futuros com salto de rolagem.** Na variante escolhida ('pares') não há futuro: TIO=F só entra na variante
'minerio' (que retirei da grade) e HG=F não é usado (o cobre é o ETF CPER). **Mas achei outro bug de dado:** o CPER
tem 2 prints errados (04/12/2014 −33% e +50% no dia seguinte; 02/02/2015 −29%/+46%). `limpa(r, .45)` zerava o +50%
e mantinha o −33% → P&L falso de ~+33% no vendido em CPER (o melhor negócio do IS, COPX×CPER 2014, +4,4 pp, vinha
daí). Correção: limpeza em NÍVEL (`base._limpa_niveis`, lim 15%) nas pernas antes do retorno.

Efeito das correções (sem regime, jan=126, z=1,0): original IS 6,2% / OOS 6,0%; só histerese 4,5/4,1; só limpeza 4,5/4,9;
ambas 2,8/3,3 (IR OOS 0,39).

**(c) Pares com conhecimento posterior.** Os 6 pares são o par "de livro" de cada metal (todos os ETFs existem desde
2009–2011), não vi garimpo. Mas o resultado depende de GDXJ×GDX na variante 126: deixa-um-fora, OOS cai de 3,3 para
1,1% sem ele. Na variante 63 nenhum par é decisivo (sem qualquer um, OOS entre 7,6 e 11,9%).

**(d) selic_corte — sorte de escolha.** Ligado só 31% do OOS; não tem tese (ciclo do Copom x mineradora em dólar).
Tabela de regimes (versão corrigida 126/1,0, OOS a.a. / IR): nenhum 3,3/0,39; selic_corte 4,3/0,90; dd_stop 4,9/0,60;
ibov_tendencia 4,8/0,64; risco_global 0,3/0,08; credito_ok 0,0/0,04. A dispersão entre regimes é do tamanho do sinal.
O regime "ganha" no IS e por acaso também no OOS; não conte com ele.

**(e) Concentração.** Pequena: os 2 melhores negócios OOS são 15% (original) e 8–27% (corrigido) do OOS. O FCX×cobre de
mar/2020 (+3,1 pp) é IS. No OOS o maior evento é a tarifa do cobre (jul/2025: CPER −19% em 30/07) — COPX/FCX comprados
contra CPER, +4,8 pp na variante 63 (real, mas evento único).

**Números corrigidos** (`C4 Mineradoras vs metal [auditado]`, grade jan {63,126} × z_in {1,2}):
- processo padrão (regime no IS): 126/2,0 + selic_corte → OOS +2,7 pp, IR 0,59, P 96%, PBO 18%, custo×2 +2,5, +1d +2,3;
- sem regime genérico: 63/1,0 → +11,7 pp, IR 1,01, P 98%, PBO 27%; 100% das variantes batem o CDI; mediana +5,2.
- Por ano (63/1,0): 2021 +15, 2022 +3, 2023 +21, 2024 +13, 2025 +3, 2026 +9,5. Vol ~10%.
Recomendação: usar SEM regime genérico (ou dd_stop), expectativa honesta +3 a +6 pp a.a., IR 0,4–0,7.

## 2. Eurobonds BR (06 / A2 / I7) — 06 APROVADO COM CORREÇÃO; A2 e I7 REPROVADOS

**O que estava errado.**
1. `PE` é o print FINRA com `ffill(limit=5)`: após 5 dias sem negócio o retorno some (NaN → 0) e o salto do gap é
   perdido; o livro 06/A2 vende por "sumiu" (3 dias sem print) ao último preço e recompra dias depois — 53 de 64
   negócios do 06 saíam assim. Andrade Gutierrez 9% 2029 (print em 9,7% dos dias, preço 22–43) foi entrada e saída ~20
   vezes = 45% do OOS do 06 (atribuição). B2W (13% dos dias) idem.
2. Entrada no próprio print da decisão (fechamento de t−1 executado em t−1): não há t+1.
3. Cupom acumulado todo dia mesmo a 23 (AG): bond em default negocia "flat" → carrego falso de ~35% a.a. no preço.
4. Custo 0,25% por lado para HY/distressed (real: 0,5–2 pts).
5. O teste "+1 dia" do motor nesses fundos só desloca a série de retornos (`r.shift(lag)`): não testa execução.

**Reprecificação (`_eb_base`, `_eb_livro_aud`).** Marca = último print (sem limite, compra-e-segura, nada de vender por
"sumiu"); entra/sai só com print "vivo" (mudou nos últimos 5 dias úteis) e liquidez (≥ 40% dos dias com print em 63d —
exclui AG, B2W novos, Rumo/Klabin ilíquidos); execução no 1º print entre t+1 e t+5; bid/ask meia ponta 0,5 (≥90),
1,0 (75–90), 1,5 (50–75), 2,0 pts (<50); sem cupom abaixo de 50. Hedge cambial (DOL) e de Treasury reconstruídos do
painel original (erro < 1e-8). Lag agora é atraso real de execução.

**Resultado.** Surpresa honesta: o 06 SOBREVIVE. Sem AG o OOS quase não muda (3,0 → 3,3–3,6 pp), porque compra-e-segura
elimina o vai-e-vem e o bid/ask maior é compensado por não pagar giro. AG não entra (liquidez); no 06 auditado o OOS
vem de MC (+3,9), Petrobras (+2,6), Raízen (+2,5), Hidrovias (+2,0), BRF, Açu; perda real em B2W (comprado a 69 em
out/2022, marcado a 14: −8,2 pp no total — o original "escapava" do calote da Americanas vendendo por "sumiu").
- 06 auditado: n=15, regime 'nenhum' (com custo de troca real o regime não compensa) → **+3,6 pp, IR 0,44, P 88%**,
  custo×2 +3,1, +1d +3,7. IS IR só 0,16 (2021–23 foi a alta de juros). É carrego de crédito HY BR com hedge, um ciclo
  de fechamento de spread (2023–24): aprovado como sleeve de carrego, não como alfa.
- A2 auditado: +2,3 pp, IR 0,33 (selic_corte) / +2,9, IR 0,29 sem regime; IS IR 0,02–0,04. Reprovado.
- I7 auditado: +2,7 pp, IR 0,35, IS IR 0,90 (safra 2020). Mesmos bonds (MC, Hidrovias, BRF, Simpar, Movida,
  Petrobras) do 06 → não é fundo separado. Reprovado como fundo; pode ser regra de dimensionamento do 06 (aumentar
  o livro após stress sistêmico).

## 3. C4 Distressed / recuperação (debêntures) — REPROVADO

**O que estava errado.**
1. **O resultado inteiro é o regime.** Sem regime, o ORIGINAL (thr 80, todos) já dá IS +0,95% / **OOS −0,5% a.a.** O
   +4,4 pp vem de `selic_corte` desligar o livro em 2025 (Selic subindo/parada em 15%), exatamente quando Aeris (−8,1 pp),
   Ambipar (−8,2 pp, RJ set/2025) e Braskem (−4,4 pp) quebraram. Escolhido num IS com um único ciclo de corte (2019–20),
   e executado a 10 bps de custo de troca num livro de debêntures estressadas — impossível.
2. Marca parada: `Pf = P.ffill()` mantém o %PU da curva e o PU continua acumulando CDI+spread todos os dias sem negócio
   (SEQL13 ficou 644 dias sem negócio na carteira, HSPA12 450 dias). Correção: marcação pelo PU em R$ do último negócio
   (o acréscimo só aparece se houver outro negócio).
3. Liquidez: entrava com giro de R$ 500 mil em 21 dias para uma posição de 10% do PL. Correção: ≥ R$ 5 mi/21d e negócio
   ≥ R$ 300 mil no dia da execução (entrada e saída).
4. Custo: já era 1% por lado (não 20–50 bps); para distressed usei 2,5%.
5. "PU que só aparece por negócio posterior": `_limpa_precos` só confirma o print com negócio POSTERIOR e só a partir
   daquele dia — sem look-ahead. Amortização: o %PU da curva pode errar (UNIP15/TAEE17); a confirmação pelo balcão B3
   cobre 2023-04+; antes disso o erro existe, mas é IS.

**Números corrigidos** (`C4 Distressed / recuperação [auditado]`): OOS **−3,9 pp, IR −0,33**, P 26%, custo×2 −6,3,
+1d −7,1; nenhuma das 6 variantes bate o CDI. Isolando: marca PU −1,5 (custo 1%) → custo 2,5% −2,8 → liquidez −3,3 a.a.
de excesso. Os ganhos reais existem (CBRD/GPA +2,1, DASA +2,2, Hosp. Anchieta +2,1, Livetech +2,1, Kora +1,6), mas as
2–3 quebras por ciclo comem tudo.

## 4. IM2 Reversão em large caps (Japão, VIX alto) — REPROVADO

- **Seleção:** das 8 variantes da grade (L 5/21 × VIX 0/1 × jp/todas), 6 são negativas no OOS; L=5 perde em IS e OOS
  (−3 a −16% a.a.). Só "jp, L=21, VIX alto" é positiva: IS −0,4% a.a. (IR 0,02), OOS +5,4%. O IS IR 0,33 que levou à
  escolha vem do regime **hmm_ibov** (HMM do Ibovespa para uma carteira de ações japonesas) — sem sentido econômico.
- **SoftBank:** 28% do OOS (+9,2 pp de 32 pp somados), +6,5 pp só em nov/2025 (vendido após a alta de out/2025; o vendido
  rendeu 44% em 18 pregões). Sem SoftBank: OOS +3,1% (IR 0,38).
- **Universo:** lista ATUAL do JP60 (sobrevivência). Toshiba (6502.T, fechou o capital em dez/2023) nem tem dado; as
  59 restantes têm série completa 2009–2026, ou seja, nenhuma "morta" no universo.
- **Horário/custo:** fechamento de Tóquio t+1 com VIX de NY de t (conhecido antes) — ok. Custo não é o problema
  (×4 ainda +3,1), o problema é que o sinal não existe no IS.

## 5. 01 Caixa sintético (box) — REPROVADO (artefato)

- Excesso = peso × (taxa travada − CDI) acumulado até o vencimento, **sem marcação a mercado**: vol OOS 0,03% a.a.,
  zero dias negativos, IR 14 (9,8 no motor).
- A "taxa travada" vem de 4 melhores ofertas de fechamento não simultâneas. Dos 98 sinais de compra (edge > 0,3 pp),
  o mesmo box só tem as 4 ofertas no dia seguinte em 1% dos casos, e a taxa implícita do d+1 é absurda (mediana +320 pp
  a.a.); dos 78 de venda, 40% existem no d+1 e 0% ainda têm edge positivo. Executando no d+1: **−14,8% a.a.**
- Ganho máximo crível +0,3–0,5 pp a.a. com risco de exercício antecipado (calls americanas de ações) e de lote: não
  vale a operação. Excluir do ranking (mesma família do termo já excluído).

## O que tentar em seguida
1. Tirar os regimes genéricos da grade de qualquer fundo de crédito e usar custo de troca real em todos (`custo_troca`
   por classe de ativo em `com_regime`).
2. Mineradoras: fixar 63/1,0 sem regime e acompanhar em paper trading; acrescentar pares de mineradoras de ouro
   australianas/canadenses (GDXJ já cobre) e testar meia-vida do z antes de aumentar o risco.
3. Eurobonds: o 06 auditado é a base; usar o gatilho de stress do I7 como regra de tamanho (livro maior após stress).
