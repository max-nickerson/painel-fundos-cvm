# Frente EVENTOS BRASIL — caderno de pesquisa (out/2026)

Código: `ideias_eventos_br.py` (estratégias + fundos), `coleta_eventos_br.py` (coletor, cache em `dados/`).
Resultado: `resultado/ideias_eventos_br.pkl` (9 fundos, com `contrib` diário por ativo e `trades`), log em `resultado/log_eventos_br.txt`.
Período: 2014-06 a 2026-10 (COTAHIST local começa em 2014, não 2008). IS até 2020-12, OOS 2021-01+ (insiders: dados 2019+, OOS 2023+).

## 1. Dados montados (todos com cache, nada é re-baixado)
| arquivo | conteúdo |
|---|---|
| `dados/cvm_ipe.parquet` | IPE CVM 2013-2026 (562 mil docs: fatos relevantes, comunicados, atas, avisos) com **Data_Entrega** e link do PDF |
| `dados/cvm_ipe_textos.parquet` | texto de 1.447 PDFs (FRs de OPA/controle/incorporação/precificação) — base para ler o **preço da oferta** |
| `dados/cvm_vlmo.parquet` | VLMO 2018-2026 (negociação de controladores/administradores, por movimento) + data de entrega do formulário |
| `dados/cvm_itr_dfp.parquet` | datas de entrega (DT_RECEB) de ITR/DFP 2013-2026 — lido por HTTP Range só o índice dentro do zip de 30 MB |
| `dados/cvm_fca_vm.parquet`, `cvm_cad.parquet` | FCA valores mobiliários (CNPJ -> código de negociação) e cadastro CVM (data de registro) |
| `dados/b3_acoes_cotahist.parquet` | COTAHIST 2014+ de ações **incluindo CODBDI 05-09** (recuperação judicial, sancionadas) e máx/mín |
| `dados/y_proventos.parquet` | dividendos/JCP e desdobramentos do Yahoo (411 tickers vivos) |
| `dados/painel_eventos_br.pkl` | painel ajustado (P, R total, volume, ADV, máx/mín) — cache derivado |

### Bugs/armadilhas encontrados nos dados (importante para outras frentes)
1. **`b3_vista.parquet` tem viés de sobrevivência nos eventos ruins**: só CODBDI 02. Ações em recuperação judicial negociam com CODBDI 08 e
   SOMEM (OIBR3 de jul/2016 a 2022, AMER3 de 2023 em diante, RPMG, TCNO, INEP, OSXB...). Qualquer estratégia vendida/contrarian em
   ações em crise que use b3_vista está errada. Use `b3_acoes_cotahist.parquet`.
2. Desdobramento/bonificação no COTAHIST: marcação **EB** (também para desdobramento, ex.: MGLU3 8:1 em 06/08/2019, BBAS3 2:1 em 16/04/2024) e **EG** (grupamento).
   Ajuste: razão do Yahoo quando existe; senão razão "redonda" mais próxima no 1º dia com EB/EG. Saltos > 25% sem documento na CVM em 5 dias são zerados; erros que se desfazem no dia seguinte também.
   Conferência contra Yahoo (retorno total anual): PETR4, ITUB4, BBAS3, VALE3, WEGE3, TAEE11 batem ao 1 pp; deslistados não têm dividendo (conservador para comprado).
3. Links do RAD/CVM devolvem uma página HTML intermitentemente (limite de acesso): o coletor re-tenta com espera; sem isso 2022+ ficaria sem texto.
4. Data do sinal = **Data_Entrega** (o IPE não tem hora). Decisão no fechamento desse dia, execução no fechamento seguinte: se o FR saiu às 8h perdemos o 1º dia (conservador), se saiu às 20h é exatamente o primeiro fechamento possível.

### Motor (próprio, em `livro()`)
Pesos decididos em t -> executados em t+1(+lag); ações em excesso sobre o CDI; custo por perna por liquidez (ADV60 >= 50 mi: 10 bps; 10-50: 20; 2-10: 40; menor: 80);
aluguel 1%/3%/8% a.a. (lock-up >= 6%, crise >= 10%); hedge em Ibovespa (BOVA11/futuro, 3 bps) do líquido; posição em papel deslistado encerrada no último negócio (OPA/incorporação liquidam a esse preço) sem custo. Testado: livro de 100% PETR4 reproduz exatamente R - CDI.

## 2. Estudos de evento (retorno anormal vs Ibovespa, a partir do fechamento de execução t+1)
| evento | n | 20d | 60d | 120d | IS<2021 (60d) | OOS (60d) |
|---|---|---|---|---|---|---|
| recompra anunciada | 831 | -0,3% | +0,4% (mediana -1,9%) | +1,0% | -0,6% | +1,1% |
| oferta de ações (follow-on) | 235 | -1,7% | **-3,0%** (t=-2,3) | -5,4% | -0,1% | -6,0% |
| pedido de RJ / fraude | 46 | -1,1% | -3,5% | -12,1% | +3,5% | -13,5% |
| fim de lock-up (decisão 10d antes) | 69 | -1,8% | -3,2% | -8,5% | +1,3% | -4,7% |
| insider compra (>=2% do giro) | 294 | +0,8% | +2,7% (mediana -0,5%) | +3,2% | +7,2% | +2,0% |
| insider venda | 432 | -1,5% | **-3,0%** (t=-3,3) | -3,6% | +1,6% | -4,6% |
| resultado: reação <= -5% | 1.042 | | -2,8% adicional | | | |
| resultado: reação >= +5% | 944 | | +2,0% adicional | | | |
| bloco vendedor sem notícia | 241 | -1,8% | -4,1% | | -2,5% | -5,5% |
| bloco comprador sem notícia | 316 | +1,5% | -0,6% | | | |
| queda >20% em 3d com fato | 283 | -2,1% | -2,7% (mediana -6,8%) | | **+5,0%** | **-7,9%** |
| entrante Ibov (proxy), até a vigência | 129 | +1,4% (21d) | | | +0,4% | +2,4% |

Leitura de mesa: no Brasil o que funciona é **subreação a notícia ruim e a quem sabe mais** (emissor vendendo ação, controlador vendendo, resultado ruim, bloco vendedor); notícia "boa" de gestão (recompra) não carrega nada.

## 3. Os fundos (escolha de parâmetros só no IS; OOS 2021+)
| fundo | escolhido | IR IS | OOS a.a. vs bench | IR OOS | P(bater) | PBO | custo x2 | +1 dia |
|---|---|---|---|---|---|---|---|---|
| E1 Arbitragem de OPA/controle | smin 2%, sem hedge, só dinheiro | 0,33 | 13,2% vs 11,4% | 0,47 | 90% | 51% | +1,5 pp | +1,4 pp |
| E2 Recompra anunciada | 63d, 20 nomes | -0,32 | 7,8% vs 11,4% | -0,20 | 22% | 65% | -5,8 | -4,2 |
| E3 Follow-on vendido | 40d, 10 nomes | -0,04 | **21,6%** vs 11,4% | **1,01** | 99% | 64% | +9,2 | +10,0 |
| E4 Fim de lock-up | 5d antes, 15d depois | 0,04 | 9,3% vs 11,4% | -0,27 | 19% | 91% | -2,8 | -1,1 |
| E5 Insiders (VLMO) | só compras >= 5% do giro | 0,74 | 16,6% vs 13,1% | 0,43 | 77% | 63% | +2,9 | +3,7 |
| E6 PEAD | |reação| >= 8%, 40d | **1,04** | 16,6% vs 11,4% | 0,50 | 88% | 77% | +2,3 | +3,2 |
| E7 Rebalanceamento Ibov | entrantes, 10d antes | 0,39 | 13,2% vs 11,4% | 0,97 | 99% | 19% | +1,6 | +1,2 |
| E8 Blocos informados | 3x, 40d, ambos | 0,21 | 9,0% vs 11,4% | -0,15 | 28% | 81% | -5,5 | -3,6 |
| E9 Crise (queda >20% / RJ) | contrarian, 60d | 0,11 | -15,4% vs 11,4% | -0,99 | 0% | 6% | -28 | -27,5 |

Benchmark CDI em todos (livros hedgeados em Ibovespa ou long-short). Nenhum Sharpe > 1,5 — não há sinal de bug grosseiro; os altos são do OOS de E3 (IR 1,0) e E7 (IR 1,0 com vol de 1,7%).

---
## E1 Arbitragem de OPA e troca de controle
**Tese**: compro o alvo de OPA/venda de controle enquanto negocia abaixo do preço da oferta; o mercado cobra prêmio de prazo/risco maior que o risco real (OPA obrigatória, tag along, laudo, CVM).
**Como**: preço da oferta lido do PDF do FR (valor "R$ x" a até 120 caracteres de "por ação"/"preço da oferta"), aceito só se estiver entre 0,9x e 1,5x o preço da própria ação (isso garante que a companhia que publicou é o ALVO, e descarta valores totais). Excluo ADR/Latibex/subsidiária/"resultado do leilão"/desistência. Entra se spread >= smin e <= 30%; sai no fechamento do spread, **no leilão** (FR "resultado do leilão" -> entrego ao preço da oferta) ou na deslistagem.
**Resultado**: 24 negócios, 88% de acerto, vol 3,4%, DD -3%. OOS 13,2% vs CDI 11,4%. Pouco capital empregado (exposição média ~6% do PL; o resto fica no CDI) — é um livro para somar, não um fundo sozinho.
**Melhores**: Helbor (HBOR3, OPA 2026, +51% em 67 pregões — comprado após a queda de 23% no dia do FR, saiu quando o preço encostou em R$ 2,52); IMC (MEAL3, OPA a R$ 8,00 em dez/2018, +27% em 147 pregões); Brava (BRAV3, OPA da Ecopetrol a R$ 23, +21% em 71 pregões até o leilão de 05/08/2026); Prumo (PRML3, OPA EIG a R$ 9,98-10,51 em 2017, +20% em 118 pregões); Kepler Weber (KEPL3, venda de controle a R$ 22 em fev/2017, +10% em 32 pregões); Heringer (FHER3, OPA unificada R$ 19, +8% em 125 pregões até o leilão de 27/06/2023); CPFL Renováveis (CPRE3, +8% em 230 pregões).
**Piores**: Zamp (BKBR3, out/2022 -10,7%: preço do "parecer do conselho" R$ 9,96 não era a oferta firme, que saiu a R$ 8,31); Cemig/Redentor 2015 (CMIG4 -12%: preço era da Redentor, não da Cemig — falso positivo do mapeamento); Prumo dez/2015 (-5,6%).
**Bugs encontrados**: (i) sem modelar o leilão, Heringer aparecia com -57% (a ação despencou DEPOIS da OPA — quem tem a ação entrega no leilão); (ii) incorporações com troca de ações (Inter 2022 -45%, GOL/Smiles, Omega) não são arbitragem em dinheiro — o "R$ por ação" é referência. Com `tipo='todos'` o fundo piora; escolhido `tipo='opa'`.
**Próximo passo**: extrair também a relação de troca e montar a perna vendida no comprador (pairs de incorporação); ler a data do leilão do edital; checar rateio (OPA parcial).

## E2 Recompra anunciada — NÃO funciona
Excesso médio negativo (IS IR -0,32). Mediana de 120 dias: -4%. Quem anuncia recompra no Brasil é frequentemente small cap em queda (IRBR3 fev/2020 -78%, SEQL3 2023 -66%, LIGT3 2022 -59%, MGLU3 2021 -64%). Os ganhos vieram de rebotes pós-Covid (EVEN3, PTBL3, CARD3 em abr/2020) e de AMBP3 (+632% em jun-ago/2024, squeeze). Anúncio de recompra ≠ execução: no BR muitos programas não são executados. **Próximo**: usar a execução efetiva (VLMO, Tipo_Empresa "Companhia"/tesouraria) em vez do anúncio.

## E3 Follow-on vendido — a melhor tese da frente (com ressalva)
**Tese**: emissor e acionista vendedor (controlador, PE) sabem mais; vendem quando a ação está cara; a oferta adicional de papel pressiona por semanas.
**Como**: 1º FR de oferta de ações por empresa em 90 dias (lançamento, pedido de registro, "potencial oferta", precificação), vendido 40 pregões, 10% do PL por nome, comprado Ibovespa contra. Na prática a maioria das ofertas restritas (476/160) é anunciada à noite e precificada no dia seguinte, então a execução já é pós-precificação: o que se captura é a deriva pós-oferta, não o desconto.
**Resultado**: IS ~0 (2018-2019 -12%/-21%: no bull market de 2019 as ofertas subiam), OOS +21,6% a.a. (IR 1,0): 2020 +24%, 2021 +14%, 2022 +14%, 2025 +25%. Robusto a custo x2 e +1 dia; 100% das variantes batem o CDI no OOS. PBO 64% porque o IS é ruim — a decisão de usar depende de acreditar que 2019 foi exceção.
**Melhores**: AZUL4 (mar/2025 "potencial oferta" de PN: -71% em 40 pregões), COGN3 (fev/2020 -67%), IRBR3 (oferta restrita ago/2022 -53%), POSI3/BEEF3/JSLG3/ANIM3 (ofertas de jan/2020 pegaram o Covid), VIIA3 (set/2023 -42% em 12 pregões), BBAS3 (fev/2020).
**Piores**: HAPV3 (abr/2023 +66%), ELPL3 (abr/2018 — virou OPA concorrente Enel x Neoenergia, +62%), JHSF3 (out/2019 +53%), DASA3 (mar/2023 +42%), PRIO3 (dez/2020 +42%). Risco: oferta que vira disputa de controle; ação de crescimento em bull market.
**Atenção**: parte do OOS vem de quedas de mercado (Covid) apesar do hedge — beta das small caps emissoras > 1. **Próximo**: hedge por beta estimado; filtrar ofertas secundárias (vendedor informado) x primárias.

## E4 Fim de lock-up — sem efeito líquido
Estudo de evento mostra -3% em 60d (OOS -4,7%), mas a janela curta em volta da data (5 antes/15 depois) não captura e o aluguel de 6-8% come o resto. 2021-2022 (a safra de IPOs de 2020-21) teve ganhos (ENJU3 -29%, WIZS3, SBFG3, CMIN3) e perdas equivalentes (CBAV3 +36%, CASH3 +29%, DESK3, BOAS3). **Próximo**: segurar 60-120d após o lock-up (onde está o efeito) e filtrar IPOs com PE vendedor.

## E5 Insiders (VLMO)
**Tese**: controlador/administrador comprando forte a própria ação sabe algo; o formulário sai ~40 dias depois e ninguém lê.
**Como**: compra/venda à vista líquida do mês (cargos controlador, conselho, diretoria; papel da própria companhia), intensidade = líquido / (ADV60 x 21). Entra no pregão seguinte à **Data_Entrega** do formulário (mediana 39 dias após o mês). 63 pregões, 1/15 do PL, hedge Ibov.
**Resultado** (2019+, OOS 2023+): escolhido "só compras >= 5% do giro": IR IS 0,74, OOS 16,6% vs 13,1% (IR 0,43, P 77%). A perna vendida (insider vendendo) tem o melhor estudo de evento (-3% em 60d, t=-3,3) mas como fundo perde para a compra no IS.
**Melhores**: AMBP3 (jul/2024 +460%), ANIM3 (ago/2026 +153%), PTBL3 (abr/2021 +91%), ALPA4 (mai/2019 +88%), SHUL4 (abr/2020 +78%). **Piores**: IFCM3 (jun/2025 -80%; jan/2024 -43% — controlador comprando na descida de empresa que quebrou), TCSA3 2022, TRAD3 2023.
**Próximo**: excluir compras de controlador em empresa alavancada/RJ; combinar com a perna vendida em tamanho menor.

## E6 Deriva pós-resultado (PEAD)
**Tese**: o mercado subreage a resultado fora do esperado; a reação dos 2 primeiros dias continua.
**Como**: data = 1ª entrega do ITR/DFP (DT_RECEB); reação anormal fech. t-1 -> fech. t+1; decide em t+1, executa t+2. |reação| >= 8%: no sinal, 40 pregões, 1/20 do PL, hedge do líquido.
**Resultado**: o mais consistente no IS (IR 1,04; 9 de 13 anos positivos), OOS 16,6% vs 11,4% (IR 0,50, P 88%). 100% das variantes batem o CDI no OOS; PBO 77% só diz que a escolha do limiar é indiferente. 926 negócios, 55% de acerto — retorno vem das caudas.
**Melhores**: AMER3 vendido após o ITR de ago/2024 (reação -67%, mais -79%), IFCM3 e VVEO3 vendidos em mar/2024 (-54%/-50%), EVEN3/POSI3/BIDI11/PRIO3 comprados em 2020-21 (+70% a +143%). **Piores**: vendidos em penny stocks que dispararam (BHIA3 ago/2026 +243%, LIGT3 mar/2023 +310%, USIM5 fev/2016 +152%) — o vendido em papel < R$ 2 é o risco; **próximo**: filtro de preço mínimo/ADV para a ponta vendida e aluguel realista (muitos desses não teriam aluguel).

## E7 Rebalanceamento do Ibovespa
**Tese**: fundos de índice/ETFs compram os entrantes no último pregão antes da vigência; quem antecipa vende para eles.
**Como**: proxy da regra B3 (IN = (n/N)^(1/3)(v/V)^(2/3) em 12 meses, presença >= 95%, preço >= R$1, 85% acumulado). Entrantes = estão no proxy agora e não estavam no proxy da carteira anterior. Compra 10 pregões antes do último pregão da carteira velha e sai no fechamento desse pregão.
**Resultado**: pequeno e limpo: vol 1,7%, DD -1,1%, OOS +1,8 pp sobre o CDI (IR 0,97, P 99%, PBO 19% — o melhor PBO da frente). 132 negócios.
**Melhores**: OIBR3 e GNDI3 (ago/2019 +19%), IRBR3 (abr/2023 +30%), BEEF3 (abr/2020 +24%), AMER3 (ago/2022 +20%), BIDI11 (abr/2021 +21%). **Piores**: TEND3 abr/2026 e YDUQ3 ago/2020 (-14%).
**Próximo**: usar a 1ª prévia oficial (B3 divulga) em vez do proxy; dimensionar por % do índice esperado x ADV (pressão de compra) — dá para alavancar 3-5x dada a vol baixa.

## E8 Blocos informados — inconclusivo
Bloco vendedor (volume >= 4x, fecha na mínima, sem notícia) continua caindo (-4% em 60d, IS e OOS), mas a perna comprada não tem efeito e o fundo combinado é ruído (IR OOS -0,15, PBO 81%). Variante "só venda" perdeu no IS. **Próximo**: livro só vendido de blocos vendedores, com aluguel e filtro de liquidez, junto com insider venda e PEAD negativo ("livro de vendedores informados").

## E9 Crise corporativa — o contrarian é armadilha
Comprar queda > 20% em 3 dias com fato relevante: IS levemente positivo (2016 +16%: OIBR3 jun/2016 +137% após pedido de RJ, LIGT3 2023), OOS **-15% a.a.** com DD -73%: AMER3 jun/2024 (-93%), AMBP3 set/2025 (-90%), IRBR3 fev/2020 (-82%), AMER3 out/2022 (-92%), SEQL3, GFSA3, VVEO3. O motor escolheu "contrarian" pelo IS e o OOS desmentiu — exemplo de livro de por que não confiar no IS curto. Os estudos mostram o oposto: após queda forte com FR o papel continua caindo (mediana -6,8% em 60d; OOS -7,9%), e após pedido de RJ -24% em 120d. Vender RJ seria a tese, mas o aluguel desses papéis é raro e caro (10%+) e há squeezes (OIBR, LIGT). **Não operar contrarian em crise corporativa brasileira.**

## 4. O que tentar em seguida
1. **Livro de vendedores informados** (E3 + insider venda + PEAD negativo + bloco vendedor): todos têm -3% a -4% em 60d; diversificar reduz o risco de squeeze. Com filtro de preço >= R$ 3 e ADV >= R$ 10 mi para ter aluguel.
2. E7 com prévia oficial e alavancado; E1 com relação de troca (pairs de incorporação).
3. Recompra pela execução efetiva (VLMO tesouraria), não pelo anúncio.
4. Testar o hedge por beta (small caps emissoras têm beta > 1 — parte do alfa de E3 é beta short em quedas).
