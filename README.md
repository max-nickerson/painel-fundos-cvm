---
title: Painel de fundos
emoji: 📊
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
short_description: Fundos brasileiros com dados abertos CVM, ANBIMA e BCB
---

# Painel de fundos (dados abertos CVM + ANBIMA + Tesouro + Banco Central)

Painel para gestor comparar **nossos fundos** com os **peers**, só com dados públicos e gratuitos.
Os fundos ficam em duas listas no topo de `lookthrough_cvm.py` (ou de `painel.py`): `NOSSOS_FUNDOS` e `PEERS` (`nome: CNPJ`).

## Três abas
| Aba | O que mostra (por fundo, buscando pelo nome digitado) |
|---|---|
| **Carteira** | Tabela por categoria (% PL, financeiro R$ mm, spread CDI e duration ponderados, total). Evolução do % PL e do spread por categoria. Ativos (código - vencimento, categoria, grupo econômico, % PL, spread, duration, PU, fonte) com filtro de categorias, quantidade (5/10/15/20/30/todos) e busca por ativo, emissor, grupo ou código; maiores grupos econômicos com o mesmo filtro. |
| **Retorno** | Período livre. Retorno e %CDI por categoria; melhores e piores ativos por contribuição (com % PL médio), com filtro de categorias, quantidade e busca. |
| **Consolidado** | Escolha os fundos (digitando, ou Todos / Nossos / Peers) e o período: só fundos ativos desde o início do período. Retorno acumulado (nossos em laranja, peers em cinza, CDI tracejado), risco x retorno e ranking. |

Categorias: **Caixa** (disponibilidades, compromissadas, LFT, provisões, caixa em dólar), **LF, LFSN, LFSC, DEB, DEBIN, Bonds** (dívida em dólar), **CRA, CRI, NC, FIDC, FIAGRO**; o que não se encaixa fica com o nome da CVM (Títulos Públicos, CDB, FII...). DEBIN = debênture incentivada (Lei 12.431, cadastro do SND). LFSC = LF perpétua; LFSN = LF com prazo > 6 anos (a CVM não informa a subordinação).

Um fundo que esteja nas duas listas (NOSSOS_FUNDOS e PEERS) entra uma vez só, como nosso. Funciona com pandas 2 e 3 e com FastAPI/Starlette novos.

## Um arquivo só (copiar e colar)
1. Instale o Python 3.11+ (python.org; no Windows marque *Add python.exe to PATH*).
2. `pip install fastapi uvicorn pandas numpy requests pyarrow openpyxl`
3. Salve [`painel.py`](painel.py) numa pasta e rode `python painel.py`. Ele baixa e processa todos os fundos e só então abre o painel no navegador.

Os dados ficam em **`dados_painel/`, na mesma pasta do `painel.py`**. A 1ª vez baixa ~2-3 GB da CVM (evite uma pasta sincronizada pelo OneDrive). Depois só baixa o que mudou e o painel do dia abre em segundos. `python painel.py excel` gera o Excel.

## Diagnóstico (arquivo separado)
Salve [`diagnostico.py`](diagnostico.py) na mesma pasta do `painel.py` e, depois de abrir o painel no dia, rode `python diagnostico.py`.
Ele não muda nada: lê o painel já processado e gera `diagnostico.xlsx` (resumo, alertas, categorias fora da casa, modelo x ANBIMA). Confere: % do PL soma 100% em todo mês; buracos de spread/duration; parte estimada; valores fora do plausível; categorias somam o retorno real da cota; resíduo e hedge; o modelo de spread pelo preço contra a ANBIMA; cotas com saltos (amortização/distribuição), em que o % do CDI não é comparável.

## Versão em pastas
```bash
pip install -r requirements.txt
uvicorn server:app --port 7860
```

## Método
- **Carteira:** look-through da CDA da CVM (abre cotas de fundos até o ativo final). Os fundos têm até 3 meses para publicar a carteira aberta, então a CVM republica os arquivos mensais; o painel confere uma vez por dia se mudaram e rebaixa. Meses com muita parte confidencial são marcados "(confid.)".
- **Spread CDI e duration (100% dos ativos de crédito; cada ativo mostra a fonte):**
  1. ANBIMA (taxa indicativa do dia mais próximo do fim do mês);
  2. debêntures fora dela: taxa de emissão e fluxo (juros/amortização) do **SND** + preço que o fundo informou à CVM ÷ PU par do SND → taxa de mercado (testado contra a ANBIMA: erro mediano 0,01 pp em DI+ e 0,09 pp em IPCA+);
  3. taxa contratada informada à CVM (LF, CDB, CRA, NC...);
  4. FIDC: série que o fundo tem (achada pelo valor da cota) no informe mensal de FIDC da CVM — mediana de 6 meses da rentabilidade acima do CDI; duration = prazo médio dos recebíveis;
  5. demais (CRI sem taxa, bonds, offshore): implícito pela variação do preço (bonds: em US$, contra o Treasury);
  6. o que sobrar: média da categoria no fundo (marcado "estimado").
  IPCA+ e prefixados viram spread contra a curva do Tesouro no mesmo prazo. Ações, FII, FIP, ETF e FIAGRO: não se aplica.
- **Retorno por categoria:** cada ativo rende CDI + seu spread, ou a variação real de preço quando ela é crível. Futuros (DI1, DAP, DOL/WDO) têm o P&L estimado e somado aos ativos que protegem (DAP → IPCA+, DI1 → prefixados, dólar → exterior); não existe categoria "derivativos". A diferença para o retorno real da cota é distribuída pelo peso, então as categorias somam o retorno do fundo.
- Grupo econômico: mapa por nome do emissor (`GRUPOS`), fácil de ampliar.

## Publicar no Hugging Face Spaces
Secrets `HF_USER` e `HF_TOKEN` neste repositório e a Action **Deploy no Hugging Face Space** sobe tudo (todo push no `main` atualiza).
