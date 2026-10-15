# Auditoria (red team) — candidatos event-driven ao top 5

Data: 15/10/2026. Pedido do dono: "top 5 sem bug". Trabalho: derrubar o que é bom demais.
Código: `ideias_aud_eventos.py` (versões corrigidas, `python ideias_aud_eventos.py medidas` reimprime as medições).
Resultado: `resultado/ideias_aud_eventos.pkl` (4 fundos "[auditado]", com contrib e trades, rodados com a dimensão de regime como a rodada final).
Scripts de medição avulsos ficaram no scratchpad da sessão; tudo o que importa está reproduzível pelo módulo.
Convenção: "ativo" = pp a.a. sobre o CDI no OOS (2021-01 em diante); "fixo" = parâmetros do candidato, sem re-seleção.

## Veredito

| fundo | publicado (rodada final) | corrigido, parâmetros fixos | corrigido, protocolo completo (re-seleção IS + regime) | veredito |
|---|---|---|---|---|
| G3 Spin-offs | +8,9 pp, IR 1,40, DD −4,1 | **+4,3 pp, IR 0,67, DD −5,4** (hedge 50/50, sem preço = −30%) | −0,5 pp, IR −0,16 (o IS corrigido fica negativo e o regime escolhido vira `inv_risco_global`) | **APROVADO COM CORREÇÃO, rebaixado** — metade do número; sem os 5 maiores ≈ 0 |
| E3 Follow-on vendido | +5,6 pp, IR 0,54, DD −12,3 | +1,7 a +5,2 pp conforme aluguel/hedge | **+2,1 pp, IR 0,24, DD −13,0**, custo x2 −0,8 pp | **REPROVADO** (para top 5) |
| E7 Rebalanceamento Ibov | +1,8 pp, IR 0,97, DD −1,1 | igual (sem bug) | — (não precisou de correção) | **APROVADO**, mas pequeno e concentrado |
| IE06 Índices EUA | +6,3 pp, IR 0,49, DD −13,1 (rodei pelo executor: regime `nenhum`) | +4,4 pp, IR 0,36, DD −13,1 | −3,6 pp, IR −0,93 | **REPROVADO** |
| IE08 PEAD Ásia | +2,9 pp, IR 0,33 sem regime; **−2,5 pp, IR −0,39 pelo executor** (regime `selic_corte`) | −1,0 pp, IR −0,07 (hedge na cesta dos sobreviventes) | −1,7 pp, IR −0,32 | **REPROVADO** |

Achado transversal (não corrigido, `regimes.py` é intocável): `_dd_stop` desliga a exposição do dia i com a curva até o fechamento de i−1,
ou seja, executa no MESMO fechamento em que vê a queda (deveria ser t+1). Efeito medido em G3: −0,3 pp/ano (8,9 → 8,6 com 1 dia de atraso).
Pequeno, mas vale para todos os fundos que escolheram `dd_stop`. Corrigir com `_dd_stop(e).shift(1)`.
Segundo achado transversal: a dimensão de regime (12 opções x grade) amplifica qualquer viés do IS. Em G3, assim que o IS é corrigido,
o regime escolhido muda e o OOS some — o "dd_stop" escolhido no publicado foi sorte de um IS inflado.

---

## G3 — Spin-offs após a venda forçada

**Checagens que passaram.** (i) Data de entrada: `espera` pregões depois do 1º preço do Yahoo — informação pública; GEV, por ex., entra em
24/05/2024, 40 pregões depois do início de negociação. Sem look-ahead. (ii) A lista vem do índice EDGAR (Form 10-12B, data de arquivamento) —
ponto no tempo. O ticker é escolhido como o mais frequente nos Forms 3/4 de qualquer época (informação futura), mas só para identificar o papel.
(iii) Beta: o excesso diário OOS tem beta 0,02 ao SPY e 0,00 ao IWM — o hedge neutraliza o mercado.
(iv) `carteira_eventos` encerra a posição na véspera de o preço sumir (`P.shift(-1)`): 1 dia de antecipação na deslistagem — irrelevante aqui.

**Viés de sobrevivência — medido.** CIKs com 10-12B, com ticker (Forms 3/4), com preço Yahoo, e que NEGOCIARAM (insiders arquivando > 90 dias)
mas sumiram do Yahoo:

| ano | 10-12B | com ticker | com preço | negociou e sumiu |
|---:|---:|---:|---:|---:|
| 2006 | 21 | 15 | 8 | 7 |
| 2007 | 33 | 25 | 7 | 16 |
| 2008 | 42 | 26 | 9 | 15 |
| 2009 | 21 | 11 | 4 | 7 |
| 2010 | 20 | 15 | 8 | 7 |
| 2011 | 27 | 19 | 8 | 10 |
| 2012 | 21 | 18 | 7 | 11 |
| 2013 | 30 | 25 | 13 | 12 |
| 2014 | 37 | 28 | 11 | 17 |
| 2015 | 46 | 39 | 18 | 20 |
| 2016 | 31 | 22 | 16 | 5 |
| 2017 | 10 | 8 | 2 | 6 |
| 2018 | 26 | 25 | 15 | 9 |
| 2019 | 36 | 14 | 11 | 3 |
| 2020 | 16 | 11 | 8 | 3 |
| 2021 | 20 | 19 | 14 | 5 |
| 2022 | 20 | 19 | 17 | 2 |
| 2023 | 19 | 14 | 11 | 2 |
| 2024 | 17 | 14 | 12 | 1 |
| 2025–26 | 27 | 19 | 19 | 0 |

No IS (2006–2015) faltam MAIS spin-offs do que existem. Destino dos que sumiram (EDGAR: DEFM14A/SC 14D9/SC TO-T = comprada; 25-NSE/15-12 = deslistada):
110 de 158 (70%) comprados depois, 28 (18%) deslistados por outro motivo, 20 sem registro de saída. No OOS os que faltam são, de memória de mercado, quase todos perdedores na janela:
LYLT (Loyalty Ventures, −85% e falência), TSVT (2seventy, ~−50%), ZIMV (ZimVie, ~−60%), MURA, TWNP; positivos AAN, AIRC, KLG. VSCO e OCTO
faltam por falha de download (ainda negociam) — o cenário os trata como os demais.

**Cenários (parâmetros fixos espera=40, dias=126; "nenhum" = sem regime):**

| cenário | IS pp (IR) | OOS pp (IR) | DD OOS |
|---|---|---|---|
| publicado (hedge IWM, sem os faltantes) | +4,6 (0,94) | +9,4 (1,46) | −4,5 |
| hedge SPY | — | +6,7 (0,96) | −7,1 |
| hedge 50/50 SPY+IWM | +4,3 (0,88) | +8,1 (1,24) | −5,3 |
| faltantes com preço parado (0%) | +2,1 (0,24) | +9,2 (1,32) | −4,4 |
| faltantes −15% | −4,7 (−0,39) | +7,6 (1,11) | −4,7 |
| faltantes −30% | −12,2 (−1,14) | +5,8 (0,85) | −5,2 |
| faltantes = média do pior decil (−40%) | — | +4,3 (0,65) | −5,6 |
| **50/50 + faltantes −30% (versão auditada)** | −12,4 (−1,29) | **+4,3 (0,67)** | −5,4 |
| sem os 5 maiores OOS (SNDK, RHLD, GRAL, TRAX, Q) | — | +4,6 (0,82) | −4,5 |
| 50/50 + −30% + sem os 5 maiores | — | −0,3 (−0,03) | −5,4 |

IWM − SPY no OOS = −7,5 pp/ano: com GEV/CEG/SNDK (large caps) na carteira, o hedge em IWM ganha o fator tamanho — 1,3 pp do resultado.

**O que estava errado:** (1) o IS (IR 0,94) é quase todo viés de sobrevivência — com a hipótese mais branda (faltante = preço parado) cai para 0,24;
(2) a escolha do regime `dd_stop` vem desse IS; (3) concentração: 5 negócios (SNDK +272%, RHLD +195%, GRAL +150%, TRAX +120%, Q +87%)
fazem metade do OOS; (4) hedge IWM adiciona fator tamanho. **O que é real:** no OOS a cobertura é 74–100% e, mesmo com −30% nos faltantes,
sobra +4 pp com IR 0,67 e DD −5%. **Uso:** só como livro pequeno, parâmetros fixos (40/126), sem overlay de regime, hedge 50/50, sabendo
que a média vive de 1–2 "SNDK" por ano. A versão `[auditado]` no pkl passa pelo protocolo completo e dá −0,5 pp — registro honesto de que,
com IS corrigido, o protocolo não escolheria esta configuração.

---

## E3 — Follow-on vendido (Brasil)

**Datas.** Sinal = Data_Entrega do 1º FR de oferta no IPE (90 dias por empresa); só 6% desses 1ºs FRs já são a precificação, o resto é
lançamento/"potencial oferta" — a entrada (fechamento seguinte) é durante o bookbuilding, sem look-ahead. 235 eventos, 116 no OOS.
Res. CVM 160 (antes ICVM 400 art. 48) só proíbe venda a descoberto a quem participa da oferta — nós não participamos.

**Aluguel — o ponto fraco.** O modelo usa 1/3/8% a.a. por ADV. Os 5 maiores ganhos do OOS são IRBR3 (ago/22, −46%), VIIA3 (set/23, −42%),
AZUL4 (mar/25, −34%), CVCB3 (jun/22 e jun/23, −27%/−25%) — todos papéis com aluguel muito acima de 8% na época (empresa em oferta,
alavancada, doadores retirando). Não há base pública offline de taxa do BTC por papel; sensibilidade (hold 20, n_max 5, credito_ok):

| aluguel mínimo | OOS pp | IR |
|---|---|---|
| modelo (1–8%) | +7,3 | 0,69 |
| 5% | +6,5 | 0,62 |
| 10% | +5,2 | 0,51 |
| 20% | +2,4 | 0,27 |
| 30% | −0,2 | 0,03 |

**Beta/tamanho.** Excesso OOS: beta Ibov 0,04, beta (SMLL − Ibov) −0,14; SMLL − Ibov OOS = −9,1 pp/ano. Vender small cap contra Ibovespa
em 2021–22 ganha o fator tamanho. Hedge 100% SMAL11: +3,7 pp; hedge por beta 252d: +7,9 pp (o beta não é o problema, o tamanho é).
Versão auditada: ADV ≥ R$50 mi contra Ibov, resto contra SMAL11, aluguel ≥ 10%.

**Concentração:** sem os 5 maiores OOS: +2,6 pp (IR 0,30). 20 negócios/ano a 19% do PL cada — um squeeze (CASH3 jun/21 +47% = −6,8% do PL) dói.

**Resultado corrigido (protocolo completo):** +2,1 pp, IR 0,24, DD −13,0%, custo x2 −0,8 pp, +1 dia +1,1 pp, P(bater) 69%.
**Veredito: REPROVADO para o top 5.** A tese existe (o retorno médio pós-oferta é negativo), mas depois de aluguel realista e do fator
tamanho sobra pouco, com cauda de squeeze. Próximo: conseguir taxa do BTC (B3, empréstimo de ativos) e excluir papéis com taxa > 15%.

---

## E7 — Rebalanceamento do Ibovespa

**Checagens.** (i) `ibov_proxy(d)` usa NEG/V/P só até `d` (fatia `[d−252, d]`), decisão em `d`, execução em d+1 — ponto no tempo.
(ii) A carteira "velha" também é proxy (da data de referência anterior), não a carteira real — gera ruído (entrante que já está no índice),
não viés. (iii) Entrada 10 pregões antes do fim: as prévias da B3 já saíram — o preço de entrada é pós-prévia, o que é realista (não se
reivindica o salto do anúncio). (iv) Painel COTAHIST com deslistados e dividendos: sem sobrevivência.
(v) Datas: o código usa "1º pregão do mês" como vigência. O pico de volume dos entrantes cai na data do código em ~1/3 das revisões e
1–8 pregões depois nas outras (sinal ruidoso porque o proxy erra entrantes). Em janeiro o "último pregão" do código é 31/12, dia SEM pregão
na B3 (a saída efetiva é 30/12) — inofensivo.
**Sensibilidade à data de saída (OOS):** −1 pregão +1,8 pp; código +2,0; +1 +1,4; +2 +0,3; +3 −0,1. A pressão reverte logo após a troca:
sair atrasado mata o ganho. Custo x2 +1,7 pp; +1 dia +1,4 pp. Sem os 5 maiores OOS (IRBR3 abr/23 +32%, AMER3 ago/22 +25%, BIDI11 abr/21
+23%...): +0,7 pp, IR 0,48. Exposição bruta média 2,7% do PL.
**Veredito: APROVADO** (sem bug). OOS +1,8 pp, IR 0,97, DD −1,1%. É pequeno porque quase não usa capital — pode ser alavancado
(5x = ~13% do PL bruto médio) com teto de liquidez; mas o IR verdadeiro é mais perto de 0,5–0,7 (concentração).

---

## IE06 — Inclusão/exclusão S&P 500 e Nasdaq-100

**Datas da Wikipédia:** são EFETIVAS. Volume / mediana em torno da data: pico no dia −1 em 210 de ~260 entrantes do S&P (20x a mediana)
e em 129 de 139 do Nasdaq-100 — é o fechamento em que os fundos de índice negociam. A fase "pos" executa nesse fechamento (MOC): correto.
A data de anúncio (fase "pre") vem das notas de rodapé.

**Bug 1 — ticker reciclado (corrigido).** Quando o CIK da empresa sumiu da SEC, o preço é buscado pelo ticker da época, e o Yahoo devolve
quem tem o ticker HOJE. 11 eventos com preço na data estavam errados (todos no IS): MNST nov/2008 (era Monster Worldwide, preço = Monster
Beverage), KG 2010 (King Pharma), SII 2010 (Smith Intl), GENZ 2011, EP 2012 (El Paso), CPWR 2011 (Compuware), e AVGO/GOOG/FTI (mesma
linhagem, removidos por precaução). Regra: CIK fora da SEC e (ticker hoje de empresa de outro nome, ou sem dono na SEC mas com preço até hoje).
Efeito: IS 6,5 → 5,8 pp; OOS inalterado.

**Bug 2 — excluídas que quebraram somem (corrigido com −50%).** Cobertura das excluídas: IS — compradas 102/264, outras 83/92,
quebradas 16/31; OOS — compradas 30/75 (neutro: preço preso ao da oferta), outras 84/85, quebradas 3/5 (faltam FRC e SIVB, 2023).
A regra "compra a excluída por 20 pregões" teria comprado Lehman, WaMu, GM, FRC, SIVB. Com −50% em 20 pregões para as quebradas sem preço:
IS +5,8 → −0,6 pp (IR 0,00); OOS +6,5 → +4,4 pp (IR 0,36).

**Concentração:** OOS = Nasdaq-100 (+42,9% de contribuição somada) contra S&P (−6,7%). Maiores: RIVN comprada após sair (jun/23, +65%),
e 4 entrantes vendidos no mesmo dia (18/06/2026: RKLB, CRWV, MRVL, NBIS, +42–54% cada) — 40% do PL num único evento.
Sem os 5 maiores OOS: +2,2 pp, IR 0,23.
**Veredito: REPROVADO.** O IS era sobrevivência (excluídas da crise de 2008 que sobreviveram) + 6 tickers de outra empresa; corrigido,
o IS é zero e o protocolo escolhe `inv_risco_global` com OOS −3,6 pp. O OOS fixo (+4,4, IR 0,36, DD −13%) é um punhado de reversões do
Nasdaq-100.

---

## IE08 — PEAD Ásia (Japão, Coreia, Hong Kong)

**Viés:** universo = membros ATUAIS (Wikipédia). Deriva de sobrevivência medida = cesta igualitária dos membros atuais − índice local:

| mercado | IS 2014–20 (pp a.a.) | OOS 2021+ |
|---|---|---|
| JP | −0,4 | +3,2 |
| KR | +2,3 | +1,8 |
| HK | +10,9 | +3,4 |

O livro é assimétrico: 1.281 negócios comprados (ret − hedge +2,4% IS / +1,9% OOS) contra 871 vendidos (−1,9% / −0,6%); a perna
comprada é ~todo o resultado e é justamente a que herda a deriva. Correção: hedge de cada nome contra a cesta igualitária dos MESMOS
sobreviventes do mercado (10 bps) — remove o viés comum (não remove o viés condicional "quem teve surpresa boa virou membro", que é
para o mesmo lado; logo o número corrigido ainda é teto).
**Números (JP+KR+HK, 8%, 60d, sem regime):** original IS +1,8 pp / OOS +3,0 pp (IR 0,35); com hedge na cesta: IS +1,1 / OOS −1,0 (IR −0,07).
Pelo executor final (com regime) o ORIGINAL já dá −2,5 pp OOS (regime `selic_corte`); o auditado, −1,7 pp (IR −0,32).
**Veredito: REPROVADO.** Todo o OOS era deriva de sobrevivência da perna comprada.

---

## Lições (para não repetir)
1. Viés de sobrevivência não é "ressalva no caderno": quando a cobertura do IS é < 50%, o IS não serve para escolher parâmetro nem regime.
   Rodar SEMPRE o cenário "faltante = preço parado" e "faltante = −30%" antes de publicar.
2. Ticker da época ≠ empresa da época no Yahoo. Validar nome do dono atual do ticker quando o CIK sumiu.
3. Hedge: casar tamanho (IWM vs SPY; Ibov vs SMAL11). Em 2021–25 o fator tamanho pagou −7 a −9 pp/ano — qualquer livro "vendido small /
   hedge large" (ou o contrário) carrega isso.
4. Vendido em papel de evento: o aluguel é o custo dominante; sem taxa real do BTC o resultado é teto.
5. Sempre publicar "sem os 5 maiores" — G3, E3, IE06 e E7 perdem metade ou mais.
