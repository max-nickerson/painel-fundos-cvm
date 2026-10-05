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

# Painel de fundos (dados abertos CVM + ANBIMA + Banco Central)

Página web para analisar **qualquer fundo brasileiro** com dados públicos e gratuitos. Busque por nome ou CNPJ, escolha até 8 fundos e o período.

| Fonte | O que entra no painel |
|---|---|
| CVM – CDA (carteira mensal) | Look-through da carteira (abre cotas de fundos até o ativo final), alocação, emissores, compras e vendas do mês, derivativos, exposição externa |
| CVM – Informe diário | Cota, rentabilidade, %CDI, drawdown, volatilidade, PL, captação líquida, cotistas |
| CVM – Cadastro | Busca de fundos por nome ou CNPJ |
| ANBIMA – mercado secundário de debêntures | Taxa indicativa (spread DI+ / IPCA+), PU e duration das debêntures da carteira |
| Banco Central – SGS 12 | CDI diário |

Abas: Visão geral · Rentabilidade · PL & captação · Alocação · Crédito · Movimentações · Derivativos & moeda · Marcação (estimada) · Comparação · Dados.

## Jeito mais simples: um arquivo só (copiar e colar)
1. Instale o Python 3.11+ (python.org; no Windows marque *Add python.exe to PATH*).
2. `pip install fastapi uvicorn pandas numpy requests pyarrow openpyxl`
3. Copie o conteúdo de [`painel.py`](painel.py) para um arquivo `painel.py` e rode `python painel.py` (abre o navegador sozinho). `python painel.py excel` gera o Excel.

## Rodar no seu computador (versão em pastas)
```bash
pip install -r requirements.txt
uvicorn server:app --port 7860
```
Abra http://localhost:7860.

## Publicar de graça no Hugging Face Spaces
1. Crie uma conta em https://huggingface.co e um **New Space**: nome `painel-fundos`, SDK **Docker** (Blank), hardware **CPU basic (free)**.
2. Em *Settings → Access Tokens* do Hugging Face, crie um token com permissão **Write**.
3. Neste repositório do GitHub: *Settings → Secrets and variables → Actions* → crie os secrets `HF_USER` (seu usuário do Hugging Face) e `HF_TOKEN` (o token).
4. Aba *Actions* → **Deploy no Hugging Face Space** → *Run workflow*. A partir daí, todo push no `main` atualiza o Space sozinho.

O painel fica em `https://huggingface.co/spaces/<seu-usuario>/painel-fundos`. Space gratuito: 2 vCPU, 16 GB de RAM; dorme depois de um tempo sem uso (a primeira visita depois disso leva ~1 min para acordar).

## Também gera Excel
`python lookthrough_cvm.py` → `lookthrough_cvm.xlsx` (gráficos, evolução, rentabilidade, top 10 por categoria, uma aba por fundo) + CSV.

## Limites dos dados
- Carteiras são **mensais**; meses recentes podem ter ativos **confidenciais** (até 6 meses). Crédito, movimentações e marcação usam o último mês "aberto".
- Derivativos vêm pelo valor informado (em geral nocional): ficam fora da soma de 100%.
- Quando a carteira informada não fecha com o PL, a diferença aparece como "Ajuste carteira x PL".
- A ANBIMA gratuita guarda só ~15 dias úteis: o histórico de spread/duration cresce a partir do uso (no Space gratuito ele recomeça quando o Space reinicia).
- Não há preço **ao vivo** gratuito de debêntures/CRI/LF (mercado de balcão); a referência pública é a taxa indicativa ANBIMA de fim de dia.
- "Marcação (estimada)" mostra variação de preço das posições mantidas, não P&L contábil: cupons/amortizações aparecem como queda de preço.
