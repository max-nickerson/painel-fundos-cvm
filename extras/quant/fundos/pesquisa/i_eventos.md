# Frente I_EVENTOS — estratégias de eventos do Brasil replicadas em EUA, Europa e Ásia (fase 2, out/2026)

Código: `quant/fundos/ideias_i_eventos.py` (`python ideias_i_eventos.py dados` baixa tudo com cache; `python ideias_i_eventos.py` roda os 9
fundos e salva `resultado/ideias_i_eventos.pkl` com `contrib`, `trades` e, no 1º item, `cobertura`). Log: `resultado/ideias_i_eventos_log.txt`;
listas completas de negócios/variantes: `resultado/ideias_i_eventos_detalhe.txt`. Corte OOS = 2021-01-01 em todos. Benchmark CDI (todos os
livros são long-short ou hedgeados); excesso em US$ sobre o T-bill (ou em moeda local, long-short) convertido com `brl()`.

## Resumo

| Fundo                                          | Escolhido no IS                                        |   IR IS | OOS a.a.   | CDI OOS   |   IR OOS | vol   | P(bater)   | PBO   |   custo x2 (pp) |   +1 dia (pp) | % var. > CDI OOS   |
|:-----------------------------------------------|:-------------------------------------------------------|--------:|:-----------|:----------|---------:|:------|:-----------|:------|----------------:|--------------:|:-------------------|
| IE01 PEAD EUA (S&P 500 ponto a ponto)          | `{'limiar': 0.07, 'hold': 20, 'lado': 'ambos'}`        |    0.16 | 12.1%      | 11.4%     |     0.14 | 5.1%  | 60%        | 28%   |            -0.1 |           0.2 | 50%                |
| IE02 Follow-on vendido EUA                     | `{'pressao': 4, 'hold': 20}`                           |   -0.07 | 11.6%      | 11.4%     |     0.07 | 2.5%  | 57%        | 5%    |             0   |          -0   | 100%               |
| IE03 Fim de lock-up EUA                        | `{'antes': 5, 'depois': 10}`                           |    0.23 | 11.7%      | 11.4%     |     0.08 | 11.4% | 55%        | 100%  |            -1.5 |           1.8 | 100%               |
| IE04 13D ativista EUA                          | `{'filtro': 'todos', 'hold': 63}`                      |    0.03 | -0.0%      | 11.4%     |    -0.46 | 19.6% | 12%        | 45%   |           -12.9 |         -13.9 | 0%                 |
| IE05 Recompra por oferta pública (SC TO-I) EUA | `{'hold': 126, 'adv_min': 1000000.0}`                  |    0.39 | 7.3%       | 11.4%     |    -0.4  | 8.6%  | 14%        | 72%   |            -4.5 |          -3.9 | 0%                 |
| IE06 Inclusão/exclusão S&P 500 e Nasdaq-100    | `{'fase': 'pos', 'lado': 'ambos'}`                     |    0.58 | 17.8%      | 11.4%     |     0.49 | 13.1% | 82%        | 14%   |             5.6 |           6   | 100%               |
| IE07 Rebalanceamento DAX, CAC 40 e NIFTY 50    | `{'fase': 'pos', 'lado': 'entra'}`                     |    0.14 | 12.4%      | 11.4%     |     0.28 | 3.3%  | 74%        | 15%   |             0.6 |           0.9 | 33%                |
| IE08 PEAD Ásia (Japão, Coreia, Hong Kong)      | `{'mercados': 'JP+KR+HK', 'limiar': 0.08, 'hold': 60}` |    0.46 | 14.3%      | 11.4%     |     0.33 | 8.7%  | 74%        | 50%   |             0.9 |           3.4 | 100%               |
| IE09 Chapter 11 EUA                            | `{'lado': 'compra', 'hold': 60}`                       |    0.4  | 11.9%      | 11.4%     |     0.1  | 5.7%  | 54%        | 15%   |             0.4 |          -0.8 | 50%                |

Veredito curto:
- **O que sobreviveu (pouco):** IE06 (pós-efetiva de índice, Nasdaq-100 + S&P) e IE08 (PEAD Ásia, perna comprada). Ambos com IR OOS ~0,3–0,5,
  robustos a custo x2 e +1 dia, 100% das variantes acima do CDI no OOS. Nenhum chega perto do follow-on brasileiro.
- **Não replicou:** follow-on vendido EUA (IE02 ~0), PEAD em large caps EUA (IE01 ~0), lock-up (IE03, PBO 100%), 13D (IE04, negativo OOS),
  recompra por tender (IE05, negativo OOS). Os EUA são o mercado mais arbitrado do mundo para esses eventos — o que no Brasil é alfa, lá é preço.
- **Intestável com dado gratuito:** Chapter 11 (IE09) — só 13% dos pedidos têm preço no Yahoo e 27 viram negócio; o "compra" que o motor
  escolheu é o lado favorecido pelo viés (os que sumiram foram a zero). Não operar.

## Dados novos (dados/, todos com cache)

| arquivo | conteúdo |
|---|---|
| `sec_indice_ie.parquet` | EDGAR full-index 2006–2026: SC 13D/SCHEDULE 13D, SC TO-I, 424B1/B4/B5, S-1, F-1 (234 mil linhas) |
| `sec_fts_8k_202.parquet` | busca textual EDGAR (EFTS) "Item 2.02" em 8-K 2006–2026 (397 mil documentos; itens do 8-K vêm no resultado) |
| `sec_fts_oferta_acoes / oferta_atm / oferta_divida.parquet` | 424B5/B4/B1 com "common stock"; ATM ("at-the-market"/"sales agreement"); dívida ("notes due") |
| `sec_fts_13d.parquet`, `sec_fts_13d_ativista.parquet` | 13D originais ("purpose of transaction") e o subconjunto com texto ativista (nominate/strategic alternatives/undervalued/proxy contest/board representation) |
| `sec_fts_cap11.parquet` | 8-K com "Chapter 11" (filtrado depois para item 1.03) |
| `sec_tickers_atual.parquet` | mapa atual CIK -> ticker da SEC |
| `wiki_indices.parquet` | mudanças de S&P 500 e Nasdaq-100 (data efetiva + **data do comunicado lida da referência**: 90%/82% dos casos), DAX (de), CAC 40 (fr), NIFTY 50 (en) |
| `wiki_sp500_atual.parquet`, `wiki_membros_asia.parquet` | S&P 500 atual (com CIK); membros atuais Nikkei 225 (ja), KOSPI 200 (ko), Hang Seng (en) |
| `y_ie_resultados_asia.parquet` | Yahoo `get_earnings_dates`: data/hora, EPS estimado e reportado — Japão/Coreia/HK de 2014 a meados de 2025 (Europa quase vazia: SAP 8 trimestres, LVMH 1) |
| `y_ie_sp / y_ie_us / y_ie_asia / y_ie_eur.parquet` | Yahoo Close (ajustado) + Volume: universo S&P histórico, tickers de eventos EUA (11,9 mil tentados, ~5,7 mil com preço), membros asiáticos + índices locais, nomes de DAX/CAC/NIFTY |

Notas de coleta: (i) o JSON de submissões da SEC por CIK é lento demais para 800 empresas (bancos têm centenas de arquivos de 424B2) — a
busca textual EFTS traz os itens do 8-K e o ticker ATUAL entre parênteses, e foi o que funcionou; (ii) EFTS limita concorrência: 4 meses em
paralelo deu 9 falhas em 12; 3 em paralelo com 0,3 s de pausa, zero falhas; (iii) a Wikipédia moveu as mudanças do S&P 500 e do Nasdaq-100
para "Historical components of ..."; Nikkei 225 só tem o ANO da mudança (ja.wiki) e Hang Seng/KOSPI/ASX/FTSE não têm tabela com datas —
ficaram de fora; (iv) a partir de dez/2024 o 13D virou "SCHEDULE 13D" estruturado (XML) e quase não tem o texto livre: 2025–26 têm poucos eventos.

## O viés de sobrevivência — medido, não presumido

**O Yahoo não tem NENHUM ticker deslistado.** Em todos os livros EUA, 100% dos negócios executados são de empresas que ainda negociam hoje
(última cotação >= set/2026). Cobertura (% dos eventos com preço) por ano:

|      |   IE01 PEAD (8-K 2.02 de membros do S&P) |   IE02 ofertas de ações (424B) |   IE03 IPOs (1º 424B4/B1) |   IE04 13D |   IE05 SC TO-I |   IE09 Chapter 11 | IE06 S&P/NDX entra   | IE06 S&P/NDX sai   |
|-----:|-----------------------------------------:|-------------------------------:|--------------------------:|-----------:|---------------:|------------------:|:---------------------|:-------------------|
| 2007 |                                       67 |                             35 |                        37 |         31 |             52 |                11 |                      |                    |
| 2008 |                                       68 |                             45 |                        56 |         32 |             43 |                 7 | 57.0                 | 52.0               |
| 2009 |                                       69 |                             54 |                        46 |         39 |             39 |                 6 | 73.0                 | 59.0               |
| 2010 |                                       70 |                             54 |                        49 |         33 |             50 |                12 | 78.0                 | 39.0               |
| 2011 |                                       71 |                             52 |                        44 |         37 |             49 |                10 | 68.0                 | 32.0               |
| 2012 |                                       73 |                             55 |                        50 |         39 |             56 |                 9 | 84.0                 | 56.0               |
| 2013 |                                       75 |                             51 |                        47 |         37 |             54 |                16 | 76.0                 | 61.0               |
| 2014 |                                       77 |                             58 |                        53 |         43 |             53 |                16 | 83.0                 | 53.0               |
| 2015 |                                       78 |                             58 |                        59 |         51 |             77 |                 8 | 79.0                 | 32.0               |
| 2016 |                                       82 |                             68 |                        66 |         50 |             69 |                18 | 85.0                 | 55.0               |
| 2017 |                                       86 |                             62 |                        69 |         55 |             56 |                12 | 92.0                 | 57.0               |
| 2018 |                                       88 |                             67 |                        74 |         56 |             75 |                12 | 81.0                 | 38.0               |
| 2019 |                                       90 |                             68 |                        69 |         59 |             72 |                14 | 84.0                 | 68.0               |
| 2020 |                                       92 |                             69 |                        71 |         62 |             72 |                14 | 97.0                 | 73.0               |
| 2021 |                                       93 |                             67 |                        65 |         65 |             71 |                23 | 96.0                 | 57.0               |
| 2022 |                                       95 |                             71 |                        83 |         67 |             69 |                37 | 100.0                | 67.0               |
| 2023 |                                       96 |                             76 |                        90 |         64 |             80 |                23 | 96.0                 | 68.0               |
| 2024 |                                       97 |                             80 |                        96 |         71 |             82 |                16 | 96.0                 | 71.0               |
| 2025 |                                       98 |                             91 |                        98 |        100 |             89 |                19 | 100.0                | 71.0               |
| 2026 |                                       99 |                             98 |                        99 |        100 |             88 |                19 | 100.0                | 90.0               |

Testes feitos:
1. **Universo ponto a ponto no PEAD (IE01):** só entra resultado de quem ESTAVA no S&P 500 na data (atual + 400 mudanças da Wikipédia desfeitas
   de trás para frente; o conjunto reconstruído tem 498–502 nomes em qualquer data). A cobertura sobe de 67% (2007) para 99% (2026); o que falta
   são empresas compradas (CFC, HNZ, BCR...) cujo resultado é simétrico. Retorno médio por negócio contra o SPY: antes de 2016 −0,1%, depois
   +0,2% — nada muda com a cobertura -> o resultado (≈ zero) é confiável.
2. **Livros de small caps (IE02–IE05):** cobertura de 30–55% antes de 2016 e 65–100% depois. Retorno médio por negócio (ação − hedge):
   13D +0,9% (antes de 2016) x −0,8% (depois); TO-I +3,2% x +1,2%; lock-up +1,6% x +0,6%. **O resultado piora quando a cobertura melhora**:
   o IS dos livros COMPRADOS (13D, TO-I) é otimista porque os alvos que quebraram somem. Nos livros VENDIDOS (follow-on, lock-up, Chapter 11)
   o viés é o contrário (o que sumiu foi a zero = ganho perdido) -> os números deles são piso.
3. **Chapter 11 (IE09):** 951 pedidos de recuperação judicial (8-K item 1.03) desde 2007, 13% com preço, 27 negociáveis (preço >= US$1, giro
   >= US$1 mi). Amostra pequena e anti-sobrevivente; ver IE09.
4. **Ásia (IE08):** membros ATUAIS dos índices (não há lista histórica gratuita) -> as ações que saíram por queda faltam. O efeito é simétrico
   para o PEAD (reação boa e ruim), mas o comprado fica otimista: por isso o resultado de IE08 deve ser descontado.

## Outros bugs/armadilhas encontrados (não reintroduzir)
- **Rebalanceio diário a peso fixo em small caps cria P&L falso.** Na 1ª versão o livro mantinha 3–5% por nome todo dia: Chapter 11 "compra"
  dava IR IS 1,3 e +25% a.a. OOS, com negócios de −99,9% de retorno e +55% de contribuição (ISUNQ, AFIIQ — preços de US$0,0001 oscilando).
  Corrigido: **compra-e-segura** (peso fixo na entrada, depois anda com o preço; custo só na entrada/saída) + filtro de preço mínimo
  (US$1–5) e giro na decisão. O teste unitário reproduz exatamente −w0 x (P_saída/P_entrada − 1).
- **Índice de preço como hedge de ação com dividendo:** Yahoo entrega ações com retorno total e ^N225/^KS11/^HSI/^FCHI/^NSEI só de preço. O
  comprado ganhava ~2% a.a. de dividendo "de graça" e o vendido pagava. Corrigido somando o dividend yield médio ao índice (DAX já é total).
  Efeito em IE08: IR IS 0,52 -> 0,46.
- `DataFrame.hist` é um método: `a.hist >= 100` quebrou o follow-on (coluna renomeada para `n_hist`).
- Ticker de preço = o ATUAL da empresa (EFTS/SEC) quando ela existe (FB->META, PCS->TMUS), senão o da época (Forms 3/4). Sem isso o Yahoo
  devolve outra empresa que herdou o ticker.
- Wikipédia: a tabela de mudanças tem rowspan (várias mudanças na mesma data) — o parser expande; o "anúncio" é a nota de rodapé mais recente
  com data <= efetiva e no máximo 60 dias antes (mediana 7 dias antes no S&P; 0 dias = mudança às pressas, fica com i0 > i1 e é descartada).

---

## IE01 PEAD EUA (S&P 500 ponto a ponto)

**Tese**: subreação ao resultado (Brasil: +5 pp/ano, ganho nas caudas). **Como**: 8-K item 2.02 de membros do S&P 500 na data; reação anormal
vs SPY do fech. t-1 ao t+1 (t = arquivamento); decide em t+1 e executa em t+2; 2% por nome; hedge SPY; custo 3–10 bps; aluguel 0,3–1%.
38,5 mil resultados, 32 mil com preço.

**Resultado**: nada. Todas as 8 variantes ficam entre −5 e +2,6 pp/ano. A perna comprada ganha +0,8% por negócio no IS (concentrado em
2009: AIG +149%, MBI +115% em março/2009), a vendida perde o mesmo. OOS ~0 nas duas. Em large caps americanas a deriva pós-resultado
foi arbitrada (literatura: desapareceu depois de ~2005). O que no Brasil vem das caudas (AMER3, IFCM3) aqui são quebras de 2008–09 (LNC, C,
HIG vendidos que voltaram 70–90%).
**Próximo**: só faria sentido em small caps (Russell 2000) e com surpresa de EPS — dado de consenso não é gratuito.

Números: escolhido `{'limiar': 0.07, 'hold': 20, 'lado': 'ambos'}`; IR IS 0.16; OOS 12.1% vs CDI 11.4% (IR 0.14, vol 5.1%, pior queda -6.2%), P(bater) 60%, PBO 28%, custo x2 -0.1 pp, +1 dia +0.2 pp. 5768 negócios, acerto 52%.

Excesso sobre o CDI por ano (pp): 2008: -3.7, 2009: +11.1, 2010: +2.7, 2011: -2.5, 2012: -2.2, 2013: -0.1, 2014: +0.6, 2015: +2.6, 2016: -2.1, 2017: +0.4, 2018: -1.3, 2019: +1.4, 2020: +0.1, 2021: -3.1, 2022: +1.2, 2023: +3.1, 2024: +6.1, 2025: +0.1, 2026: -3.7

Variantes (retorno ativo sobre o CDI):

|                                               |   IS (pp a.a.) |   OOS (pp a.a.) |
|:----------------------------------------------|---------------:|----------------:|
| {'limiar': 0.04, 'hold': 20, 'lado': 'ambos'} |            0.5 |            -0.9 |
| {'limiar': 0.04, 'hold': 20, 'lado': 'venda'} |           -2.2 |            -0.5 |
| {'limiar': 0.04, 'hold': 60, 'lado': 'ambos'} |           -1   |            -0.6 |
| {'limiar': 0.04, 'hold': 60, 'lado': 'venda'} |           -4.7 |             2.6 |
| {'limiar': 0.07, 'hold': 20, 'lado': 'ambos'} |            0.6 |             0.7 |
| {'limiar': 0.07, 'hold': 20, 'lado': 'venda'} |           -1.5 |             0.3 |
| {'limiar': 0.07, 'hold': 60, 'lado': 'ambos'} |           -1.3 |            -0.2 |
| {'limiar': 0.07, 'hold': 60, 'lado': 'venda'} |           -5   |             2.2 |

**10 melhores:**

| ativo   | lado   | entrada    | saida      |   dias |   retorno % |   contrib % |   ret - hedge % |
|:--------|:-------|:-----------|:-----------|-------:|------------:|------------:|----------------:|
| AIG     | compra | 2009-03-04 | 2009-04-01 |     20 |       148.8 |         3   |           135   |
| MBI     | compra | 2009-03-05 | 2009-04-02 |     20 |       115.3 |         2.3 |            93.1 |
| FNMA    | venda  | 2008-08-12 | 2008-09-10 |     20 |        30.6 |         1.8 |            26.1 |
| OXY     | compra | 2020-11-11 | 2020-12-10 |     20 |        79.2 |         1.6 |            76.3 |
| NCLH    | venda  | 2020-02-24 | 2020-03-23 |     20 |       185.5 |         1.5 |           155   |
| FCX     | compra | 2016-01-28 | 2016-02-26 |     20 |        68.1 |         1.4 |            64.9 |
| HIG     | venda  | 2009-02-09 | 2009-03-10 |     20 |        89.9 |         1.3 |            72.8 |
| CZR     | compra | 2020-05-13 | 2020-06-11 |     20 |        64   |         1.3 |            57.2 |
| HIG     | venda  | 2008-11-05 | 2008-12-01 |     17 |        42.4 |         1.2 |            27.8 |
| VIAV    | venda  | 2008-10-31 | 2008-12-01 |     20 |        94.3 |         1.1 |            79.1 |

**10 piores:**

| ativo   | lado   | entrada    | saida      |   dias |   retorno % |   contrib % |   ret - hedge % |
|:--------|:-------|:-----------|:-----------|-------:|------------:|------------:|----------------:|
| LNC     | venda  | 2008-11-21 | 2008-12-22 |     20 |       -77.8 |        -3.2 |           -67.4 |
| C       | venda  | 2009-03-03 | 2009-03-31 |     20 |       -69   |        -2.1 |           -54.7 |
| SMCI    | venda  | 2024-11-07 | 2024-12-06 |     20 |       -58.4 |        -1.4 |           -56.7 |
| EP      | venda  | 2012-05-07 | 2012-06-05 |     20 |       -88.8 |        -1.4 |           -94.7 |
| VTR     | compra | 2020-02-24 | 2020-03-23 |     20 |       -63.5 |        -1.3 |           -33.1 |
| PNC     | venda  | 2009-03-05 | 2009-04-02 |     20 |       -49.4 |        -1.2 |           -27.2 |
| TSLA    | venda  | 2023-01-05 | 2023-01-27 |     15 |       -40.5 |        -1.2 |           -33.9 |
| CPWR    | compra | 2007-04-25 | 2007-05-22 |     19 |       -59.2 |        -1.2 |           -60.8 |
| HIG     | compra | 2008-10-08 | 2008-10-31 |     17 |       -58.5 |        -1.2 |           -57.8 |
| LNC     | venda  | 2020-11-06 | 2020-12-07 |     20 |       -41.7 |        -1.1 |           -36.3 |

---

## IE02 Follow-on vendido EUA

**Tese**: emissor/vendedor sabe mais; a oferta pressiona por semanas (Brasil +10 pp OOS). **Como**: 424B5/B4/B1 com "common stock", sem
ATM/dívida (busca textual), empresa listada há >= 100 pregões, preço >= US$5, giro >= US$5 mi (alugável), 1ª oferta em 90 dias; vende em t+1;
hedge IWM. Filtro de pressão = volume do dia do prospecto (ou seguinte) / giro médio: confirma que houve distribuição de ações (a reação mediana
é −0,4% sem pressão e −2% com pressão >= 2x). ~50 ofertas/ano passam nos filtros (1.010 no total).

**Resultado**: zero no IS em todas as variantes (−0,6 a −0,1 pp); OOS de +0,1 a +6,4 pp (a variante sem filtro e 40 dias rende +6,4 pp
OOS, mas foi a pior no IS). O motor escolheu pressão >= 4x, 20 dias: vol 2,5%, ~0. Ganhos: ELPW 2026, CTNT 2024, ATXG 2022 — micro caps que despencaram depois da oferta; perdas: FSLY 2020, TNXP 2021, BEAM 2020 (ofertas de crescimento em bull market — o mesmo
risco do JHSF3/PRIO3 no Brasil). Nos EUA o desconto da oferta já é o ajuste: bancos colocam ao preço de equilíbrio e o mercado de
aluguel é eficiente. Viés: o que sumiu (deslistadas) seria ganho do vendido -> número é piso, mas mesmo com 50% de cobertura no IS não há sinal.

Números: escolhido `{'pressao': 4, 'hold': 20}`; IR IS -0.07; OOS 11.6% vs CDI 11.4% (IR 0.07, vol 2.5%, pior queda -2.7%), P(bater) 57%, PBO 5%, custo x2 +0.0 pp, +1 dia -0.0 pp. 338 negócios, acerto 51%.

Excesso sobre o CDI por ano (pp): 2008: -1.5, 2009: +0.7, 2010: +0.6, 2011: -0.6, 2012: +0.5, 2013: -0.4, 2014: +0.6, 2015: +1.6, 2016: -1.0, 2017: -0.3, 2018: -0.7, 2019: +0.8, 2020: -3.3, 2021: +2.0, 2022: +0.8, 2023: -1.8, 2024: +0.5, 2025: +0.1, 2026: -0.7

Variantes (retorno ativo sobre o CDI):

|                            |   IS (pp a.a.) |   OOS (pp a.a.) |
|:---------------------------|---------------:|----------------:|
| {'pressao': 0, 'hold': 20} |           -0.2 |             3.6 |
| {'pressao': 0, 'hold': 40} |           -0.4 |             6.4 |
| {'pressao': 2, 'hold': 20} |           -0.3 |             0.1 |
| {'pressao': 2, 'hold': 40} |           -0.6 |             0.9 |
| {'pressao': 4, 'hold': 20} |           -0.1 |             0.3 |
| {'pressao': 4, 'hold': 40} |           -0.6 |             0.7 |

**10 melhores:**

| ativo   | lado   | entrada    | saida      |   dias |   retorno % |   contrib % |   ret - hedge % |
|:--------|:-------|:-----------|:-----------|-------:|------------:|------------:|----------------:|
| ELPW    | venda  | 2026-02-05 | 2026-03-06 |     20 |       832.2 |         1.9 |           830   |
| CTNT    | venda  | 2024-05-17 | 2024-06-17 |     20 |       169.8 |         1.9 |           166   |
| ATXG    | venda  | 2022-09-06 | 2022-10-04 |     20 |        83.6 |         1.1 |            82.6 |
| JKS     | venda  | 2010-11-09 | 2010-12-08 |     20 |        56.9 |         0.8 |            62.1 |
| NSPR    | venda  | 2021-02-09 | 2021-03-10 |     20 |        40.8 |         0.8 |            40.3 |
| CDNL    | venda  | 2026-06-29 | 2026-07-28 |     20 |        45   |         0.7 |            42.9 |
| NB      | venda  | 2025-10-16 | 2025-11-13 |     20 |        35.5 |         0.7 |            31.8 |
| MARA    | venda  | 2017-12-14 | 2018-01-16 |     20 |        37.2 |         0.7 |            41.5 |
| SLS     | venda  | 2012-04-09 | 2012-05-07 |     20 |        38   |         0.7 |            36.9 |
| TNON    | venda  | 2024-09-18 | 2024-10-16 |     20 |        22.4 |         0.7 |            25.7 |

**10 piores:**

| ativo   | lado   | entrada    | saida      |   dias |   retorno % |   contrib % |   ret - hedge % |
|:--------|:-------|:-----------|:-----------|-------:|------------:|------------:|----------------:|
| FSLY    | venda  | 2020-05-26 | 2020-06-23 |     20 |       -52   |        -1.9 |           -48.6 |
| TNXP    | venda  | 2021-01-14 | 2021-02-12 |     20 |       -55.3 |        -1.8 |           -49.1 |
| ANVS    | venda  | 2021-05-25 | 2021-06-23 |     20 |       -49.2 |        -1.2 |           -44.8 |
| LGN     | venda  | 2026-04-10 | 2026-05-08 |     20 |       -38.5 |        -1.2 |           -30.1 |
| JOBY    | venda  | 2024-10-28 | 2024-11-25 |     20 |       -42.1 |        -1.1 |           -33.5 |
| DVN     | venda  | 2016-02-19 | 2016-03-18 |     20 |       -38   |        -1   |           -28.9 |
| BEAM    | venda  | 2020-10-05 | 2020-11-02 |     20 |       -38.7 |        -0.9 |           -39.5 |
| PDFS    | venda  | 2026-05-15 | 2026-06-15 |     20 |       -34.6 |        -0.9 |           -28.5 |
| MDGL    | venda  | 2017-12-20 | 2018-01-22 |     20 |       -32.6 |        -0.8 |           -28.4 |
| PRPL    | venda  | 2020-05-19 | 2020-06-17 |     20 |       -30.7 |        -0.8 |           -21.4 |

---

## IE03 Fim de lock-up EUA

**Tese**: no dia 180 PE/VC/fundadores podem vender. **Como**: IPO = 1º 424B4/B1 do CIK + 1º preço do Yahoo entre −3 e +10 dias (e nenhum
antes); sem SPACs (nome e preço parado em US$10); vende 5–10 pregões antes do dia 180 e recompra 10–60 depois; preço >= US$2, giro >= US$1 mi;
aluguel mínimo 3%. 1.913 IPOs com preço.

**Resultado**: janela curta (+10 dias) ~0; janela longa (+60) −3 pp IS e +17 pp OOS -> PBO 100%: o IS e o OOS discordam. O OOS de 2025–26
(+10, +15 pp) vem de micro IPOs asiáticos/de pump-and-dump que despencaram (LHAI, NPT, YDDL, BYAH, MGN) — na prática
**sem aluguel disponível**. 2021 −19 pp (bolha de IPOs: VRPX ago/2021 disparou com a ação vendida, −8,9% do PL num só nome). Como no Brasil: efeito existe na média
(−0,9% mediana por negócio), mas não paga o risco de squeeze.

Números: escolhido `{'antes': 5, 'depois': 10}`; IR IS 0.23; OOS 11.7% vs CDI 11.4% (IR 0.08, vol 11.4%, pior queda -23.1%), P(bater) 55%, PBO 100%, custo x2 -1.5 pp, +1 dia +1.8 pp. 1213 negócios, acerto 52%.

Excesso sobre o CDI por ano (pp): 2008: -0.4, 2009: +0.2, 2010: +3.8, 2011: +3.2, 2012: -2.7, 2013: -3.8, 2014: +1.9, 2015: +2.6, 2016: -0.6, 2017: +0.9, 2018: -0.7, 2019: +4.8, 2020: +0.2, 2021: -19.0, 2022: -2.8, 2023: +1.6, 2024: +0.0, 2025: +10.1, 2026: +15.0

Variantes (retorno ativo sobre o CDI):

|                             |   IS (pp a.a.) |   OOS (pp a.a.) |
|:----------------------------|---------------:|----------------:|
| {'antes': 5, 'depois': 10}  |            0.9 |             0.4 |
| {'antes': 5, 'depois': 60}  |           -2.8 |            16.8 |
| {'antes': 10, 'depois': 10} |            0.7 |             3.5 |
| {'antes': 10, 'depois': 60} |           -3   |            17.7 |

**10 melhores:**

| ativo   | lado   | entrada    | saida      |   dias |   retorno % |   contrib % |   ret - hedge % |
|:--------|:-------|:-----------|:-----------|-------:|------------:|------------:|----------------:|
| BYAH    | venda  | 2025-06-17 | 2025-07-11 |     16 |        66.8 |         2.8 |            72.8 |
| MGN     | venda  | 2026-03-18 | 2026-04-10 |     16 |        15.8 |         2.8 |            21.8 |
| MENS    | venda  | 2025-12-08 | 2025-12-31 |     16 |        10.9 |         2.6 |             9.2 |
| RYDE    | venda  | 2024-08-26 | 2024-09-18 |     16 |        14.6 |         2.6 |            13.9 |
| LHAI    | venda  | 2026-01-12 | 2026-02-04 |     16 |       297.8 |         2.5 |           297.2 |
| NPT     | venda  | 2026-04-13 | 2026-05-05 |     16 |       150.8 |         2.4 |           157.2 |
| SNDL    | venda  | 2020-01-21 | 2020-02-12 |     16 |       113.4 |         1.9 |           113.6 |
| YDDL    | venda  | 2026-03-30 | 2026-04-22 |     16 |        62.1 |         1.9 |            77.2 |
| FBLG    | venda  | 2024-07-22 | 2024-08-13 |     16 |       101.4 |         1.8 |            95.5 |
| NNOX    | venda  | 2021-02-09 | 2021-03-04 |     16 |       103.2 |         1.7 |            96.5 |

**10 piores:**

| ativo   | lado   | entrada    | saida      |   dias |   retorno % |   contrib % |   ret - hedge % |
|:--------|:-------|:-----------|:-----------|-------:|------------:|------------:|----------------:|
| VRPX    | venda  | 2021-08-09 | 2021-08-31 |     16 |       -99.4 |        -8.9 |           -97.7 |
| MSGY    | venda  | 2025-12-26 | 2026-01-21 |     16 |       -58.9 |        -3.1 |           -52.6 |
| ILAG    | venda  | 2022-12-30 | 2023-01-25 |     16 |       -66.8 |        -2.9 |           -59.6 |
| RPGL    | venda  | 2026-04-06 | 2026-04-28 |     16 |       -81.4 |        -2.6 |           -73.1 |
| GLSI    | venda  | 2021-03-17 | 2021-04-09 |     16 |       -50.3 |        -2.5 |           -54.3 |
| EDHL    | venda  | 2025-10-07 | 2025-10-29 |     16 |       -99   |        -2.5 |           -98.2 |
| LIFE    | venda  | 2026-07-21 | 2026-08-12 |     16 |       -48.1 |        -2.4 |           -46.3 |
| RYM     | venda  | 2021-07-20 | 2021-08-11 |     16 |       -46.6 |        -2.1 |           -44.1 |
| XP      | venda  | 2020-06-01 | 2020-06-23 |     16 |       -41.2 |        -1.9 |           -38.9 |
| LKNCY   | venda  | 2019-11-06 | 2019-11-29 |     16 |       -43.9 |        -1.8 |           -41.7 |

---

## IE04 13D ativista EUA

**Tese**: ativista que cruza 5% destrava valor. **Como**: 1º SC 13D (texto "purpose of transaction"), empresa-alvo = 1º nome do resultado
EFTS (com ticker atual), preço >= US$2, giro >= US$1 mi, 1 evento por empresa por ano; 27% têm texto ativista. Compra t+1, 3–12 meses, hedge IWM.

**Resultado**: negativo. IS ~0 (2009 e 2020–21 positivos: MARA nov/2020 +1.600% após 13D, ERNA, VANI, PLBY — bolha de small caps),
OOS −10 pp (2022–24: −22, −20, −29 pp). O 13D genérico é dominado por insiders/estratégicos em micro caps em queda, não por ativistas;
mesmo o filtro "ativista" fica em −0,2 a −8 pp OOS. Viés: comprado com cobertura ruim no IS -> o IS ainda é otimista.
**Próximo**: lista de ativistas reais (Elliott, Starboard, Trian, Icahn, Pershing, ValueAct, Jana, Third Point) pelo nome do filer — o EFTS
traz o nome; é a variante a testar.

Números: escolhido `{'filtro': 'todos', 'hold': 63}`; IR IS 0.03; OOS -0.0% vs CDI 11.4% (IR -0.46, vol 19.6%, pior queda -57.0%), P(bater) 12%, PBO 45%, custo x2 -12.9 pp, +1 dia -13.9 pp. 1785 negócios, acerto 47%.

Excesso sobre o CDI por ano (pp): 2008: -9.7, 2009: +10.7, 2010: +3.7, 2011: -1.3, 2012: +4.2, 2013: -2.0, 2014: -8.9, 2015: -5.6, 2016: -6.1, 2017: -1.9, 2018: +1.9, 2019: -1.3, 2020: +16.4, 2021: +26.3, 2022: -22.2, 2023: -20.2, 2024: -28.5, 2025: -3.5, 2026: -1.0

Variantes (retorno ativo sobre o CDI):

|                                     |   IS (pp a.a.) |   OOS (pp a.a.) |
|:------------------------------------|---------------:|----------------:|
| {'filtro': 'todos', 'hold': 63}     |           -0.1 |           -10.2 |
| {'filtro': 'todos', 'hold': 126}    |           -1.4 |           -16.9 |
| {'filtro': 'todos', 'hold': 252}    |           -3.3 |           -10   |
| {'filtro': 'ativista', 'hold': 63}  |           -0.4 |            -0.2 |
| {'filtro': 'ativista', 'hold': 126} |           -1.6 |            -8.2 |
| {'filtro': 'ativista', 'hold': 252} |           -1.3 |            -3.9 |

**10 melhores:**

| ativo   | lado   | entrada    | saida      |   dias |   retorno % |   contrib % |   ret - hedge % |
|:--------|:-------|:-----------|:-----------|-------:|------------:|------------:|----------------:|
| MARA    | compra | 2020-11-10 | 2021-02-11 |     63 |      1601.5 |        43.3 |          1569.9 |
| ERNA    | compra | 2021-02-01 | 2021-05-03 |     63 |       434.3 |         9.4 |           426.8 |
| VANI    | compra | 2021-01-11 | 2021-04-13 |     63 |       405.4 |         8.6 |           398.6 |
| SRNE    | compra | 2007-02-13 | 2007-05-15 |     63 |       403.4 |         8.3 |           404.1 |
| CRDF    | compra | 2020-07-06 | 2020-10-02 |     63 |       210.5 |         6.3 |           203.6 |
| DAC     | compra | 2020-11-11 | 2021-02-12 |     63 |       205.6 |         5.5 |           173.5 |
| REAL    | compra | 2024-11-04 | 2025-02-06 |     63 |       177.1 |         5.3 |           174   |
| PLBY    | compra | 2021-03-04 | 2021-06-03 |     63 |       284.6 |         5.2 |           278.2 |
| NIO     | compra | 2020-06-22 | 2020-09-21 |     63 |       153.1 |         4.6 |           149.2 |
| UP      | compra | 2023-09-27 | 2023-12-27 |     63 |       152.9 |         4.5 |           137.6 |

**10 piores:**

| ativo   | lado   | entrada    | saida      |   dias |   retorno % |   contrib % |   ret - hedge % |
|:--------|:-------|:-----------|:-----------|-------:|------------:|------------:|----------------:|
| ONCO    | compra | 2024-09-27 | 2024-12-27 |     63 |       -93.6 |        -2.8 |           -93.7 |
| GMVDF   | compra | 2023-01-31 | 2023-05-02 |     63 |       -91.3 |        -2.8 |           -80.2 |
| BW      | compra | 2017-05-23 | 2017-08-22 |     63 |       -83.1 |        -2.5 |           -82.5 |
| CENN    | compra | 2020-06-29 | 2020-09-28 |     63 |       -81.9 |        -2.5 |           -88.5 |
| CLF     | compra | 2008-07-18 | 2008-10-16 |     63 |       -72.3 |        -2.2 |           -50.2 |
| SDA     | compra | 2023-05-31 | 2023-08-30 |     63 |       -71.9 |        -2.2 |           -79.5 |
| JCSE    | compra | 2022-05-25 | 2022-08-25 |     63 |       -82.8 |        -2.1 |           -91.9 |
| GETY    | compra | 2022-08-02 | 2022-10-31 |     63 |       -79.9 |        -2.1 |           -77.7 |
| RNAZ    | compra | 2024-06-24 | 2024-09-23 |     63 |       -70.3 |        -2.1 |           -78.6 |
| ALTO    | compra | 2008-04-04 | 2008-07-03 |     63 |       -67.4 |        -2   |           -60.9 |

---

## IE05 Recompra por oferta pública (SC TO-I) EUA

**Tese**: tender offer de recompra = compra firme com prêmio (diferente do "programa" brasileiro). **Como**: SC TO-I (sem fundos fechados/BDCs/
bancos), 1 por empresa a cada 6 meses, compra no fechamento seguinte, 1–6 meses, hedge IWM.

**Resultado**: IS levemente positivo só no prazo longo (+2 pp com 126 dias: 2009 e 2020–21, MSTR ago/2020 +637%, APVO, LAMR 2009),
OOS negativo em TODAS as 6 variantes (−0,1 a −4,8 pp; 2022 −13, 2023 −9, 2026 −11). Muitas TO-I recentes são de empresas em
reestruturação (troca de warrants, recompra de micro caps em queda: ELAB, RBNE, GROV, XELA). O sinal "gestão compra" não sobrevive.

Números: escolhido `{'hold': 126, 'adv_min': 1000000.0}`; IR IS 0.39; OOS 7.3% vs CDI 11.4% (IR -0.40, vol 8.6%, pior queda -9.7%), P(bater) 14%, PBO 72%, custo x2 -4.5 pp, +1 dia -3.9 pp. 513 negócios, acerto 54%.

Excesso sobre o CDI por ano (pp): 2008: -1.3, 2009: +11.5, 2010: -4.6, 2011: +2.8, 2012: -1.7, 2013: -3.8, 2014: +0.3, 2015: +0.5, 2016: +4.2, 2017: +2.6, 2018: +5.9, 2019: -4.0, 2020: +14.1, 2021: +13.5, 2022: -13.4, 2023: -9.4, 2024: +1.1, 2025: +0.4, 2026: -11.3

Variantes (retorno ativo sobre o CDI):

|                                      |   IS (pp a.a.) |   OOS (pp a.a.) |
|:-------------------------------------|---------------:|----------------:|
| {'hold': 21, 'adv_min': 1000000.0}   |           -0.1 |            -1.7 |
| {'hold': 21, 'adv_min': 10000000.0}  |           -0.3 |            -0.1 |
| {'hold': 63, 'adv_min': 1000000.0}   |            0.6 |            -4.8 |
| {'hold': 63, 'adv_min': 10000000.0}  |            0.2 |            -1.4 |
| {'hold': 126, 'adv_min': 1000000.0}  |            2.1 |            -3.6 |
| {'hold': 126, 'adv_min': 10000000.0} |            0.7 |            -2.2 |

**10 melhores:**

| ativo   | lado   | entrada    | saida      |   dias |   retorno % |   contrib % |   ret - hedge % |
|:--------|:-------|:-----------|:-----------|-------:|------------:|------------:|----------------:|
| MSTR    | compra | 2020-08-12 | 2021-02-11 |    126 |       636.7 |        19.1 |           591.9 |
| APVO    | compra | 2020-06-30 | 2020-12-29 |    126 |       317.2 |         9.5 |           280.5 |
| FSLR    | compra | 2007-06-07 | 2007-12-05 |    126 |       213.9 |         6.5 |           221.9 |
| ARQT    | compra | 2024-01-17 | 2024-07-18 |    126 |       185   |         5.6 |           172.4 |
| LAMR    | compra | 2009-03-24 | 2009-09-22 |    126 |       185.4 |         5.6 |           135.4 |
| STOK    | compra | 2023-11-03 | 2024-05-07 |    126 |       173.1 |         5.3 |           157.9 |
| AMCX    | compra | 2020-09-17 | 2021-03-19 |    126 |       173.9 |         5.2 |           125.3 |
| AMD     | compra | 2009-06-30 | 2009-12-29 |    126 |       151.8 |         4.6 |           126.9 |
| PANW    | compra | 2026-02-20 | 2026-08-21 |    126 |       136.4 |         4.1 |           124.6 |
| GNW     | compra | 2009-07-14 | 2010-01-12 |    126 |       133.8 |         4   |           104.7 |

**10 piores:**

| ativo   | lado   | entrada    | saida      |   dias |   retorno % |   contrib % |   ret - hedge % |
|:--------|:-------|:-----------|:-----------|-------:|------------:|------------:|----------------:|
| ELAB    | compra | 2024-10-07 | 2025-04-09 |    126 |       -97.4 |        -3   |           -83.3 |
| RBNE    | compra | 2026-03-25 | 2026-09-24 |    126 |       -93.4 |        -2.8 |          -103.8 |
| MGM     | compra | 2008-09-09 | 2009-03-11 |    126 |       -91.7 |        -2.8 |           -43.9 |
| GROV    | compra | 2022-09-27 | 2023-03-29 |    126 |       -90.2 |        -2.7 |           -95.3 |
| CSIQ    | compra | 2008-05-28 | 2008-11-24 |    126 |       -88.7 |        -2.7 |           -47.7 |
| XELA    | compra | 2022-01-27 | 2022-07-29 |    126 |       -87   |        -2.6 |           -84.8 |
| UTSI    | compra | 2008-09-05 | 2009-03-09 |    126 |       -79.9 |        -2.4 |           -28.3 |
| FOXO    | compra | 2023-04-28 | 2023-10-27 |    126 |       -78.3 |        -2.4 |           -69.2 |
| SHO     | compra | 2008-06-03 | 2008-12-01 |    126 |       -78.9 |        -2.4 |           -35.8 |
| FUBO    | compra | 2025-11-25 | 2026-05-29 |    126 |       -73.4 |        -2.2 |           -90.4 |

---

## IE06 Inclusão/exclusão S&P 500 e Nasdaq-100

**Tese**: fundos de índice compram quem entra na véspera da efetiva sem olhar preço. **Como**: S&P 500 e Nasdaq-100 2008+ (552 mudanças;
1.108 pontas). pre = compra entrante/vende excluída no fechamento seguinte ao COMUNICADO (data da referência) e zera na véspera da efetiva;
pos = depois da efetiva vende quem entrou/compra quem saiu por 20 pregões (executa no fechamento da véspera, junto com os fundos de índice).
10% por nome, hedge SPY/QQQ, custo 3–10 bps.

**Resultado**: o "pre" (o fundo brasileiro E7) não funciona nos EUA (−0,7/−1,2 pp IS): o salto acontece na abertura seguinte ao comunicado e o
resto é arbitrado. O que paga é a **reversão depois da efetiva**: escolhido pos/ambos, IR IS 0,58, OOS 17,8% vs 11,4% (IR 0,49, P 82%,
PBO 14%), custo x2 +5,6 pp, +1 dia +6,0 pp, 100% das variantes acima do CDI no OOS.
De onde vem: IS = **excluídas do S&P compradas na crise** (UAL jul/2008 +160%, FMCC, MBI dez/2009 +67%, PCG jan/2019 +143% depois da
falência da PG&E) — +92% de contribuição em 107 negócios; OOS = **Nasdaq-100** dos dois lados (+43% em 49 negócios: RIVN comprada após sair em
jun/2023 +65%; RKLB e CRWV vendidas após entrar em jun/2026 +50%), enquanto o S&P OOS ficou ~0. Piores: SNDK vendida após entrar em
abr/2026 (−40%), LCID comprada após sair (−42%), ILMN/COHR/LULU entrantes que continuaram subindo.
**Ressalva**: vol 13% para um ganho de 6 pp — é um livro de poucas posições (10% cada) com cauda; o IS depende de 2008 (+49 pp).

Números: escolhido `{'fase': 'pos', 'lado': 'ambos'}`; IR IS 0.58; OOS 17.8% vs CDI 11.4% (IR 0.49, vol 13.1%, pior queda -13.1%), P(bater) 82%, PBO 14%, custo x2 +5.6 pp, +1 dia +6.0 pp. 687 negócios, acerto 53%.

Excesso sobre o CDI por ano (pp): 2008: +49.0, 2009: +5.2, 2010: +16.5, 2011: +5.9, 2012: -3.7, 2013: +6.3, 2014: -3.6, 2015: +3.7, 2016: -3.0, 2017: -0.8, 2018: +1.7, 2019: +9.3, 2020: -1.6, 2021: +2.2, 2022: +16.0, 2023: +8.2, 2024: -1.3, 2025: +2.0, 2026: +6.4

Variantes (retorno ativo sobre o CDI):

|                                      |   IS (pp a.a.) |   OOS (pp a.a.) |
|:-------------------------------------|---------------:|----------------:|
| {'fase': 'pre', 'lado': 'entra'}     |           -0.7 |             1.6 |
| {'fase': 'pre', 'lado': 'ambos'}     |           -1.2 |             3.2 |
| {'fase': 'pos', 'lado': 'entra'}     |            0.1 |             4.9 |
| {'fase': 'pos', 'lado': 'ambos'}     |            6   |             5.8 |
| {'fase': 'pre+pos', 'lado': 'entra'} |           -0.5 |             6.7 |
| {'fase': 'pre+pos', 'lado': 'ambos'} |            4.8 |             9.4 |

**10 melhores:**

| ativo   | lado   | entrada    | saida      |   dias |   retorno % |   contrib % |   ret - hedge % |
|:--------|:-------|:-----------|:-----------|-------:|------------:|------------:|----------------:|
| UAL     | compra | 2008-07-18 | 2008-08-15 |     20 |       159.9 |        16   |           156.7 |
| PCG     | compra | 2019-01-17 | 2019-02-15 |     20 |       143   |        14.3 |           137.7 |
| FMCC    | compra | 2008-09-11 | 2008-10-09 |     20 |        74.5 |         7.4 |           101.8 |
| MBI     | compra | 2009-12-17 | 2010-01-19 |     20 |        66.5 |         6.6 |            61.5 |
| RIVN    | compra | 2023-06-16 | 2023-07-18 |     20 |        65.3 |         6.5 |            60.7 |
| CPRI    | compra | 2020-05-11 | 2020-06-09 |     20 |        46.9 |         4.7 |            37.2 |
| SII     | compra | 2010-08-25 | 2010-09-23 |     20 |        44   |         4.3 |            37.2 |
| CRM     | venda  | 2008-09-11 | 2008-10-09 |     20 |        61.2 |         4.1 |            33.8 |
| RKLB    | venda  | 2026-06-18 | 2026-07-20 |     20 |        50.2 |         3.9 |            44   |
| CRWV    | venda  | 2026-06-18 | 2026-07-20 |     20 |        53.6 |         3.8 |            47.4 |

**10 piores:**

| ativo   | lado   | entrada    | saida      |   dias |   retorno % |   contrib % |   ret - hedge % |
|:--------|:-------|:-----------|:-----------|-------:|------------:|------------:|----------------:|
| SNDK    | venda  | 2026-04-17 | 2026-05-15 |     20 |       -40   |        -5.3 |           -36.2 |
| LCID    | compra | 2023-12-15 | 2024-01-17 |     20 |       -42   |        -4.2 |           -42.3 |
| ILMN    | venda  | 2013-12-20 | 2014-01-22 |     20 |       -28.8 |        -3.8 |           -27.3 |
| COHR    | venda  | 2026-03-20 | 2026-04-20 |     20 |       -31.2 |        -3.7 |           -22.2 |
| P       | venda  | 2026-09-18 | 2026-10-14 |     18 |       -29   |        -3.6 |           -28.3 |
| FSLR    | compra | 2012-04-20 | 2012-05-18 |     20 |       -33.9 |        -3.4 |           -27.9 |
| ETSY    | venda  | 2020-09-18 | 2020-10-16 |     20 |       -26.2 |        -3.2 |           -21.2 |
| LULU    | venda  | 2018-12-21 | 2019-01-23 |     20 |       -25.3 |        -3.2 |           -16.1 |
| CE      | compra | 2025-03-21 | 2025-04-21 |     20 |       -31.4 |        -3.1 |           -22.2 |
| MRNA    | venda  | 2021-07-20 | 2021-08-17 |     20 |       -30.9 |        -3.1 |           -27.9 |

---

## IE07 Rebalanceamento DAX, CAC 40 e NIFTY 50

**Tese**: mesmo fluxo de índice onde há menos arbitradores. **Como**: só data efetiva (Wikipédia); 119 negócios executáveis; ~75% dos
nomes com preço (faltam Hypo Real Estate, Postbank, MAN, Wirecard, EDF, Alcatel, Gemalto, Natixis, Satyam, HDFC, Cairn...).
pre5/pre10 só em revisões regulares (o comunicado sai 2–4 semanas antes, então entrar 5–10 pregões antes não usa informação futura).

**Resultado**: pre negativo em tudo (−0,5 a −2,5 pp): sem a data do comunicado, entrar 5–10 dias antes já é tarde. pos (vender o entrante após
a efetiva) ~+0,4 IS / +1,0 OOS, vol 3% — o DAX dá o ganho (K+S vendida após entrar em set/2008, em plena crise; HEI 2010; CBK 2023),
o NIFTY perde (Axis Bank 2009, IndusInd 2013, Jio Financial 2025 continuaram subindo). Pequeno demais para ser fundo.

Números: escolhido `{'fase': 'pos', 'lado': 'entra'}`; IR IS 0.14; OOS 12.4% vs CDI 11.4% (IR 0.28, vol 3.3%, pior queda -2.8%), P(bater) 74%, PBO 15%, custo x2 +0.6 pp, +1 dia +0.9 pp. 119 negócios, acerto 47%.

Excesso sobre o CDI por ano (pp): 2008: +2.1, 2009: -4.5, 2010: -0.0, 2011: +3.3, 2012: +0.3, 2013: -0.1, 2014: -2.6, 2015: +1.2, 2016: -0.6, 2017: -3.3, 2018: +2.0, 2019: +0.5, 2020: +5.2, 2021: +5.7, 2022: -0.4, 2023: +1.3, 2024: -1.2, 2025: -1.3, 2026: +1.0

Variantes (retorno ativo sobre o CDI):

|                                    |   IS (pp a.a.) |   OOS (pp a.a.) |
|:-----------------------------------|---------------:|----------------:|
| {'fase': 'pre5', 'lado': 'entra'}  |           -0.6 |            -1.8 |
| {'fase': 'pre5', 'lado': 'ambos'}  |           -2.5 |            -2.4 |
| {'fase': 'pre10', 'lado': 'entra'} |           -0.6 |            -1.3 |
| {'fase': 'pre10', 'lado': 'ambos'} |           -2   |            -2.3 |
| {'fase': 'pos', 'lado': 'entra'}   |            0.4 |             1   |
| {'fase': 'pos', 'lado': 'ambos'}   |           -1.3 |             2.4 |

**10 melhores:**

| ativo       | lado   | entrada    | saida      |   dias |   retorno % |   contrib % |   ret - hedge % |
|:------------|:-------|:-----------|:-----------|-------:|------------:|------------:|----------------:|
| SDF.DE      | venda  | 2008-09-19 | 2008-10-17 |     20 |        51.2 |         6.2 |            28.5 |
| RPOWER.NS   | venda  | 2008-09-09 | 2008-10-08 |     21 |        19.7 |         2.7 |            -1.5 |
| HEI.DE      | venda  | 2010-06-18 | 2010-07-16 |     20 |        19.8 |         2.7 |            17   |
| CBK.DE      | venda  | 2023-02-24 | 2023-03-24 |     20 |        15   |         2.5 |            13.3 |
| ENGI.PA     | venda  | 2008-07-21 | 2008-08-18 |     20 |        17.4 |         2.3 |            20.5 |
| JSWSTEEL.NS | venda  | 2018-09-27 | 2018-10-29 |     22 |        16.2 |         2.2 |             9.7 |
| VOW3.DE     | venda  | 2009-12-22 | 2010-01-25 |     23 |        13.8 |         1.9 |             8.5 |
| NOKIA.HE    | venda  | 2016-01-06 | 2016-02-03 |     20 |        12   |         1.8 |             6.6 |
| ENR.DE      | venda  | 2022-09-16 | 2022-10-14 |     20 |        11.1 |         1.7 |             8.7 |
| ERF.PA      | venda  | 2021-09-16 | 2021-10-14 |     20 |        12.2 |         1.7 |            13.4 |

**10 piores:**

| ativo         | lado   | entrada    | saida      |   dias |   retorno % |   contrib % |   ret - hedge % |
|:--------------|:-------|:-----------|:-----------|-------:|------------:|------------:|----------------:|
| AXISBANK.NS   | venda  | 2009-03-26 | 2009-04-29 |     24 |       -27.9 |        -4.9 |           -15.1 |
| WLN.PA        | venda  | 2020-03-20 | 2020-04-21 |     22 |       -21.6 |        -3.3 |           -13.7 |
| INDUSINDBK.NS | venda  | 2013-03-27 | 2013-04-30 |     24 |       -15.9 |        -2.6 |           -10.7 |
| IOC.NS        | venda  | 2017-03-30 | 2017-05-01 |     22 |       -15   |        -2.6 |           -13.4 |
| JIOFIN.NS     | venda  | 2025-03-27 | 2025-04-30 |     24 |       -14.3 |        -2.4 |           -11.1 |
| DRREDDY.NS    | venda  | 2010-09-30 | 2010-10-28 |     20 |       -12.7 |        -2.2 |           -13.3 |
| RHM.DE        | venda  | 2023-03-17 | 2023-04-18 |     22 |       -13.1 |        -2.1 |            -5.6 |
| ETERNAL.NS    | venda  | 2025-03-27 | 2025-04-30 |     24 |       -12.2 |        -2   |            -8.9 |
| LR.PA         | venda  | 2011-12-16 | 2012-01-17 |     22 |       -11.4 |        -1.9 |            -1.1 |
| ZEEL.NS       | venda  | 2014-09-18 | 2014-10-22 |     24 |       -10.6 |        -1.7 |           -11.9 |

---

## IE08 PEAD Ásia (Japão, Coreia, Hong Kong)

**Tese**: subreação a resultado na Ásia, com dado de surpresa. **Como**: datas e EPS (estimado x reportado) do Yahoo 2014–2025 para os membros
atuais do Nikkei 225, KOSPI 200 e Hang Seng (18 mil resultados); reação vs índice local t-1..t+1; decide t+1; 3% por nome; hedge índice local
(com dividend yield); custo JP 10 bps, KR 20 (imposto de venda), HK 22 (selo); aluguel 1–2%; sem venda na Coreia nas proibições
(2008–09, 2011, mar/2020–mai/2021, nov/2023–mar/2025).

**Resultado**: escolhido JP+KR+HK, |reação| >= 8%, 60 dias: IR IS 0,46, OOS 14,3% vs 11,4% (IR 0,33, P 74%, PBO 50%), custo x2 +0,9 pp,
+1 dia +3,4 pp; todas as 8 variantes acima do CDI no OOS (mediana +2,5 pp). **Todo o ganho é da perna comprada** (+2 a +3% por negócio
contra o índice; Coreia e Japão), a vendida perde (−1,3 a −2,6% IS). Melhores: Hanjin Kal (009420.KS nov/2017 +109%), Hyosung Heavy
(298040.KS fev/2025 +107%), Samyang Foods (003230.KS fev/2025 +86%), Furukawa Electric (5803.T fev/2024 +81%), Hanwha Aerospace/Korea Zinc.
Piores: vendidos que viraram (Advantest 6857.T 2023 −51% duas vezes, Panasonic 6753.T nov/2020 −50%, Hyundai Electric 2025).
**Ressalva**: membros ATUAIS (sobreviventes) inflam justamente a perna comprada; PBO 50%. Para operar: só comprado em resultado positivo
forte (>= 8%) com hedge de índice — é o equivalente asiático do PEAD brasileiro, mas metade do tamanho.

Números: escolhido `{'mercados': 'JP+KR+HK', 'limiar': 0.08, 'hold': 60}`; IR IS 0.46; OOS 14.3% vs CDI 11.4% (IR 0.33, vol 8.7%, pior queda -12.2%), P(bater) 74%, PBO 50%, custo x2 +0.9 pp, +1 dia +3.4 pp. 2152 negócios, acerto 51%.

Excesso sobre o CDI por ano (pp): 2014: -0.4, 2015: -1.2, 2016: +4.6, 2017: +9.2, 2018: +5.9, 2019: -6.3, 2020: +9.9, 2021: +7.6, 2022: -5.3, 2023: -4.2, 2024: +1.5, 2025: +16.8, 2026: -0.1

Variantes (retorno ativo sobre o CDI):

|                                                      |   IS (pp a.a.) |   OOS (pp a.a.) |
|:-----------------------------------------------------|---------------:|----------------:|
| {'mercados': 'JP+KR+HK', 'limiar': 0.05, 'hold': 20} |           -1.5 |             2   |
| {'mercados': 'JP+KR+HK', 'limiar': 0.05, 'hold': 60} |            1.6 |             1.9 |
| {'mercados': 'JP+KR+HK', 'limiar': 0.08, 'hold': 20} |           -1.6 |             3.3 |
| {'mercados': 'JP+KR+HK', 'limiar': 0.08, 'hold': 60} |            3.3 |             2.7 |
| {'mercados': 'JP', 'limiar': 0.05, 'hold': 20}       |           -0.4 |             2.7 |
| {'mercados': 'JP', 'limiar': 0.05, 'hold': 60}       |           -0.2 |             1.2 |
| {'mercados': 'JP', 'limiar': 0.08, 'hold': 20}       |           -1.4 |             2.4 |
| {'mercados': 'JP', 'limiar': 0.08, 'hold': 60}       |           -0.5 |             1.8 |

**10 melhores:**

| ativo     | lado   | entrada    | saida      |   dias |   retorno % |   contrib % |   ret - hedge % |
|:----------|:-------|:-----------|:-----------|-------:|------------:|------------:|----------------:|
| 009420.KS | compra | 2017-11-16 | 2018-02-08 |     60 |       109   |         3.3 |           113.6 |
| 298040.KS | compra | 2025-02-05 | 2025-07-22 |    119 |       106.8 |         3.2 |            79.4 |
| 003230.KS | compra | 2025-02-07 | 2025-08-11 |    131 |        85.8 |         2.6 |            57.5 |
| 185750.KS | compra | 2015-11-06 | 2016-02-01 |     60 |        81.5 |         2.4 |            86.8 |
| 5803.T    | compra | 2024-02-12 | 2024-05-06 |     60 |        81.1 |         2.4 |            77   |
| 4043.T    | compra | 2016-05-16 | 2016-10-25 |    116 |        80.4 |         2.4 |            74   |
| 010130.KS | compra | 2024-08-09 | 2024-11-01 |     60 |        95.3 |         2.4 |            96.7 |
| 377300.KS | compra | 2022-11-03 | 2023-01-26 |     60 |        75.9 |         2.3 |            69.5 |
| 014680.KS | compra | 2020-05-19 | 2020-08-11 |     60 |        75.3 |         2.2 |            52.6 |
| 010060.KS | compra | 2020-10-30 | 2021-01-22 |     60 |        73.9 |         2.2 |            34.8 |

**10 piores:**

| ativo     | lado   | entrada    | saida      |   dias |   retorno % |   contrib % |   ret - hedge % |
|:----------|:-------|:-----------|:-----------|-------:|------------:|------------:|----------------:|
| 6753.T    | venda  | 2020-11-10 | 2021-02-02 |     60 |       -49.7 |        -2.7 |           -35.3 |
| 6857.T    | venda  | 2023-04-28 | 2023-07-21 |     60 |       -51   |        -2.6 |           -38.5 |
| 267260.KS | venda  | 2025-04-24 | 2025-07-17 |     60 |       -41.9 |        -1.9 |           -14.8 |
| 3436.T    | venda  | 2017-08-10 | 2017-11-02 |     60 |       -38.5 |        -1.7 |           -23.8 |
| 9107.T    | venda  | 2023-11-07 | 2024-01-30 |     60 |       -39.8 |        -1.7 |           -27.5 |
| 2015.HK   | compra | 2024-02-28 | 2024-05-22 |     60 |       -53.5 |        -1.6 |           -70.6 |
| 6857.T    | venda  | 2023-11-02 | 2024-01-25 |     60 |       -38   |        -1.6 |           -24.1 |
| 3659.T    | venda  | 2015-02-16 | 2015-05-11 |     60 |       -35.8 |        -1.5 |           -26.3 |
| 000100.KS | venda  | 2018-11-01 | 2019-01-25 |     60 |       -40.3 |        -1.5 |           -32.3 |
| 267270.KS | venda  | 2018-11-01 | 2019-01-25 |     60 |       -36.1 |        -1.4 |           -28.1 |

---

## IE09 Chapter 11 EUA

**Tese**: na recuperação judicial a ação vai a zero (credores na frente); no Brasil o contrarian perdeu 15%/ano. **Como**: 8-K item 1.03
(951 pedidos 2007+), vende (ou compra) no fechamento seguinte, aluguel 20% a.a., custo >= 50 bps, preço >= US$1 e giro >= US$1 mi.

**Resultado**: **intestável** — 13% de cobertura e 27 negócios. O motor escolheu "compra" (IR IS 0,4, OOS ~0): PCG 2019 +175%, MPU 2021, GTX
2020, AAL 2011 — empresas grandes que sobreviveram ao Chapter 11 e por isso continuam no Yahoo. Os ~820 pedidos sem preço são exatamente as
ações que foram a zero (o ganho do vendido). Conclusão de mesa igual à do Brasil: não comprar ação em recuperação judicial; a venda não dá para
medir sem base paga de preços deslistados (CRSP/Norgate) e, na prática, quase não há aluguel.

Números: escolhido `{'lado': 'compra', 'hold': 60}`; IR IS 0.40; OOS 11.9% vs CDI 11.4% (IR 0.10, vol 5.7%, pior queda -7.7%), P(bater) 54%, PBO 15%, custo x2 +0.4 pp, +1 dia -0.8 pp. 27 negócios, acerto 52%.

Excesso sobre o CDI por ano (pp): 2008: +3.6, 2009: +1.0, 2010: -0.9, 2011: -0.0, 2012: +1.5, 2013: -0.1, 2014: +0.5, 2015: -0.2, 2016: -0.1, 2017: +1.9, 2018: -1.0, 2019: +2.5, 2020: +4.7, 2021: +9.2, 2022: -0.1, 2023: -5.0, 2024: -0.2, 2025: -0.1, 2026: -1.0

Variantes (retorno ativo sobre o CDI):

|                                 |   IS (pp a.a.) |   OOS (pp a.a.) |
|:--------------------------------|---------------:|----------------:|
| {'lado': 'vende', 'hold': 20}   |           -0.9 |            -1.6 |
| {'lado': 'vende', 'hold': 60}   |           -1.8 |            -1.3 |
| {'lado': 'vende', 'hold': 120}  |           -2.4 |            -9.2 |
| {'lado': 'compra', 'hold': 20}  |            0.6 |             1.2 |
| {'lado': 'compra', 'hold': 60}  |            1.2 |             0.6 |
| {'lado': 'compra', 'hold': 120} |            1.2 |             7.3 |

**10 melhores:**

| ativo   | lado   | entrada    | saida      |   dias |   retorno % |   contrib % |   ret - hedge % |
|:--------|:-------|:-----------|:-----------|-------:|------------:|------------:|----------------:|
| MPU     | compra | 2021-03-31 | 2021-06-25 |     60 |       179.4 |         8.9 |           174.1 |
| PCG     | compra | 2019-01-15 | 2019-04-11 |     60 |       175.3 |         8.7 |           166.1 |
| GTX     | compra | 2020-09-22 | 2020-12-16 |     60 |       146.8 |         7.3 |           115.8 |
| AAL     | compra | 2011-11-30 | 2012-02-28 |     60 |        57   |         2.8 |            44.8 |
| NRG     | compra | 2017-06-15 | 2017-09-11 |     60 |        43.6 |         2.1 |            43.3 |
| PPC     | compra | 2009-12-11 | 2010-03-11 |     60 |        41.3 |         2   |            28.3 |
| AAL     | compra | 2013-10-24 | 2014-01-22 |     60 |        37.6 |         1.8 |            31.6 |
| HOS     | compra | 2020-05-26 | 2020-08-19 |     60 |        35.8 |         1.7 |            22.8 |
| BBIG    | compra | 2021-04-22 | 2021-07-19 |     60 |        24.9 |         1.2 |            29.2 |
| ASB     | compra | 2008-08-11 | 2008-11-04 |     60 |        15.4 |         0.7 |            42.7 |

**10 piores:**

| ativo   | lado   | entrada    | saida      |   dias |   retorno % |   contrib % |   ret - hedge % |
|:--------|:-------|:-----------|:-----------|-------:|------------:|------------:|----------------:|
| KALRQ   | compra | 2023-04-05 | 2023-07-03 |     60 |       -94.8 |        -4.8 |          -101.9 |
| ACET    | compra | 2019-09-23 | 2019-12-17 |     60 |       -87.9 |        -4.5 |           -94.3 |
| ALTO    | compra | 2010-06-14 | 2010-09-08 |     60 |       -20   |        -1.1 |           -17.5 |
| OLOX    | compra | 2026-05-05 | 2026-07-31 |     60 |       -19.8 |        -1   |           -22.2 |
| LEU     | compra | 2014-03-06 | 2014-06-02 |     60 |       -14.1 |        -0.8 |            -8.1 |
| TREE    | compra | 2019-07-26 | 2019-10-21 |     60 |        -9.3 |        -0.5 |            -7.2 |
| CCO     | compra | 2018-03-16 | 2018-06-12 |     60 |        -6.5 |        -0.4 |           -12.5 |
| ECHO    | compra | 2026-08-04 | 2026-10-14 |     50 |        -4.8 |        -0.3 |             5.7 |
| BBDC    | compra | 2022-03-04 | 2022-05-31 |     60 |        -3.3 |        -0.2 |             3.4 |
| SHOE    | compra | 2008-07-17 | 2008-10-10 |     60 |        -1.3 |        -0.1 |            22.1 |

---

## O que tentar em seguida
1. **IE06 com tamanho por fluxo**: dimensionar pela demanda dos fundos de índice (peso no índice x AUM indexado / giro) e separar Nasdaq-100
   (onde o OOS está) de S&P; testar a reversão das excluídas só em revisões regulares (sem as de crise).
2. **IE08 só comprado + Europa**: PEAD comprado com surpresa positiva; para Europa, extrair datas de resultado dos próprios preços/volume
   (salto + volume 3x em temporada) — o Yahoo não tem as datas europeias.
3. **Ativistas de verdade (IE04)**: filtrar o 13D pelo nome do filer (lista de ~30 ativistas conhecidos) — o EFTS já traz o nome.
4. **Preços de deslistadas**: sem CRSP/Norgate (pagos) merger arb, Chapter 11 e o IS de small caps continuam com viés; tudo que é comprado
   em small cap nos EUA deve ser lido como teto.
5. Lição para o multiestratégia: as estratégias de eventos que funcionam no Brasil (follow-on, PEAD, OPA) dependem de **mercado pouco
   arbitrado**; nos EUA o mesmo evento já está no preço. A replicação útil é na Ásia (Coreia/Japão) e em índices com menos indexadores.
