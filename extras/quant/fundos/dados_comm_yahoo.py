"""Yahoo extra para a frente de commodities -> dados/y_comm.parquet (preço ajustado; cache: não re-baixa se existir)."""
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
from dados_fundos import yahoo, D

TK = ["RB=F", "HO=F", "ZM=F", "ZL=F", "GF=F", "HE=F", "TIO=F", "PA=F", "PL=F", "ALI=F", "OJ=F", "CC=F",
      "GDX", "GDXJ", "SIL", "COPX", "XME", "PICK", "XOP", "OIH", "UGA", "USL", "UNL", "DBO", "FXA", "FXC", "SLX", "MOO", "COW", "TAGS", "CANE",
      "BHP", "RIO", "SCCO", "AEM", "PPC", "TSN", "ADM", "BG", "FCX", "NEM", "XOM", "CVX", "MOS", "NTR", "CF", "VALE", "PBR", "JBS", "MBRFY",
      "PETR4.SA", "PETR3.SA", "PRIO3.SA", "RECV3.SA", "RRRP3.SA", "BRAV3.SA", "JBSS3.SA", "MRFG3.SA", "BRFS3.SA", "MBRF3.SA", "BEEF3.SA", "SMTO3.SA",
      "RAIZ4.SA", "CSAN3.SA", "VALE3.SA", "CMIN3.SA", "CSNA3.SA", "GGBR4.SA", "SUZB3.SA", "KLBN11.SA", "SLCE3.SA", "AGRO3.SA", "TTEN3.SA",
      "UGPA3.SA", "VBBR3.SA", "BRAP4.SA", "JALL3.SA", "ENAT3.SA", "AURA33.SA", "CAML3.SA", "JBSS32.SA"]

if __name__ == "__main__":
    f = D / "y_comm.parquet"
    if not f.exists():
        with ThreadPoolExecutor(8) as ex:
            s = [x for x in ex.map(yahoo, TK) if x is not None]
        pd.concat(s, axis=1).to_parquet(f)
    d = pd.read_parquet(f)
    print(d.notna().sum().to_string(), d.index.min(), d.index.max())
