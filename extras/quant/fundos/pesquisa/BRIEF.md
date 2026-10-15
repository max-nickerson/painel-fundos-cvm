# Rodada 2 — brief comum para todas as frentes

Somos gestores de um fundo PRÓPRIO (dinheiro nosso). Objetivo: achar alfa real, de trader experiente
(30+ anos de mesa), não "fator de baixa vol / momentum / ML genérico". Cada fundo deve ter uma TESE
de mesa: "compro X porque o mercado está precificando Y e eu acho Z", "vendo Y e faço hedge com W porque...".
Mercados menos arbitrados, custo de entrada alto, risco maior — tudo vale, desde que testado com honestidade.

## Pastas
- Código: `C:/Users/maxpn/OneDrive/Documents/itau/quant/fundos/` (rode python a partir daqui; `PYTHONIOENCODING=utf-8 python -W ignore ...`)
- Dados novos que você baixar: `quant/fundos/dados/` (parquet, um arquivo por fonte, com cache — nunca re-baixar o que já existe)
- Notas de pesquisa: `quant/fundos/pesquisa/<frente>.md`
- Resultados: `quant/fundos/resultado/ideias_<frente>.pkl`

## Dados já disponíveis (leia antes de baixar algo)
`quant/fundos/dados/` (= `base.D`):
- `b3_vista.parquet` — COTAHIST à vista 2008+ (2,1 mi linhas, 2.909 tickers incl. FIIs, units, ~870 BDRs, sem viés de sobrevivência; preços NÃO ajustados por proventos). Colunas incluem data, ticker, fech, oferta_compra, oferta_venda, negocios, volume...
- `b3_opcoes.parquet` — opções B3 (25 maiores ativos-objeto) com melhor oferta, strike, venc, tipo C/P, negocios, volume
- `b3_termo.parquet` — termo
- `y_adr`, `y_br_local`, `y_fx` (26 moedas), `y_etf` (86 ETFs globais), `y_idx` (índices, ^VIX, ^IRX, futuros contínuos Yahoo — cuidado com saltos na rolagem)
- `bis_juros_politica.parquet` (29 países), `cot.parquet` (CFTC 2010+), `fred_diario.parquet`
`quant/dados/` (= `base.DQ`):
- `snd_negocios.parquet` — negócios de debêntures (debentures.com.br) 2019+: date, emissor, codigo, isin, qtd, negocios, pu_min/med/max, pct_curva (PU em % da curva/par)
- `snd_cadastro.parquet` — cadastro debêntures: codigo, empresa, cnpj, venc, indice (DI/IPCA/PRE), pct, juros (spread/taxa), periodicidade, incentivada
- `balcao.parquet` — TODOS os negócios de balcão B3 2023-03+ (14 mi linhas): date, tipo (DEB/CRA/CRI/CDB/LF...), emissor, codigo, isin, qtd, pu, vol, taxa, origem
- `futuros.parquet` — ajustes B3 2019+ só DI1, DDI, FRC, DOL, DAP, WDO (ticker, AdjstdQt, AdjstdQtTax=taxa, OpnIntrst, volume)
- `tesouro_direto.csv` — preços/taxas Tesouro Direto (LTN, NTN-F, NTN-B, LFT) históricos (sep=';', decimal=',')
- `focus_ipca*.parquet`, `analistas.parquet` (Focus top5), `noticias_cvm.parquet` (contagem de fatos relevantes por CNPJ/dia, sem texto), `noticias_gdelt.parquet`
- `eurobonds_cadastro/precos.parquet`, `embi.parquet`, `mercado_global.parquet`, `eq_us.parquet`, `eq_br.parquet`, `opcoes_b3.parquet`, `sgs_*.parquet`
- Outros scripts antigos úteis para reaproveitar lógica: `quant/*.py` (dados.py, dados_extra.py, pesquisa_credito.py, pesquisa_juros.py), `itau/negocios_b3.py`

Fontes públicas que funcionam desta rede: dados.cvm.gov.br (IPE = fatos relevantes/comunicados com assunto e data de entrega; VLMO = negociação de insiders; FII informe mensal; DFP/ITR com datas), api.bcb.gov.br (SGS, Focus), B3 arquivos públicos (COTAHIST, ajustes), sec.gov (EDGAR índices e Form 4 data sets — mande User-Agent com nome+email genérico de pesquisa, NUNCA o e-mail do usuário), stats.bis.org, fred, yahoo (yfinance), CFTC. Polymarket/Kalshi BLOQUEADOS. Não use credenciais de ninguém, não contorne paywall/token.

## Convenções obrigatórias (o motor depende disso)
```python
from base import CDI, CDI_AA, DIAS, DIAS_US, PTAX, R_IBOV, TB_US, brl, carteira, vol_alvo, mensal, semanal, limpa, limpa_fx, D, DQ
from motor import Fundo, roda
from rodar import BENCH        # chaves: "CDI", "Ibovespa", "ACWI (R$ c/ hedge)", "S&P 500 (R$ c/ hedge)"
```
- Cada estratégia é `func(**params, custo_mult=1, lag=0) -> pd.Series` indexada em `DIAS` (dias úteis BR) com o EXCESSO diário sobre o CDI, já líquido de custos. O fundo = CDI + excesso.
- Decisão com informação disponível no fechamento de t (ou data de publicação do evento!), execução no fechamento de t+1+lag. `carteira(W, R, custo, lag, aluguel)` já faz o deslocamento: W = pesos-alvo decididos em t.
- Posição comprada financiada: retorno de ativo em R$ deve ser (r_ativo − CDI) se o caixa saiu do CDI. Ativo em USD com hedge: use `brl(excesso_em_usd_sobre_Tbill)`. Venda a descoberto: retorno −r, recebe CDI do caixa, paga aluguel (~0,5–1% a.a. blue chips; 3–10% small caps).
- Custos realistas por perna: ações B3 líquidas 5–10 bps + emolumentos; small caps 20–50 bps; opções = spread bid/ask real (use melhor oferta) + 0,1% do prêmio; futuros B3 ~1 bp; debêntures: 20–50 bps de spread no PU (balcão); FX G10 2 bps, EM 10–30 bps, fronteira 50–150 bps; ETFs EUA 3 bps; cripto 10–20 bps. `custo_mult` multiplica TODOS os custos.
- Benchmark: CDI para tudo que é absoluto/long-short/arbitragem; Ibovespa só para fundo comprado em ações BR; S&P/ACWI hedge para comprado em ações globais.
- `Fundo(nome, categoria, benchmark, tese, estrutura, func, grade, inicio=..., corte=...)` — sem taxa de gestão/performance (fundo próprio; motor já zera). Grade de 4 a 12 combinações, parâmetros com sentido econômico (não otimize 10 decimais). `corte` = início do fora-da-amostra: 2021-01-01 quando os dados começam ≤2012; 2023-01-01 quando começam em 2019; 2024-07-01 se começam em 2023. Pelo menos ~3 anos IS.
- `roda(f, CDI, BENCH[f.benchmark], log)` devolve dict com liquido, oos, rob etc. Antes de `pickle.dump`, faça `r["fundo"].func = None`.

## Regras anti-autoengano (de quem já se queimou)
1. Sharpe > 1,5 em estratégia única = BUG até prova em contrário. Procure: look-ahead (data do evento vs data de publicação), preço de fechamento não negociável, sobrevivência, provento não ajustado (dividendo parece queda!), saltos de rolagem, divisão por preço velho (stale), posição não marcada a mercado.
2. COTAHIST não é ajustado: ao calcular retorno de ação, zere/ajuste dias com |r|>25% sem notícia OU use fator de ajuste; desdobramentos e grupamentos aparecem como saltos. Dividendos grandes (PETR, VALE, BBAS) também — se a estratégia é vendida, o dividendo é CUSTO para você.
3. Preços de balcão/debêntures são esparsos: marque pelo último negócio e NÃO use preço que só existe porque houve negócio depois (sem olhar o futuro).
4. Use t+1 de execução sempre; teste também lag=1 (o motor faz).
5. Se precisar de "lista de eventos" (OPAs, fusões, recompras), a data relevante é a da DIVULGAÇÃO (data de entrega/arquivamento), não a do evento.

## O que entregar por frente
1. Módulo `ideias_<frente>.py` com as funções, uma lista `FUNDOS = [Fundo(...), ...]` (5–9 fundos) e um `if __name__ == "__main__":` que roda todos com `roda`, imprime uma linha por fundo e salva `resultado/ideias_<frente>.pkl`.
2. Para cada fundo, no resultado salvo, inclua também (chave extra no dict) `"contrib"`: DataFrame diário da contribuição de cada ativo/negócio ao excesso, e `"trades"`: DataFrame de negócios/posições (ativo, entrada, saída, dias, retorno, contribuição) — para depois explicarmos QUAIS negócios geraram o resultado.
3. `pesquisa/<frente>.md` — caderno de pesquisa: para cada hipótese: tese de mesa, como foi implementada, dados usados, resultado IS/OOS, os 10 melhores e 10 piores negócios, O QUE DEU CERTO E POR QUÊ (concreto: "a OPA da empresa X pagou 18% em 40 dias"), o que deu errado, bugs encontrados, e o que tentar em seguida. Escreva para que outro gestor possa reler daqui a um ano.
4. Resposta final curta (≤ 300 palavras): tabela com fundo, OOS a.a. vs bench, IR OOS, P(bater), PBO, e as 2–3 ideias mais promissoras com a razão concreta.

---
# FASE 2 (internacionalização) — leia também isto

Bugs já corrigidos na base (não reintroduza): `limpa` agora mantém NaN (antes ativo não listado rendia −CDI); `limpa_fx` não zera mais
movimentos > 50% (desvalorizações reais) e pega erro de 100x em log; carry: teto por ativo aplicado DEPOIS do vol-alvo; `futuros.parquet`
deduplicado (tinha cada linha 3x). Bugs que as frentes acharam e você deve evitar no seu código:
- `b3_vista.parquet` omite papéis em RJ (CODBDI 05–09) e TODOS os BDRs após out/2022 → para ações BR use `dados/b3_acoes_cotahist.parquet`
  (2014+, com RJ) e o painel ajustado `ideias_eventos_br.painel()`; BDRs em `dados/arb_bdr_vista.parquet`.
- Raiz de opção B3 mistura classes (VALE5/BBDC3/PETR3) — filtre pela série coerente com o ativo.
- `limpa` aplicado perna a perna cria P&L falso em pares — limpe o PAR.
- Peso fixo diário com preços ruidosos/esparsos (debêntures, ETFs ilíquidos) cria ganho falso de rebalanceamento → use compra-e-segura.
- Yahoo: alvos de M&A/empresas quebradas somem (viés de sobrevivência); abertura japonesa pré-2010 = fechamento anterior; futuros
  contínuos têm saltos na rolagem; dados de ETFs extintos não existem.
- Preços não simultâneos (termo vs à vista; ADR vs local) geram "arbitragem" falsa.

REGIME DE MERCADO: o executor final aplica a TODOS os fundos uma dimensão extra `regime` (ver `regimes.py`: risco_global, vix_contango,
sp_tendencia, ibov_tendencia, credito_ok, hmm_sp, hmm_ibov, selic_corte, brl_calmo, dd_stop, inv_risco_global) — NÃO coloque esses regimes
genéricos na sua grade. Se a sua estratégia tem um regime ESPECÍFICO com sentido econômico (ex.: carry só com curva de vol em contango;
merger arb só com spread de crédito calmo; commodities só em backwardation), inclua-o como parâmetro próprio.

Pegue as estratégias da rodada (cadernos em `pesquisa/*.md`, código em `ideias_*.py`, `fundos_br.py`, `fundos_global.py`) e REPLIQUE nos
EUA, Europa e Ásia (Japão, Coreia, Taiwan, Hong Kong/China, Índia, Austrália) e outros emergentes, com a lógica de mesa adaptada a cada mercado.
Onde não há dado gratuito, documente no caderno e siga. Cada fundo novo: nome com prefixo da frente (ex. "I1-03 PEAD EUA").
Entregue no mesmo formato: `ideias_<frente>.py` com FUNDOS, `resultado/ideias_<frente>.pkl` (com contrib e trades), `pesquisa/<frente>.md`.
