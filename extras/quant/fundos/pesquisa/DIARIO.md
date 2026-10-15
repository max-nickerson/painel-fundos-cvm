# Diário mestre — fundos simulados (out/2026)

Releia antes de começar qualquer nova rodada. Detalhes por frente em `pesquisa/*.md`; auditorias em `pesquisa/auditoria_*.md`.

## Protocolo
- Fundo próprio: sem taxa de gestão/performance; custos de negociação, aluguel e despesas (0,15% a.a.) mantidos.
- Decisão em t, execução no fechamento de t+1; parâmetros e REGIME escolhidos só no IS; OOS intocado (2021+, ou 2023/2024 para dados curtos).
- Regime: só regimes com sentido econômico para o ativo (a auditoria mostrou que "ciclo da Selic" escolhido para mineradoras/EUA fabricava resultado).
- Robustez: bootstrap estacionário, PBO (CSCV), Sharpe deflacionado, % de variantes, custo x2, execução +1 dia, alfa após beta de Ibovespa e S&P.
- 109 fundos testados (rodada 1 + 11 frentes), 44 bateram o benchmark OOS antes da auditoria; 5 sobreviveram à auditoria.

## Top 5 (pós-auditoria) — `top5_final.py`, figuras em `resultado/final/top5/`
1. Variância do S&P vendida com beta vendido (strike VIX−1, teto de vega 0,4x PL, regime risco_global) — OOS +7,6 pp a.a. vs CDI, IR 1,42, PBO 5%. Morre se o dealer cobrar VIX−2.
2. Carry de moedas G10+EM (teto 25%/moeda depois do vol-alvo, carry BRL pelo cupom cambial, custos por moeda, stop executado em t+1) — +7,0 pp, IR 1,02. IS 2010–2020 ≈ 0: é prêmio do regime de juros altos pós-2021.
3. Mineradoras vs metal (pares GDXJ×GDX, FCX×cobre etc., sem reentrada no mesmo dia) — +11,7 pp, IR 1,01, PBO 26%; sensível a atraso (t+3 → +7,9).
4. Rebalanceamento do Ibovespa (comprar prováveis entrantes 10 dias antes) — +1,8 pp, IR 0,97, vol 1,7% (alavancável); sem os 5 maiores eventos +0,7 pp. Morre com 2+ dias de atraso.
5. Eurobonds BR high yield com hedge cambial (compra-e-segura, preço vivo, bid/ask 0,5–2 pts, sem AG) — +3,6 pp, IR 0,44; um único ciclo (2023–24).
Carteira dos 5 (pesos pelo inverso da vol do IS de cada um, vol-alvo 6%): OOS (2024+) 22,2% a.a. vs CDI 13,1%, Sharpe 1,26, pior queda −5,3%, correlações ~0.

## Bugs encontrados (não repetir)
- `limpa` zerava NaN (ativo não listado rendia −CDI); `limpa_fx` apagava desvalorizações reais > 50% e não pegava erro de 100x do Yahoo que dura 2–8 dias (COP jun/2015) → `_limpa_niveis` em base.FXY.
- Carry: teto por moeda aplicado antes do vol-alvo (TRY chegava a 75% do PL).
- `dd_stop` decidia e operava no mesmo fechamento (escapava de fev/2018) → shift(1).
- HMM: predict_proba suaviza para trás (look-ahead) → filtro forward.
- `b3_vista` omite papéis em RJ e todos os BDRs pós-out/2022 → `b3_acoes_cotahist.parquet`.
- `futuros.parquet` com linhas triplicadas.
- Termo/box: taxa "travada" vinda de preços não simultâneos e posição sem marcação a mercado (IR 9–44 falso).
- Máquina de reversão reentrava no mesmo dia após saída por prazo/stop.
- Rebalancear a peso fixo com preços ruidosos (debêntures, penny stocks) cria ganho falso → compra-e-segura.
- Eurobonds: vender quando o preço "some" e recomprar; cupom acumulando em bond em default.
- %PU da curva do SND erra em amortização; base antiga cortava PU < 30% (apagava os distressed).
- Yahoo: sobrevivência (spin-offs, alvos de M&A, excluídos de índice que quebraram, membros atuais de índices asiáticos), tickers reaproveitados por outra empresa, abertura japonesa pré-2010.
- Regime genérico sem relação com o ativo escolhido no IS = overfitting; custo de liga/desliga de 10 bps irreal para crédito ilíquido (2–5%).

## O que funcionou em parte (vale pesquisar mais)
- OPA/troca de controle BR (88% de acerto, mas só ~6% do PL) — livro complementar.
- Follow-on vendido BR (+2 pp após aluguel real 20% a.a.) — depende de aluguel.
- Spin-offs EUA (+4,3 pp com parâmetros fixos; zera no protocolo completo após viés de sobrevivência).
- Crédito antecipa ação — só o lado vendido (Ambipar, Alliança, Viveo).
- PETR4 vs Brent em pânico; crack/crush/gás de inverno; inflação implícita EUA "seguindo o gap"; eleições EM após pânico; reversão de large caps no Japão (IS≈0).
- Base cripto: código certo, mas risco de contraparte + margem realista zeram o alfa.

## O que não funciona (não insistir)
Box/conversão (≈CDI), ADR/BDR/units/ETF×NAV com t+1, dividendos/JCP, venda de put sem hedge de beta (é beta), CBOE put-write com beta vendido, carry agro B3 vendido, contrarian CFTC, prever juros (Brasil e EUA), ML semanal em ações, collar, macro alternativo, recompra, lock-up, insiders (sobrevivência), merger arb via Yahoo, PEAD Ásia/EUA, crise contrarian BR.

## Sem dado gratuito
Prediction markets (bloqueados), NDF/forwards EM, OAS de HY pré-2023, TRACE, futuros Bund/Gilt/JGB, bonds soberanos em crise, filings Europa/Ásia, fundamento histórico (P/L, CAPE).
