# Frente: commodities e valor relativo entre ativos (hedge de mesa) — rodada 2

Código: `quant/fundos/ideias_commodities.py` (9 fundos C1-C9). Resultado: `resultado/ideias_commodities.pkl` (cada dict tem também `contrib` = contribuição diária por perna/par e `trades` = negócios com entrada, saída, dias, retorno do par e contribuição em fração do PL).

Dados novos:
- `dados/y_comm.parquet` (`dados_comm_yahoo.py`): RB, HO, ZM, ZL, GF, HE, **TIO=F (minério SGX existe no Yahoo desde out/2010)**, PA, PL, GDX, GDXJ, SIL, COPX, UGA, USL, UNL, CANE, mineradoras/petroleiras/frigoríficos EUA e ações BR .SA ajustadas por proventos (BRFS3/MRFG3/JBSS3 sumiram do Yahoo; MBRF3.SA e JBSS32.SA guardam o histórico de Marfrig e JBS).
- `dados/b3_futuros_agro.parquet` + cache diário `dados/b3_agro/` (`dados_agro.py`, mesma fonte do `quant/dados.py`): ajustes de todos os vencimentos de BGI, CCM, ICF, SJC, ETH, ETN, SOY, CNL, GLD na B3, 2018-2026. O boletim BVBG.086 só existe a partir de 2018; o site antigo de ajustes (www2.bmf) foi desligado.

## Convenções desta frente
- Tudo no calendário B3; preço dos EUA = último fechamento disponível (ffill até 5 dias). Decisão no fechamento de sexta, execução no fechamento seguinte (`executa` replica `base.carteira` e devolve contribuição e negócios).
- Ação BR financiada: r - CDI (Yahoo .SA ajustado: dividendo é custo do vendido). Commodity em R$: (1+r)(1+r_USD)-1-CDI (sem hedge cambial — a exportadora está exposta ao Brent *em reais*). Par em dólar: excesso sobre T-bill (= excesso em R$ com hedge cambial).
- Futuros contínuos Yahoo: dias com salto > 5 desvios robustos zerados (rolagem). Rolagens pequenas passam — viés a favor do vendido em mercado em backwardation (minério). ETFs sempre que havia.
- Pares: beta rolante 1 ano (retornos de 5 dias, por causa do fuso), z-score do resíduo acumulado, entra |z|>z_in, sai em 0, stop |z|>4 ou 120 dias, risco igual por par (vol-alvo 10%/raiz(n)), bruto acima de 2x paga CDI+1%.
- Custos por perna: ações líquidas 7 bps, small caps 20-30 bps, ETFs 3 bps, câmbio G10 2 bps / EM 15 bps, futuros 2 bps (agro B3 5-30 bps + rolagem mensal); aluguel 0,5% blue chip, 1,5-4% small, 0,3% ETF.

## Bugs encontrados (para não repetir)
1. `base.limpa` transforma NaN em 0: antes da listagem a ação rendia "0 - CDI" todo dia e o par virava um short perfeito do CDI (açúcar dava IS -33% a.a., SR -6,7). Corrigido mantendo NaN fora do período listado.
2. SUZB3.SA no Yahoo antes de 2018 é a ON ilíquida, parada por meses: virava -12 pp/ano no livro de exportadoras. Filtro: ação com >30% dos dias sem variação em 21 dias fica fora.
3. Carry B3 sem descontar o CDI (ver C5).
4. Download do boletim B3 com 10 processos: o servidor devolve resposta inválida e o coletor gravava arquivo vazio (857 dias "sem dados"). Agora não grava e refaz; ficaram 23 dias sem arquivo na B3.
5. COT: nomes de contratos mudaram em 2022 (WTI, gás, cobre) — mapear pelo `CFTC_Contract_Market_Code`. O `cot.parquet` começa em 2013, não 2010.

## Resumo (OOS = 2021+; C2/C5 = 2023+; benchmark CDI)
| fundo | escolhido no IS | OOS a.a. vs CDI | IR OOS | P(bater) | PBO | variantes > CDI no OOS |
|---|---|---|---|---|---|---|
| C1 Petróleo: PETR4/PRIO3 vs Brent em R$ | {'jan': 126, 'z_in': 1.0, 'conj': 'brent'} | 14.7% vs 11.4% | 0.34 | 77% | 40% | 100% |
| C2 Proteína: margem boi/milho nos frigoríficos | {'jan': 126, 'sinal': 'margem'} | 12.1% vs 13.1% | -0.16 | 35% | 90% | 75% |
| C3 Açúcar/etanol: usinas vs açúcar | {'jan': 63, 'z_in': 2.0, 'hedge': 'acucar'} | 7.6% vs 11.4% | -0.35 | 19% | 60% | 0% |
| C4 Mineradoras vs metal | {'jan': 126, 'z_in': 2.0, 'vale': 'minerio'} | 14.7% vs 11.4% | 0.37 | 80% | 59% | 100% |
| C5 Carry agro B3 (estrutura a termo) + filtro CFTC | {'modo': 'saz_ts', 'cot': 0} | -1.3% vs 13.1% | -0.93 | 3% | 69% | 0% |
| C6 Spreads clássicos de commodities | {'jan': 126, 'z_in': 1.5, 'gas': 1} | 13.7% vs 11.4% | 0.24 | 67% | 5% | 50% |
| C7 Moedas de commodities vs commodities | {'jan': 63, 'z_in': 2.0} | 11.8% vs 11.4% | 0.08 | 53% | 36% | 56% |
| C8 Exportadoras BR com hedge de commodity | {'modo': 'todas', 'jan': 126} | 10.8% vs 11.4% | -0.01 | 46% | 43% | 0% |
| C9 CFTC contrarian (especulador lotado) | {'lim': 0.95, 'saida': '50', 'confirma': 0} | -0.7% vs 11.4% | -1.08 | 0% | 66% | 0% |

**Mais promissores:** C4 (mineradora vs metal — todas as variantes positivas no OOS, sobrevive a custo x2 e a atraso), C6 restrito a crack + crush + gás de inverno (spreads com arbitragem física; PBO 5%), C1 só com PETR4 x Brent (funciona no OOS, mas perdeu no IS de 2014-16: depende de não haver choque de governança).
**Descartados:** C5 carry agro (o prêmio está do lado comprado), C9 contrarian CFTC (o especulador lotado em commodity está certo), C8 exportadoras hedgeadas como fator, C3 usinas (crédito).

## C1 Petróleo: PETR4/PRIO3 vs Brent em R$

**Tese de mesa.** PETR4 é "Brent em reais + risco Petrobras". Quando a ação fica muito para trás do Brent x dólar (resíduo da regressão rolante muito negativo: "a ação precificou um Brent a 60 e o futuro está a 80"), compro a ação e vendo BNO na proporção do beta; quando a ação andou demais à frente do petróleo, o inverso. PRIO3 (pura, sem risco político) como segundo par; variante com o par PRIO3 x PETR4.

**Implementação.** Resíduo diário = (r_ação - CDI) - beta x (BNO em R$ sem hedge cambial - CDI); beta de 1 ano em retornos de 5 dias, só passado, limitado a [0,3]. z-score do resíduo acumulado em `jan` dias, decisão semanal, entra com |z|>z_in, sai em z=0, stop em |z|>4 ou 120 dias. Risco igual por par, vol-alvo 10%. Custos: PETR4 7 bps, PRIO3 20 bps, BNO 3 bps + câmbio 2 bps; aluguel PETR4 0,5%, PRIO3 1,5%, BNO 0,3% a.a. PRIO só a partir de 2016 (antes era penny stock).

**Resultado.** Escolhido no IS com IR IS **negativo** (-0,21): nenhuma variante foi boa no IS (2014-16, Lava Jato: a PETR4 caiu muito mais que o Brent e a reversão à média apanhou). No OOS (2021+) todas as 8 variantes bateram o CDI (mediana +3,3 pp). Não é alfa comprovado: é resultado de regime.

**O que deu certo.** O par PETR4 x BNO paga quando o desvio vem de *fluxo/pânico*, não de mudança de governança: vendi PETR4/comprei BNO em 16/nov/2020 (a ação tinha subido à frente do petróleo na reabertura) e ganhei 23,5% no par em 66 dias (saída em 22/fev/2021, o dia da queda pela troca de CEO); comprei PETR4/vendi BNO em 23/mar/2020 (fundo do Covid) e o par rendeu +63% em 23 dias.

**O que deu errado.** PRIO3 x BNO perde 3,75 pp/ano no IS: PRIO é uma *compounder* (produção crescendo 30%+ ao ano), o resíduo dela tem tendência e não reverte — vender PRIO "cara vs Brent" de jul/2018 a ago/2019 custou -62% no par. Idem PETR4 vendida de mai/2023 a mar/2024 (-43%): o mercado reprecificou o risco político para baixo e o resíduo não voltou.

**Próximo passo.** Só PETR4 (e PBR vs PETR4); para PRIO usar momentum do resíduo; filtro de evento (troca de CEO, mudança de política de preços: datas de fato relevante CVM/IPE) para *suspender* a reversão.

**Números.** params {'jan': 126, 'z_in': 1.0, 'conj': 'brent'} | IR IS -0.21 | OOS 14.7% vs CDI 11.4% | IR OOS 0.34 | vol OOS 9.8% | DD OOS -11.8% | P(bater) 77% | PBO 40% | DSR 55% | custo x2 +2.3pp | lag+1 +3.3pp | mediana variantes +3.3pp | % var>CDI 100%
| perna | IS pp/a | OOS pp/a |
|---|---|---|
| PETR4 x BNO | +1.95 | +3.07 |
| PRIO3 x BNO | -3.75 | +0.40 |
negócios: 79 | acerto 67% | dias mediana 42

10 melhores:
| ativo | lado | entrada | saída | dias | retorno | contrib (pp do PL) |
|---|---|---|---|---|---|---|
| PETR4 x BNO | vendido | 2020-11-16 | 2021-02-22 | 66 | +23.5% | +6.34 |
| PETR4 x BNO | vendido | 2012-09-17 | 2012-11-19 | 42 | +22.3% | +5.72 |
| PETR4 x BNO | comprado | 2020-03-23 | 2020-04-27 | 23 | +62.9% | +4.33 |
| PETR4 x BNO | vendido | 2015-04-27 | 2015-07-27 | 63 | +24.7% | +4.27 |
| PRIO3 x BNO | comprado | 2018-04-09 | 2018-04-30 | 15 | +39.6% | +4.16 |
| PETR4 x BNO | vendido | 2019-10-28 | 2020-03-02 | 85 | +9.5% | +3.46 |
| PETR4 x BNO | comprado | 2026-06-08 | 2026-08-31 | 60 | +9.4% | +3.42 |
| PETR4 x BNO | vendido | 2025-02-03 | 2025-03-05 | 20 | +7.6% | +3.41 |
| PETR4 x BNO | vendido | 2017-05-15 | 2017-05-22 | 5 | +16.8% | +3.36 |
| PETR4 x BNO | comprado | 2025-10-27 | 2025-11-10 | 10 | +8.7% | +3.14 |

10 piores:
| ativo | lado | entrada | saída | dias | retorno | contrib (pp do PL) |
|---|---|---|---|---|---|---|
| PRIO3 x BNO | vendido | 2018-07-30 | 2019-08-19 | 264 | -62.2% | -13.11 |
| PETR4 x BNO | vendido | 2023-05-02 | 2024-03-11 | 215 | -42.7% | -11.45 |
| PETR4 x BNO | vendido | 2016-03-07 | 2017-02-15 | 240 | -60.5% | -10.96 |
| PRIO3 x BNO | vendido | 2017-08-14 | 2018-03-19 | 147 | -34.6% | -10.43 |
| PRIO3 x BNO | vendido | 2019-11-04 | 2020-03-16 | 90 | -34.6% | -9.90 |
| PRIO3 x BNO | vendido | 2016-11-28 | 2017-05-22 | 120 | -59.7% | -9.56 |
| PETR4 x BNO | comprado | 2020-03-02 | 2020-03-16 | 10 | -36.4% | -8.75 |
| PRIO3 x BNO | vendido | 2023-05-22 | 2023-11-10 | 120 | -18.0% | -4.62 |
| PETR4 x BNO | vendido | 2026-09-14 | 2026-10-13 | 21 | -13.7% | -4.29 |
| PRIO3 x BNO | vendido | 2026-01-05 | 2026-06-08 | 104 | -13.4% | -4.27 |

## C2 Proteína: margem boi/milho nos frigoríficos

**Tese de mesa.** A margem do frigorífico aparece nos futuros antes do balanço: margem bovina BR ~ carne (LE x dólar, proxy do preço de exportação) - boi gordo (BGI B3); margem de aves/suínos ~ porco (HE x dólar) - milho (CCM B3). Compro o frigorífico com margem melhorando e vendo o que tem margem piorando (long-short setorial, cada ação com hedge de Ibovespa). Variante "ciclo": boi/milho subindo = custo subindo = vende quem compra o insumo.

**Dados.** Futuros B3 BGI/CCM 2018+ (baixados do boletim BVBG.086, todos os vencimentos; índice rolado sem saltos de vencimento), LE/HE Yahoo, BEEF3, MBRF3 (o Yahoo guarda o histórico da Marfrig sob MBRF3), JBS (JBSS32 contínuo no Yahoo), BRFS3 do COTAHIST até a fusão (set/2025). Início 2019, corte 2023.

**Resultado.** IS forte (IR 1,07) mas OOS -1,0 pp vs CDI, PBO 90%: o IS foi feito quase todo por BRF em 2019-2022. A mediana das variantes no OOS é +1,7 pp e 75% delas ficaram acima do CDI — a economia da ideia parece certa, a escolha de parâmetro no IS é que falhou (a variante "ciclo" de 63 dias foi a melhor no OOS). Vol do livro baixa (5%).

**O que deu certo.** Vendido BRFS3 de ago/2022 a mai/2023: milho caro + porco/frango fraco esmagaram a margem e a ação caiu pela metade (o lado vendido rendeu +94% em 172 dias, +9,9 pp do PL). Comprado BRFS3 fev-ago/2021 (+17%) com milho cedendo.

**O que deu errado.** BEEF3 comprada ago/2022-mai/2023 (margem pela proxy parecia boa, mas a China suspendeu as compras de carne brasileira em fev/2023 (caso atípico de vaca louca)): -42%. LE (boi dos EUA) é uma proxy fraca da carne exportada pelo Brasil.

**Próximo passo.** Preço de exportação da carne bovina (Comex Stat mensal, com data de divulgação), CEPEA boi/frango/suíno, relação boi-bezerro (ciclo de retenção). Alavancar o sinal (é lento).

**Números.** params {'jan': 126, 'sinal': 'margem'} | IR IS 1.07 | OOS 12.1% vs CDI 13.1% | IR OOS -0.16 | vol OOS 4.7% | DD OOS -4.0% | P(bater) 35% | PBO 90% | DSR 13% | custo x2 -1.5pp | lag+1 -1.3pp | mediana variantes +1.7pp | % var>CDI 75%
| perna | IS pp/a | OOS pp/a |
|---|---|---|
| BEEF3 | +2.09 | -3.56 |
| MBRF3 | -0.12 | +0.20 |
| JBSS32 | +0.23 | +0.84 |
| BRFS3 | +6.86 | +1.93 |
negócios: 192 | acerto 52% | dias mediana 15

10 melhores:
| ativo | lado | entrada | saída | dias | retorno | contrib (pp do PL) |
|---|---|---|---|---|---|---|
| BRFS3 | vendido | 2022-08-22 | 2023-05-02 | 172 | +94.1% | +9.93 |
| BRFS3 | comprado | 2021-02-01 | 2021-08-23 | 140 | +17.3% | +8.05 |
| BRFS3 | vendido | 2019-09-30 | 2020-04-27 | 143 | +29.7% | +6.74 |
| BEEF3 | comprado | 2019-01-07 | 2019-03-25 | 53 | +27.0% | +5.33 |
| BRFS3 | comprado | 2019-05-06 | 2019-09-30 | 104 | +14.5% | +3.84 |
| BEEF3 | vendido | 2020-09-14 | 2020-10-26 | 29 | +19.1% | +3.15 |
| BEEF3 | comprado | 2021-09-06 | 2022-02-21 | 116 | +20.0% | +3.12 |
| BEEF3 | comprado | 2019-09-30 | 2020-04-27 | 143 | +48.0% | +2.52 |
| BRFS3 | vendido | 2021-09-06 | 2022-02-21 | 116 | +14.3% | +2.43 |
| BRFS3 | comprado | 2024-04-01 | 2024-07-01 | 63 | +46.7% | +1.83 |

10 piores:
| ativo | lado | entrada | saída | dias | retorno | contrib (pp do PL) |
|---|---|---|---|---|---|---|
| BEEF3 | comprado | 2022-08-22 | 2023-05-02 | 172 | -42.5% | -4.92 |
| BEEF3 | comprado | 2023-10-23 | 2024-02-26 | 84 | -19.5% | -2.93 |
| BEEF3 | comprado | 2025-07-14 | 2026-02-23 | 155 | -15.6% | -2.66 |
| BRFS3 | comprado | 2020-09-14 | 2020-10-26 | 29 | -14.2% | -2.18 |
| BEEF3 | vendido | 2019-05-06 | 2019-09-30 | 104 | -4.1% | -1.98 |
| BEEF3 | vendido | 2022-03-28 | 2022-08-22 | 102 | -25.3% | -1.96 |
| BEEF3 | vendido | 2021-02-01 | 2021-08-23 | 140 | -8.2% | -1.24 |
| BEEF3 | comprado | 2023-08-21 | 2023-09-18 | 19 | -20.2% | -1.04 |
| BRFS3 | vendido | 2019-01-07 | 2019-03-25 | 53 | -2.6% | -1.01 |
| BEEF3 | vendido | 2024-02-26 | 2024-03-25 | 20 | -9.6% | -0.81 |

## C3 Açúcar/etanol: usinas vs açúcar

**Tese de mesa.** Usina = açúcar + etanol em reais. Quando SMTO3/RAIZ4/JALL3 descolam do açúcar (CANE em R$), aposto na volta com hedge no açúcar; variante com 40% de gasolina (UGA) porque o etanol segue a paridade com a gasolina.

**Resultado.** IS bom (IR 0,88, praticamente só SMTO3 2012-2020) e OOS ruim (-3,8 pp; 0% das variantes acima do CDI).

**O que deu errado (concreto).** 2024-2026: Raízen e Jalles entraram em crise de alavancagem/crédito; o resíduo "barato vs açúcar" ficou cada vez mais barato — comprei RAIZ4 em out/2024 e jul/2025 e perdi 38%-46% no par; JALL3 -44% a partir de out/2024. Reversão à média contra empresa com balanço deteriorando é vender put sem saber.

**O que deu certo.** Vendido RAIZ4 vs açúcar em abr/2022 (+33% em 17 dias, oito meses depois do IPO); SMTO3 nos dois sentidos em 2012-2018.

**Próximo passo.** Filtro de crédito: spread das debêntures do emissor em `snd_negocios`/`balcao` (se abriu, não compra o resíduo) — o mercado de dívida avisou antes. SMTO3 sozinha continua candidata.

**Números.** params {'jan': 63, 'z_in': 2.0, 'hedge': 'acucar'} | IR IS 0.88 | OOS 7.6% vs CDI 11.4% | IR OOS -0.35 | vol OOS 8.9% | DD OOS -20.2% | P(bater) 19% | PBO 60% | DSR 10% | custo x2 -4.6pp | lag+1 -3.9pp | mediana variantes -3.7pp | % var>CDI 0%
| perna | IS pp/a | OOS pp/a |
|---|---|---|
| SMTO3 x acucar | +3.93 | -0.64 |
| RAIZ4 x acucar | +0.00 | -1.78 |
| JALL3 x acucar | +0.00 | -0.56 |
negócios: 71 | acerto 65% | dias mediana 32

10 melhores:
| ativo | lado | entrada | saída | dias | retorno | contrib (pp do PL) |
|---|---|---|---|---|---|---|
| RAIZ4 x acucar | vendido | 2022-04-12 | 2022-05-09 | 17 | +33.4% | +4.93 |
| SMTO3 x acucar | vendido | 2014-09-01 | 2014-10-06 | 25 | +18.7% | +3.89 |
| JALL3 x acucar | comprado | 2023-08-21 | 2023-08-28 | 5 | +20.8% | +3.55 |
| SMTO3 x acucar | comprado | 2017-12-04 | 2017-12-26 | 15 | +9.5% | +3.00 |
| SMTO3 x acucar | comprado | 2018-10-08 | 2018-10-22 | 9 | +12.7% | +2.98 |
| SMTO3 x acucar | vendido | 2024-06-24 | 2024-08-05 | 30 | +16.5% | +2.96 |
| SMTO3 x acucar | comprado | 2014-10-27 | 2014-11-24 | 20 | +17.3% | +2.95 |
| SMTO3 x acucar | comprado | 2026-06-22 | 2026-08-24 | 45 | +15.5% | +2.91 |
| SMTO3 x acucar | comprado | 2012-05-25 | 2012-06-25 | 20 | +14.7% | +2.83 |
| JALL3 x acucar | comprado | 2024-06-10 | 2024-07-08 | 20 | +14.6% | +2.64 |

10 piores:
| ativo | lado | entrada | saída | dias | retorno | contrib (pp do PL) |
|---|---|---|---|---|---|---|
| JALL3 x acucar | comprado | 2024-10-14 | 2025-04-08 | 120 | -44.0% | -10.59 |
| RAIZ4 x acucar | comprado | 2024-10-28 | 2025-04-24 | 120 | -37.7% | -7.06 |
| RAIZ4 x acucar | comprado | 2025-07-14 | 2025-12-31 | 120 | -46.2% | -5.87 |
| SMTO3 x acucar | comprado | 2022-06-27 | 2022-11-07 | 92 | -32.0% | -5.56 |
| RAIZ4 x acucar | comprado | 2026-03-20 | 2026-08-11 | 98 | -55.0% | -5.07 |
| JALL3 x acucar | comprado | 2025-07-14 | 2025-11-17 | 90 | -23.7% | -4.81 |
| SMTO3 x acucar | comprado | 2024-09-02 | 2025-02-21 | 120 | -22.0% | -3.62 |
| SMTO3 x acucar | vendido | 2022-02-21 | 2022-06-13 | 76 | -15.3% | -2.96 |
| SMTO3 x acucar | comprado | 2023-11-13 | 2024-03-11 | 80 | -13.9% | -2.46 |
| JALL3 x acucar | comprado | 2026-05-25 | 2026-08-24 | 64 | -12.6% | -1.12 |

## C4 Mineradoras vs metal

**Tese de mesa.** Mineradora é uma opção alavancada no metal. GDX/GLD, GDXJ/GDX, SIL/SLV, COPX/CPER, FCX/CPER e Vale (vs BHP/RIO ou vs minério SGX TIO=F em R$). Quando a mineradora fica para trás do metal, compro a mineradora e vendo o metal (e vice-versa).

**Implementação.** Pares em dólar com hedge cambial (excesso sobre T-bill), beta 1 ano, z-score, histerese semanal. TIO=F (o Yahoo tem minério SGX desde out/2010) como futuro contínuo com dias de rolagem zerados: **atenção**, rolagens pequenas não são detectadas e o minério vive em backwardation, então a série contínua subestima o retorno do comprado no futuro (favorece o lado vendido). A perna Vale x minério é a menos confiável — e foi negativa no OOS.

**Resultado.** Robusto entre variantes: 100% das 8 acima do CDI no OOS (mediana +5,9 pp), IR OOS 0,37, P(bater) 80%, custo x2 e execução +1 dia ainda positivos. PBO 59% diz que *qual* variante não importa — o efeito aparece em todas. Acerto de 70% dos negócios.

**O que deu certo.** GDXJ x GDX (junior vs sênior) é o melhor par OOS (+2 pp/ano): juniores exageram nos dois sentidos. Vendi FCX/comprei cobre em 10/fev/2020 (FCX tinha andado à frente do cobre) e ganhei 34,5% no par até 9/mar/2020. COPX comprado vs cobre em out/2014 +23%.

**O que deu errado.** Pares em que a mineradora mudou de patamar: Vale vendida vs minério em nov/2020 e out/2025 (-42% e -31%, saídas por tempo), SIL x SLV em 2025 (prata parabólica, mineradoras dispararam ainda mais).

**Próximo passo.** Tirar Vale x minério (viés de rolagem), manter os 5 pares EUA; testar saída em 60 dias; expressar com opções (vender call de GDX/comprar call de GLD quando GDX está rico).

**Números.** params {'jan': 126, 'z_in': 2.0, 'vale': 'minerio'} | IR IS 0.63 | OOS 14.7% vs CDI 11.4% | IR OOS 0.37 | vol OOS 8.8% | DD OOS -14.5% | P(bater) 80% | PBO 59% | DSR 66% | custo x2 +2.6pp | lag+1 +2.1pp | mediana variantes +5.9pp | % var>CDI 100%
| perna | IS pp/a | OOS pp/a |
|---|---|---|
| GDX x GLD | +0.76 | +0.63 |
| GDXJ x GDX | +0.88 | +2.04 |
| SIL x SLV | +1.03 | -0.04 |
| COPX x CPER | +0.55 | -0.12 |
| FCX x CPER | +2.21 | +1.17 |
| VALE3 x minerio | +0.03 | -0.72 |
| CMIN3 x minerio | +0.00 | +0.45 |
negócios: 175 | acerto 70% | dias mediana 50

10 melhores:
| ativo | lado | entrada | saída | dias | retorno | contrib (pp do PL) |
|---|---|---|---|---|---|---|
| COPX x CPER | comprado | 2014-10-06 | 2014-12-08 | 45 | +23.2% | +4.59 |
| FCX x CPER | vendido | 2020-02-10 | 2020-03-09 | 18 | +34.5% | +3.97 |
| GDX x GLD | vendido | 2018-07-02 | 2018-08-20 | 35 | +9.4% | +3.42 |
| GDXJ x GDX | comprado | 2019-06-10 | 2019-08-05 | 39 | +6.0% | +2.80 |
| GDXJ x GDX | comprado | 2016-02-10 | 2016-03-07 | 18 | +9.9% | +2.76 |
| GDXJ x GDX | vendido | 2025-06-09 | 2025-07-28 | 34 | +6.3% | +2.52 |
| SIL x SLV | vendido | 2025-09-15 | 2025-10-13 | 20 | +14.5% | +2.47 |
| GDX x GLD | vendido | 2019-07-22 | 2019-08-12 | 15 | +10.5% | +2.43 |
| GDX x GLD | vendido | 2017-01-02 | 2017-03-06 | 43 | +12.2% | +2.43 |
| FCX x CPER | comprado | 2014-10-13 | 2014-12-08 | 40 | +17.8% | +2.42 |

10 piores:
| ativo | lado | entrada | saída | dias | retorno | contrib (pp do PL) |
|---|---|---|---|---|---|---|
| VALE3 x minerio | vendido | 2025-10-27 | 2026-04-22 | 120 | -30.7% | -8.43 |
| VALE3 x minerio | vendido | 2020-11-23 | 2021-05-18 | 120 | -42.1% | -6.03 |
| COPX x CPER | vendido | 2025-08-11 | 2026-06-08 | 206 | -38.3% | -5.77 |
| SIL x SLV | vendido | 2016-02-22 | 2016-08-11 | 120 | -36.5% | -5.27 |
| GDXJ x GDX | vendido | 2016-04-11 | 2016-09-29 | 120 | -18.9% | -4.69 |
| VALE3 x minerio | vendido | 2017-08-28 | 2018-02-22 | 120 | -27.5% | -4.04 |
| SIL x SLV | vendido | 2025-03-24 | 2025-09-12 | 120 | -20.2% | -3.25 |
| SIL x SLV | comprado | 2025-12-08 | 2026-06-03 | 120 | -22.0% | -3.17 |
| GDX x GLD | comprado | 2012-01-23 | 2012-07-16 | 120 | -14.3% | -2.83 |
| VALE3 x minerio | comprado | 2014-09-29 | 2015-03-20 | 120 | -27.6% | -2.74 |

## C5 Carry agro B3 (estrutura a termo) + filtro CFTC

**Tese de mesa.** Curva invertida (spot > futuro) = estoque apertado: quem carrega o futuro ganha o roll. Compro BGI/CCM/ICF/SJC/ETH (B3) em backwardation, vendo em contango; filtro CFTC (não ficar do lado de especuladores lotados nos mercados equivalentes dos EUA).

**Dados.** Baixei os ajustes de TODOS os vencimentos dos futuros agro B3 2018+ (boletim BVBG.086, `dados/b3_futuros_agro.parquet`, 400 mil linhas). Série rolada = 2º vencimento com OI > 50, troca 20 dias antes do mês de vencimento; carry = log(F1/F2) anualizado.

**Armadilha encontrada.** Na B3 a curva "normal" está sempre em contango porque carregar estoque custa CDI (10-14%): sem ajuste, o sinal ficava vendido 80-90% do tempo (SR -1,8). Corrigido somando o juro (CDI p/ contratos em R$, T-bill p/ café e soja em dólar) -> sobra o rendimento de conveniência; a variante "saz" desconta também a média do mesmo mês nos anos anteriores (safra/entressafra domina a curva de milho e boi).

**Resultado.** Ruim em todas as 8 variantes (OOS -14 pp vs CDI na escolhida; custo x2 -26 pp: o sinal vira toda semana). O fato dominante do período: os futuros agro B3 *comprados* renderam ~8% (BGI), 8% (CCM), 15% (ICF), 10% (ETH) ao ano de excesso 2018-2026 — prêmio para quem compra o hedge do produtor (pressão de hedge vendedor) + real fraco. Qualquer sinal que fica vendido paga esse prêmio. Melhor negócio: comprado em café (ICF) de nov/2021 a out/2026, +100%. Pior: vendido em boi set-nov/2019 (-24,5%, a China abriu habilitações e a arroba explodiu).

**Próximo passo.** Inverter a pergunta: carteira comprada risco-paridade em futuros agro B3 (prêmio de hedge), reduzindo só em backwardation extrema; carry cross-section precisa de mais mercados (vencimentos CBOT/ICE — o Yahoo só tem o contínuo).

**Números.** params {'modo': 'saz_ts', 'cot': 0} | IR IS -0.26 | OOS -1.3% vs CDI 13.1% | IR OOS -0.93 | vol OOS 13.7% | DD OOS -29.2% | P(bater) 3% | PBO 69% | DSR 0% | custo x2 -25.6pp | lag+1 -11.6pp | mediana variantes -10.4pp | % var>CDI 0%
| perna | IS pp/a | OOS pp/a |
|---|---|---|
| BGI | -2.37 | -4.41 |
| CCM | -3.62 | +2.39 |
| ICF | +2.13 | +4.99 |
| SJC | +4.41 | -6.27 |
| ETH | +1.59 | -2.13 |
negócios: 259 | acerto 41% | dias mediana 15

10 melhores:
| ativo | lado | entrada | saída | dias | retorno | contrib (pp do PL) |
|---|---|---|---|---|---|---|
| ICF | comprado | 2021-11-29 | 2026-10-13 | 1225 | +100.3% | +16.66 |
| CCM | vendido | 2023-01-09 | 2024-01-02 | 244 | +40.4% | +16.20 |
| BGI | comprado | 2024-09-02 | 2024-12-23 | 78 | +29.1% | +13.84 |
| CCM | comprado | 2020-07-13 | 2020-11-09 | 82 | +67.3% | +13.64 |
| ETH | vendido | 2020-02-10 | 2020-06-15 | 84 | +20.9% | +12.04 |
| ETH | comprado | 2021-04-19 | 2021-12-13 | 164 | +34.5% | +11.07 |
| ETH | comprado | 2019-11-04 | 2020-02-10 | 67 | +13.0% | +8.93 |
| BGI | comprado | 2020-05-11 | 2020-09-08 | 84 | +26.1% | +8.44 |
| SJC | comprado | 2020-11-09 | 2021-10-11 | 232 | +12.2% | +7.85 |
| SJC | comprado | 2020-05-04 | 2020-09-21 | 98 | +18.1% | +7.33 |

10 piores:
| ativo | lado | entrada | saída | dias | retorno | contrib (pp do PL) |
|---|---|---|---|---|---|---|
| BGI | vendido | 2019-09-02 | 2019-11-25 | 59 | -24.5% | -22.95 |
| ETH | vendido | 2021-01-11 | 2021-03-01 | 33 | -17.3% | -9.58 |
| ETH | comprado | 2022-04-04 | 2022-09-05 | 107 | -22.9% | -7.62 |
| ETH | vendido | 2019-03-18 | 2019-04-22 | 24 | -5.1% | -7.21 |
| CCM | vendido | 2021-02-01 | 2021-05-10 | 66 | -24.1% | -7.12 |
| BGI | comprado | 2023-05-08 | 2023-09-04 | 84 | -22.9% | -6.84 |
| CCM | vendido | 2019-04-29 | 2019-08-26 | 83 | -16.2% | -6.47 |
| SJC | vendido | 2025-12-29 | 2026-05-04 | 84 | -13.1% | -5.71 |
| ETH | comprado | 2023-04-10 | 2023-07-17 | 67 | -15.7% | -5.34 |
| CCM | comprado | 2025-02-17 | 2025-05-19 | 60 | -13.2% | -4.88 |

## C6 Spreads clássicos de commodities

**Tese de mesa.** Spreads de processamento e de qualidade voltam à média porque alguém arbitra fisicamente: Brent-WTI (BNO/USO), prata/ouro, platina/ouro, crack 3:2:1 (2/3 RB + 1/3 HO vs CL) e crush da soja (farelo + óleo vs grão, pesos de valor da prancha de esmagamento). Mais um livro sazonal: vender UNG de outubro a fevereiro (o prêmio de inverno e o contango do gás se desfazem).

**Implementação.** ETFs onde há; crack e crush com futuros contínuos com dias de rolagem zerados (RB muda de especificação inverno/verão em março: o salto de +24% em 1/3/2016 é removido). Beta 6 meses, z-score.

**Resultado.** PBO 5% (o menor da frente), IR OOS 0,24, P(bater) 67%, custo x2 e atraso ainda positivos — mas IR IS só 0,27 e só metade das variantes acima do CDI no OOS. Fontes: gás de inverno no IS (+1,65 pp/ano), crack (+3,5 pp/ano) e crush (+1,9) no OOS. Brent-WTI, prata/ouro e platina/ouro **não** revertem (perdem).

**O que deu certo.** UNG vendido no inverno: out/2015-mar/2016 +75%, out/2022-mar/2023 +102% (o fim da crise do gás europeu com inverno quente). Crack vendido abr-ago/2019 +12,5%.

**O que deu errado.** UNG vendido no inverno de 2013-14 (vórtice polar, -35%): é venda de opção — tamanho pequeno/stop. Brent-WTI vendido em fev/2022 (guerra: Brent disparou vs WTI; -7,8% em 10 dias com peso alto).

**Próximo passo.** Ficar só com crack + crush + gás de inverno (os spreads com arbitragem física); tamanho do gás pela vol implícita.

**Números.** params {'jan': 126, 'z_in': 1.5, 'gas': 1} | IR IS 0.27 | OOS 13.7% vs CDI 11.4% | IR OOS 0.24 | vol OOS 10.6% | DD OOS -13.8% | P(bater) 67% | PBO 5% | DSR 46% | custo x2 +1.3pp | lag+1 +3.3pp | mediana variantes +0.5pp | % var>CDI 50%
| perna | IS pp/a | OOS pp/a |
|---|---|---|
| BNO x USO (Brent-WTI) | -0.47 | -0.81 |
| SLV x GLD (prata/ouro) | +1.09 | -1.88 |
| crack 3:2:1 | +0.09 | +3.51 |
| crush soja | +0.69 | +1.93 |
| PPLT x GLD (platina/ouro) | -0.17 | -0.60 |
| UNG vendido (inverno) | +1.65 | +0.70 |
negócios: 210 | acerto 65% | dias mediana 62

10 melhores:
| ativo | lado | entrada | saída | dias | retorno | contrib (pp do PL) |
|---|---|---|---|---|---|---|
| UNG vendido (inverno) | vendido | 2015-10-02 | 2016-03-02 | 102 | +75.4% | +8.41 |
| UNG vendido (inverno) | vendido | 2022-10-04 | 2023-03-02 | 102 | +102.1% | +5.44 |
| UNG vendido (inverno) | vendido | 2014-10-02 | 2015-03-03 | 104 | +40.6% | +4.35 |
| UNG vendido (inverno) | vendido | 2019-10-02 | 2020-03-03 | 104 | +32.1% | +3.93 |
| UNG vendido (inverno) | vendido | 2023-10-03 | 2024-03-04 | 102 | +36.4% | +3.60 |
| crack 3:2:1 | vendido | 2019-04-22 | 2019-08-05 | 73 | +12.5% | +3.42 |
| SLV x GLD (prata/ouro) | comprado | 2022-09-05 | 2022-09-19 | 9 | +13.2% | +3.26 |
| crush soja | vendido | 2016-05-30 | 2016-09-12 | 74 | +8.9% | +3.19 |
| crush soja | vendido | 2021-05-03 | 2021-06-21 | 34 | +7.1% | +3.10 |
| crush soja | comprado | 2017-07-03 | 2017-07-17 | 10 | +3.7% | +3.01 |

10 piores:
| ativo | lado | entrada | saída | dias | retorno | contrib (pp do PL) |
|---|---|---|---|---|---|---|
| BNO x USO (Brent-WTI) | vendido | 2022-02-14 | 2022-03-02 | 10 | -7.8% | -8.53 |
| SLV x GLD (prata/ouro) | vendido | 2025-09-29 | 2026-03-23 | 120 | -38.5% | -7.90 |
| PPLT x GLD (platina/ouro) | comprado | 2014-09-22 | 2015-03-13 | 120 | -12.5% | -7.89 |
| SLV x GLD (prata/ouro) | comprado | 2020-02-03 | 2020-07-27 | 119 | -13.4% | -6.86 |
| crack 3:2:1 | vendido | 2017-07-24 | 2017-09-04 | 30 | -15.4% | -6.81 |
| UNG vendido (inverno) | vendido | 2013-10-02 | 2014-03-06 | 106 | -35.0% | -6.71 |
| BNO x USO (Brent-WTI) | comprado | 2014-07-21 | 2015-02-18 | 148 | -9.9% | -6.68 |
| crush soja | vendido | 2016-05-09 | 2016-05-16 | 5 | -5.4% | -6.08 |
| BNO x USO (Brent-WTI) | vendido | 2017-08-14 | 2017-09-04 | 15 | -5.2% | -4.83 |
| BNO x USO (Brent-WTI) | vendido | 2025-08-25 | 2026-03-09 | 135 | -1.7% | -4.66 |

## C7 Moedas de commodities vs commodities

**Tese de mesa.** AUD, CAD, NOK, CLP e BRL são commodities disfarçadas; quando a moeda descola da cesta de exportação, compro a moeda barata e vendo as commodities (carry da moeda incluído, juros de política do BIS).

**Resultado.** Neutro: IR IS 0, OOS +0,4 pp, P(bater) 53%. CAD e AUD ganham um pouco no OOS; BRL perde (o real descola do minério/soja por risco fiscal — vendido BRL vs commodities em mar/2016 perdeu 17,7% quando o impeachment apreciou o real).

**Próximo passo.** Só G10 (AUD, CAD, NOK), prazo mais curto; para BRL o resíduo é risco fiscal (frente de juros).

**Números.** params {'jan': 63, 'z_in': 2.0} | IR IS -0.00 | OOS 11.8% vs CDI 11.4% | IR OOS 0.08 | vol OOS 9.2% | DD OOS -7.6% | P(bater) 53% | PBO 36% | DSR 40% | custo x2 -1.1pp | lag+1 -1.0pp | mediana variantes +0.5pp | % var>CDI 56%
| perna | IS pp/a | OOS pp/a |
|---|---|---|
| AUD x commodities | +0.14 | +1.14 |
| CAD x commodities | +0.22 | +1.65 |
| NOK x commodities | +0.18 | +0.15 |
| CLP x commodities | -0.52 | -0.47 |
| BRL x commodities | +0.01 | -1.56 |
negócios: 196 | acerto 66% | dias mediana 38

10 melhores:
| ativo | lado | entrada | saída | dias | retorno | contrib (pp do PL) |
|---|---|---|---|---|---|---|
| CAD x commodities | comprado | 2024-07-29 | 2024-08-26 | 20 | +2.7% | +2.82 |
| NOK x commodities | vendido | 2015-08-24 | 2015-09-28 | 24 | +6.2% | +2.46 |
| CAD x commodities | vendido | 2024-09-02 | 2024-10-14 | 30 | +2.4% | +2.33 |
| BRL x commodities | comprado | 2015-03-16 | 2015-04-27 | 28 | +11.9% | +2.26 |
| BRL x commodities | comprado | 2018-08-27 | 2018-10-08 | 29 | +7.3% | +2.23 |
| NOK x commodities | vendido | 2023-07-17 | 2023-08-21 | 25 | +6.8% | +2.16 |
| CLP x commodities | comprado | 2025-07-14 | 2025-09-15 | 45 | +5.3% | +2.11 |
| CLP x commodities | vendido | 2015-05-18 | 2015-06-08 | 14 | +4.6% | +2.06 |
| AUD x commodities | vendido | 2021-11-01 | 2021-11-29 | 18 | +3.7% | +1.98 |
| CLP x commodities | comprado | 2022-07-11 | 2022-07-25 | 10 | +6.6% | +1.91 |

10 piores:
| ativo | lado | entrada | saída | dias | retorno | contrib (pp do PL) |
|---|---|---|---|---|---|---|
| NOK x commodities | comprado | 2014-06-23 | 2014-12-08 | 120 | -10.1% | -6.62 |
| NOK x commodities | comprado | 2021-11-22 | 2022-08-01 | 175 | -13.9% | -5.21 |
| AUD x commodities | comprado | 2020-02-03 | 2020-06-08 | 85 | -6.6% | -5.05 |
| CLP x commodities | comprado | 2021-05-31 | 2021-11-22 | 120 | -11.2% | -4.79 |
| BRL x commodities | vendido | 2016-03-07 | 2016-08-25 | 120 | -17.7% | -4.40 |
| AUD x commodities | comprado | 2021-02-22 | 2021-08-12 | 120 | -8.6% | -4.22 |
| AUD x commodities | comprado | 2019-05-13 | 2019-10-21 | 114 | -4.5% | -3.69 |
| BRL x commodities | vendido | 2014-03-05 | 2014-08-11 | 109 | -8.4% | -3.66 |
| CLP x commodities | comprado | 2019-10-28 | 2020-01-06 | 47 | -5.9% | -3.66 |
| BRL x commodities | comprado | 2020-02-17 | 2020-06-08 | 75 | -8.2% | -3.50 |

## C8 Exportadoras BR com hedge de commodity

**Tese de mesa.** Isolar o alfa da empresa: comprar exportadoras BR e vender a commodity em R$ (ou o dólar, para celulose e aço) e o Ibovespa nas proporções dos betas (2 fatores, 1 ano). Variantes: todas compradas; momentum do resíduo; reversão.

**Resultado.** Não há alfa médio: IS IR 0,31, OOS -0,6 pp, nenhuma variante acima do CDI no OOS. O resíduo é dominado por poucos nomes: PRIO (resíduo de +2.000% desde 2016, crescimento de produção) e SLC carregam; BRF (-88% de resíduo até a fusão), Gerdau e Suzano destroem. "Exportadora com hedge" é escolha de ação, não fator.

**Próximo passo.** Usar estes resíduos como insumo de seleção (crescimento de volume, custo caixa) em vez de comprar todos.

**Números.** params {'modo': 'todas', 'jan': 126} | IR IS 0.31 | OOS 10.8% vs CDI 11.4% | IR OOS -0.01 | vol OOS 10.4% | DD OOS -12.2% | P(bater) 46% | PBO 43% | DSR 9% | custo x2 -1.5pp | lag+1 -0.8pp | mediana variantes -1.2pp | % var>CDI 0%
| perna | IS pp/a | OOS pp/a |
|---|---|---|
| VALE3 | +0.06 | -0.51 |
| CMIN3 | +0.00 | +0.02 |
| CSNA3 | +0.23 | -0.97 |
| PETR4 | -0.17 | +1.33 |
| PRIO3 | +1.71 | +0.14 |
| SUZB3 | -0.03 | -0.35 |
| KLBN11 | +0.49 | -0.45 |
| JBSS32 | +1.00 | +0.73 |
| BEEF3 | +0.12 | -0.79 |
| MBRF3 | +0.03 | +0.81 |
| SMTO3 | +0.96 | -0.50 |
| SLCE3 | +0.77 | +0.07 |
| GGBR4 | -0.43 | +0.18 |
| BRFS3 | -1.42 | +0.39 |
negócios: 8 | acerto 62% | dias mediana 2923

10 melhores:
| ativo | lado | entrada | saída | dias | retorno | contrib (pp do PL) |
|---|---|---|---|---|---|---|
| PRIO3 | comprado | 2016-08-01 | 2026-10-13 | 2560 | +2073.6% | +16.10 |
| SLCE3 | comprado | 2012-04-02 | 2026-10-13 | 3649 | +150.0% | +7.37 |
| SMTO3 | comprado | 2012-04-02 | 2026-10-13 | 3649 | -13.3% | +6.04 |
| KLBN11 | comprado | 2014-09-01 | 2026-10-13 | 3042 | -35.3% | +1.81 |
| CMIN3 | comprado | 2021-09-01 | 2026-10-13 | 1284 | -32.3% | +0.19 |
| SUZB3 | comprado | 2018-07-02 | 2026-10-13 | 2081 | -62.8% | -2.29 |
| GGBR4 | comprado | 2012-10-01 | 2026-10-13 | 3523 | -50.0% | -4.86 |
| BRFS3 | comprado | 2014-08-01 | 2025-10-01 | 2804 | -88.1% | -10.35 |

10 piores:
| ativo | lado | entrada | saída | dias | retorno | contrib (pp do PL) |
|---|---|---|---|---|---|---|
| BRFS3 | comprado | 2014-08-01 | 2025-10-01 | 2804 | -88.1% | -10.35 |
| GGBR4 | comprado | 2012-10-01 | 2026-10-13 | 3523 | -50.0% | -4.86 |
| SUZB3 | comprado | 2018-07-02 | 2026-10-13 | 2081 | -62.8% | -2.29 |
| CMIN3 | comprado | 2021-09-01 | 2026-10-13 | 1284 | -32.3% | +0.19 |
| KLBN11 | comprado | 2014-09-01 | 2026-10-13 | 3042 | -35.3% | +1.81 |
| SMTO3 | comprado | 2012-04-02 | 2026-10-13 | 3649 | -13.3% | +6.04 |
| SLCE3 | comprado | 2012-04-02 | 2026-10-13 | 3649 | +150.0% | +7.37 |
| PRIO3 | comprado | 2016-08-01 | 2026-10-13 | 2560 | +2073.6% | +16.10 |

## C9 CFTC contrarian (especulador lotado)

**Tese de mesa.** Quando os managed money estão no percentil 95 de 3 anos de posição líquida (% do OI), todo mundo já comprou: vendo. No percentil 5, compro. COT de terça é publicado sexta 15h30 ET -> índice deslocado +3 dias, execução no fechamento seguinte.

**Dados.** cot.parquet (disaggregated, 2013+; mapeado pelo código CFTC porque os nomes mudaram em 2022), 13 mercados (ETFs e futuros com rolagem zerada).

**Resultado.** Ruim e robustamente ruim: OOS -12 pp vs CDI, IR OOS -1,08, todas as 8 variantes negativas, inclusive com confirmação de preço. No OOS o especulador lotado estava *certo*: ouro vendido mar/2024-out/2025 -49% (-14 pp do PL), milho vendido out/2020-jul/2022 -52%, boi vendido em 2023 -21%.

**Leitura.** Em commodities, posição extrema de managed money é sintoma de tendência com fundamento (estoque caindo), não de excesso. O inverso (seguir o extremo) daria IR ~+1 no OOS, mas isso é escolher depois de ver — tratar como hipótese nova, calibrada só em 2013-2020.

**Números.** params {'lim': 0.95, 'saida': '50', 'confirma': 0} | IR IS 0.13 | OOS -0.7% vs CDI 11.4% | IR OOS -1.08 | vol OOS 10.2% | DD OOS -25.3% | P(bater) 0% | PBO 66% | DSR 0% | custo x2 -12.4pp | lag+1 -11.6pp | mediana variantes -10.6pp | % var>CDI 0%
| perna | IS pp/a | OOS pp/a |
|---|---|---|
| GLD | +1.60 | -2.18 |
| SLV | +0.01 | -0.39 |
| CPER | -1.39 | -0.47 |
| USO | +0.23 | +2.20 |
| UNG | +0.23 | +0.19 |
| CORN | +0.71 | -2.11 |
| SOYB | -0.15 | -1.12 |
| WEAT | +1.50 | -0.83 |
| CANE | -0.09 | -2.00 |
| KC=F | -0.95 | -0.35 |
| LE=F | +0.73 | -2.33 |
| CT=F | -0.37 | -0.41 |
| HE=F | -0.71 | -1.09 |
negócios: 113 | acerto 57% | dias mediana 91

10 melhores:
| ativo | lado | entrada | saída | dias | retorno | contrib (pp do PL) |
|---|---|---|---|---|---|---|
| USO | comprado | 2025-03-05 | 2026-09-14 | 384 | +106.9% | +9.51 |
| WEAT | vendido | 2018-06-04 | 2019-04-29 | 226 | +30.7% | +5.03 |
| HE=F | comprado | 2019-02-18 | 2019-04-15 | 38 | +34.6% | +4.25 |
| UNG | vendido | 2016-10-24 | 2018-07-23 | 436 | +34.8% | +4.06 |
| HE=F | vendido | 2022-11-07 | 2023-01-16 | 49 | +21.0% | +2.90 |
| GLD | vendido | 2016-04-04 | 2016-12-19 | 179 | +5.5% | +2.65 |
| CT=F | vendido | 2024-03-04 | 2024-04-22 | 34 | +22.1% | +2.53 |
| LE=F | comprado | 2019-07-08 | 2020-08-24 | 286 | +16.4% | +2.49 |
| SOYB | vendido | 2018-03-12 | 2018-06-18 | 67 | +11.4% | +2.43 |
| SOYB | vendido | 2023-01-09 | 2023-03-27 | 53 | +6.1% | +2.42 |

10 piores:
| ativo | lado | entrada | saída | dias | retorno | contrib (pp do PL) |
|---|---|---|---|---|---|---|
| GLD | vendido | 2024-03-11 | 2025-10-20 | 407 | -48.7% | -14.35 |
| CORN | vendido | 2020-10-19 | 2022-07-11 | 433 | -51.9% | -10.66 |
| LE=F | vendido | 2023-01-02 | 2023-11-06 | 211 | -21.2% | -10.23 |
| CANE | vendido | 2022-12-26 | 2023-06-12 | 114 | -29.1% | -8.34 |
| SOYB | vendido | 2020-09-14 | 2021-10-25 | 279 | -31.5% | -7.06 |
| SLV | vendido | 2024-09-23 | 2025-10-13 | 265 | -42.6% | -7.05 |
| LE=F | vendido | 2024-11-25 | 2025-11-24 | 251 | -18.1% | -5.81 |
| KC=F | vendido | 2024-01-29 | 2025-06-30 | 355 | -43.6% | -5.04 |
| CT=F | vendido | 2021-08-23 | 2022-07-11 | 221 | -35.6% | -4.84 |
| CPER | vendido | 2020-09-28 | 2021-12-20 | 307 | -34.5% | -4.79 |

