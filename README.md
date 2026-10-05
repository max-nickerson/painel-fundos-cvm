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
| **Carteira** | Tabela por categoria: % PL, financeiro (R$ mm), spread CDI e duration ponderados + total; derivativos à parte (sem % PL). Evolução do % PL e do spread por categoria. Top 10 ativos com grupo econômico, spread e duration. Maiores grupos econômicos. |
| **Retorno** | Período livre. Retorno e %CDI por categoria, 10 melhores e piores ativos, posição do fundo no risco x retorno de todos os fundos. |
| **Consolidado** | Escolha os fundos (digitando, ou Todos / Nossos / Peers) e o período: só fundos ativos desde o início do período. Retorno acumulado (nossos em laranja, peers em cinza, CDI tracejado) e ranking. |

## Um arquivo só (copiar e colar)
1. Instale o Python 3.11+ (python.org; no Windows marque *Add python.exe to PATH*).
2. `pip install fastapi uvicorn pandas numpy requests pyarrow openpyxl`
3. Salve [`painel.py`](painel.py) numa pasta e rode `python painel.py`. Ele baixa e processa todos os fundos e só então abre o painel no navegador.

Os dados ficam em **`dados_painel/`, na mesma pasta do `painel.py`**. A 1ª vez baixa ~2-3 GB da CVM (evite uma pasta sincronizada pelo OneDrive). Depois só baixa o que mudou e o painel do dia abre em segundos. `python painel.py excel` gera o Excel.

## Versão em pastas
```bash
pip install -r requirements.txt
uvicorn server:app --port 7860
```

## Método
- **Carteira:** look-through da CDA da CVM (abre cotas de fundos até o ativo final). Os fundos têm até 3 meses para publicar a carteira aberta, então a CVM republica os arquivos mensais; o painel confere uma vez por dia se mudaram e rebaixa. Meses com muita parte confidencial são marcados "(confid.)".
- **Spread CDI e duration:** debêntures pela taxa indicativa ANBIMA; IPCA+ e prefixados viram spread contra a curva do Tesouro (IPCA+ / Prefixado) no mesmo prazo; %CDI vira (x−100%)×CDI. Caixa e compromissadas valem 0.
- **Retorno por categoria:** cada ativo rende CDI + seu spread, ou a variação real de preço quando ela é crível. Futuros (DI1, DAP, DOL/WDO) têm o P&L estimado e somado aos ativos que protegem (DAP → IPCA+, DI1 → prefixados, dólar → exterior); não existe categoria "derivativos". A diferença para o retorno real da cota é distribuída pelo peso, então as categorias somam o retorno do fundo.
- Grupo econômico: mapa por nome do emissor (`GRUPOS`), fácil de ampliar.

## Publicar no Hugging Face Spaces
Secrets `HF_USER` e `HF_TOKEN` neste repositório e a Action **Deploy no Hugging Face Space** sobe tudo (todo push no `main` atualiza).
