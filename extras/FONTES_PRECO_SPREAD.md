# Fontes grátis de preço e spread — ativos IAM (pesquisa 2026-10-07)

Tudo testado com requisições reais, sem login/token/captcha. São endpoints públicos de sites (não APIs oficiais): podem mudar; consultar com moderação e guardar cache.

## Quadro por tipo de ativo

| Ativo | Melhor fonte grátis | O que dá | Atraso |
|---|---|---|---|
| Debênture / CRI / CRA | **B3 BDI "Trade"** | cada negócio: PU, **taxa** (spread p/ DI+, taxa real p/ IPCA+), ISIN | ~15 min |
| | ANBIMA `dbAAMMDD.txt` (~122 da lista) + **IDA** (taxa por papel, 458 IDA-DI) | taxa indicativa | fim do dia |
| | Agentes fiduciários (Oliveira Trust, Vórtx, Pentágono) | PU da curva diário | diário |
| LF / LFSN / LFSC | **B3 BDI "Trade"** (só PU) + **B3 arquivo ISIN** (data de emissão) → calcular spread | PU real → spread implícito (validado c/ CVM: ±0,1–0,2 pp) | ~15 min |
| | Oliveira Trust (~41 LFs) | PU da curva | diário |
| NC | B3 BDI (PU) + trustees (Oliveira/Vórtx) | PU, sem taxa pronta | diário |
| CDB | — só CVM CDA (mensal) e ofertas (Investidor10/Yubb) | sem preço secundário grátis | — |
| Cota FIDC/Fiagro | Oliveira Trust (525 séries), B3 BDI "CFF" quando negocia, CVM informe mensal | cota/PU | diário / esporádico |
| Eurobonds | **TradingView scanner** (BONDSCOM: 13/17 c/ bid/ask/yield/duration; bolsas alemãs cobrem 17/17), FINRA TRACE (último negócio), Frankfurt | preço, yield | ao vivo–15 min |
| T-bills | TradingView + treasury.gov bill rates | yield | ao vivo / fim do dia |
| LFT / títulos públicos | ANBIMA `msAAMMDD.txt`, Tesouro Direto JSON | taxa, PU | intradia / fim do dia |

## Curvas e sinais
- **B3 cotacao** `cotacao.b3.com.br/mds/api/v1/DerivativeQuotation/{DI1|DAP|FRC|DDI|DOL}` — intradia (~15 min); `DailyFluctuationHistory/<contrato>` minuto a minuto.
- **B3 taxas referenciais** (fechamento: cupom limpo DOC, PRE, DIC): `sistemaswebb3-derivativos.b3.com.br/referenceRatesProxy/Search/GetList/<base64 json>`.
- **ANBIMA**: ETTJ `est-termo/CZ-down.asp`; curvas de crédito por rating `curvas-debentures/CD-down.asp` (AAA/AA/A, 5 dias); IDA `ida/IDA_down.asp`.
- **UST**: TradingView/CNBC ao vivo; treasury.gov CSV e FRED no fechamento.
- **Ações dos emissores** (alerta de crédito): TradingView `brazil/scan`, Yahoo `v8/finance/spark`.
- **CDS Brasil 5a**: só fechamento (Investing, scraping).

## URLs principais
- BDI negócios: `POST https://arquivos.b3.com.br/bdi/table/Trade/{AAAA-MM-DD}/{AAAA-MM-DD}/{pag}/{take≤1000}?filter={base64(codigo)}` body `{}`; tabelas `ConsolidatedRecords` (min/méd/máx, EXTRA/INTRAGRUPO), `InstrumentRegistration` (ISIN↔código, indexador, spread, vencimento). Filtro só por código B3 (não ISIN).
- B3 ISIN (data de emissão): `GET https://sistemaswebb3-listados.b3.com.br/isinProxy/IsinCall/GetDetail/<base64('{"isin":"BR..."}')>`; arquivo completo via `GetTextDownload/` → `GetFileDownload/<base64(id)>`.
- Oliveira Trust PU: `https://services-ft.oliveiratrust.com.br/app/v1/titulos/historico_pu?page=1&limit=50&data=AAAA-MM-DD&busca=<código CETIP>`.
- Vórtx PU do dia (xlsx): `https://apis.vortx.com.br/vxsite/api/operacoes/exportar-pu`.
- Pentágono PU: `https://www.pentagonotrustee.com.br/Site/DetalhesEmissor?aba=tab-4&ativo=<CETIP>&dataInicial=dd%2Fmm%2Faaaa&dataFinal=dd%2Fmm%2Faaaa&tipo=3`.
- TradingView bonds: `POST https://scanner.tradingview.com/bond/scan` `{"symbols":{"tickers":["BONDSCOM:<ISIN>"]},"columns":["close","bid","ask","yield_to_maturity","modified_duration"]}` (headers Origin/Referer tradingview.com).
- FINRA TRACE: cookie XSRF de `services-dynarep.ddwa.finra.org` e POST em `.../FixedIncomeMarket/name/CorporateAndAgencySecurities` (filtro CUSIP).

## Spread de LF a partir do preço B3
PU par = VN × Π(1+CDI diário) desde a emissão × (1+spread)^(du/252); spread de mercado = (1+spread)/(PU negócio/PU par)^(252/du restantes) − 1.
Ex. 05/10/2026: Nu DI+0,65 → mercado DI+0,30; Agibank DI+2,05 → DI+0,40; Banrisul LFSN DI+1,65 → DI+1,44; Toyota DI+0,32 → DI+0,24. Descartar negócios com PU/par = 1,0000 (registro na curva do emissor). %CDI precisa da curva DI1 futura.

## Correções na planilha (ISINs de bonds)
USL01343AB52 / AE91 = **AEGEA** (não Amaggi); **Amaggi** = USL0183BAA90; US105756… = **soberano Brasil**; USL40756AG06 = FS; USL70906… = Nova Securitisation (Sabesp); USL7151AAC01 = Oceânica; USL7915TAE21 = Rede D'Or; USL9R621AA97 = 3R; USN15516… = Braskem.

## Não existe grátis
Curva de LF da ANBIMA automatizada (captcha; só XLS manual, 5 dias); preço secundário de CDB; taxa pronta de NC; LF/CDB intradia; CDS intradia; cota diária de FIDCs cujo administrador não publica (ex.: Creditas Auto X / Limine); debêntures não têm cotação na tela da B3.
