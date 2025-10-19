# app.py — QuantBuddy (MVP)
# Webová appka pro základní kvantitativní analýzy s česky psanou interpretací.
# Spuštění: 1) pip install -r requirements.txt  2) streamlit run app.py

import io
import tempfile
import textwrap
from datetime import datetime

import numpy as np
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
from scipy import stats
import statsmodels.api as sm
import statsmodels.formula.api as smf
from docx import Document
from docx.shared import Inches

# ---------------------------
# Nastavení stránky (musí být první Streamlit příkaz)
# ---------------------------

st.set_page_config(
    page_title="QuantBuddy — chytrý parťák pro analýzu dat",
    page_icon="📊",
    layout="wide"
)

st.markdown("""
# QuantBuddy 📊  
*Tvůj chytrý parťák pro kvantitativní výzkum.*  
Nahraj data → vyber analýzu → získej výsledky i interpretaci v češtině.
""")

# ---------------------------
# Pomocné funkce
# ---------------------------

def detect_var_types(df: pd.DataFrame, cat_unique_threshold: int = 10):
    """Hrubá heuristika: text = kategorická; číselná s <=10 unikáty = kategorická; jinak numerická."""
    types = {}
    for col in df.columns:
        s = df[col]
        if pd.api.types.is_numeric_dtype(s):
            nunq = s.dropna().nunique()
            types[col] = "kategorická" if nunq <= cat_unique_threshold else "numerická"
        else:
            types[col] = "kategorická"
    return types

def clean_series_pair(x: pd.Series, y: pd.Series):
    df = pd.concat([x, y], axis=1).dropna()
    return df.iloc[:,0], df.iloc[:,1]

def cohen_d_from_groups(g1, g2):
    n1, n2 = len(g1), len(g2)
    s1, s2 = np.var(g1, ddof=1), np.var(g2, ddof=1)
    sp = np.sqrt(((n1-1)*s1 + (n2-1)*s2) / (n1+n2-2))
    if sp == 0:
        return np.nan
    return (np.mean(g1) - np.mean(g2)) / sp

def cramers_v(chi2, n, r, c):
    return np.sqrt(chi2 / (n * (min(r-1, c-1))))

def eta_squared_anova(anova_table):
    try:
        ss_effect = anova_table.loc['C(group)', 'sum_sq']
        ss_resid = anova_table.loc['Residual', 'sum_sq']
        return ss_effect / (ss_effect + ss_resid)
    except Exception:
        return np.nan

def wrap(text, width=90):
    return "\n".join(textwrap.wrap(text, width=width))

# ---------------------------
# Generátor interpretací (CZ)
# ---------------------------

def interpret_correlation(stat, p, n, method, varx, vary):
    sig = p < 0.05
    strength = "slabý"
    absr = abs(stat)
    if absr >= 0.7:
        strength = "silný"
    elif absr >= 0.4:
        strength = "středně silný"
    elif absr >= 0.2:
        strength = "slabý"
    trend = "pozitivní" if stat > 0 else ("negativní" if stat < 0 else "nulový")

    lines = [
        f"Byla provedena {method} korelace mezi „{varx}“ a „{vary}“ (n = {n}).",
        f"Výsledek ukazuje {strength} {trend} vztah (r = {stat:.2f}, p = {p:.3f})."
    ]
    if sig:
        lines.append("Vztah je statisticky významný na hladině α = 0,05.")
    else:
        lines.append("Vztah není statisticky významný na hladině α = 0,05.")
    lines.append("Pozn.: Korelace neimplikuje kauzalitu.")
    return " ".join(lines)

def interpret_ttest(t, p, d, n1, n2, group, outcome):
    sig = p < 0.05
    eff = ""
    if not np.isnan(d):
        mag = "malý"
        if abs(d) >= 0.8:
            mag = "velký"
        elif abs(d) >= 0.5:
            mag = "střední"
        eff = f" (Cohenovo d = {d:.2f}, {mag} efekt)."

    lines = [
        f"Byl proveden dvouvýběrový t-test pro nezávislé výběry pro porovnání průměrů proměnné „{outcome}“ mezi dvěma úrovněmi „{group}“ (n₁ = {n1}, n₂ = {n2}).",
        f"Výsledek: t = {t:.2f}, p = {p:.3f}{eff}"
    ]
    if sig:
        lines.append("Rozdíl je statisticky významný na hladině α = 0,05.")
    else:
        lines.append("Rozdíl není statisticky významný na hladině α = 0,05.")
    return " ".join(lines)

def interpret_chi2(chi2, p, dof, v, n, var1, var2):
    sig = p < 0.05
    mag = ""
    if not np.isnan(v):
        size = "slabé"
        if v >= 0.5:
            size = "silné"
        elif v >= 0.3:
            size = "střední"
        mag = f" Velikost asociace dle Cramerova V = {v:.2f} ({size})."
    lines = [
        f"Byl proveden chí-kvadrát test nezávislosti pro „{var1}“ × „{var2}“ (n = {n}, df = {dof}).",
        f"Výsledek: χ² = {chi2:.2f}, p = {p:.3f}.{mag}"
    ]
    if sig:
        lines.append("Mezi kategoriemi existuje statisticky významná asociace.")
    else:
        lines.append("Statisticky významná asociace mezi proměnnými nebyla zjištěna.")
    return " ".join(lines)

def interpret_anova(F, p, eta2, k, n, group, outcome):
    sig = p < 0.05
    mag = ""
    if not np.isnan(eta2):
        size = "malý"
        if eta2 >= 0.14:
            size = "velký"
        elif eta2 >= 0.06:
            size = "střední"
        mag = f" (η² = {eta2:.2f}, {size} efekt)."
    lines = [
        f"Jednofaktorová ANOVA pro „{outcome}“ napříč {k} skupinami proměnné „{group}“ (n = {n}).",
        f"Výsledek: F = {F:.2f}, p = {p:.3f}{mag}"
    ]
    if sig:
        lines.append("Rozdíly mezi alespoň dvěma skupinami jsou statisticky významné.")
    else:
        lines.append("Statisticky významné rozdíly mezi skupinami nebyly zjištěny.")
    return " ".join(lines)

# ---------------------------
# Export do DOCX
# ---------------------------

def build_docx(report_title, meta, results_text, fig_bytes=None):
    doc = Document()
    doc.add_heading(report_title, level=1)
    doc.add_paragraph(f"Datum: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    doc.add_heading("Popis dat", level=2)
    doc.add_paragraph(meta)

    doc.add_heading("Výsledky a interpretace", level=2)
    for para in textwrap.wrap(results_text, width=100):
        doc.add_paragraph(para)

    if fig_bytes is not None:
        doc.add_heading("Vizualizace", level=2)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(fig_bytes.getvalue())
            tmp.flush()
            doc.add_picture(tmp.name, width=Inches(5.5))
    bio = io.BytesIO()
    doc.save(bio)
    bio.seek(0)
    return bio

# ---------------------------
# UI
# ---------------------------



with st.sidebar:
    st.header("1) Nahraj data")
    file = st.file_uploader("CSV nebo Excel (.xlsx)", type=["csv", "xlsx"])
    if file and file.name.lower().endswith(".xlsx"):
        try:
            xls = pd.ExcelFile(file)
            sheet_name = st.selectbox("Vyber list", xls.sheet_names)
            df = pd.read_excel(file, sheet_name=sheet_name)
        except Exception as e:
            st.error(f"Chyba při načítání Excelu: {e}")
            df = None
    elif file and file.name.lower().endswith(".csv"):
        try:
            df = pd.read_csv(file)
        except Exception:
            file.seek(0)
            df = pd.read_csv(file, sep=";")
    else:
        df = None

    st.header("2) Zvol analýzu")
    analysis = st.selectbox(
        "Typ analýzy",
        [
            "Korelace dvou proměnných",
            "Porovnání dvou skupin (t-test)",
            "Asociace dvou kategoriálních (χ²)",
            "Porovnání více skupin (ANOVA)",
        ],
    )

if df is None:
    st.info("Nahraj prosím datový soubor (CSV/XLSX).")
    st.stop()

st.success(f"Načteno: {df.shape[0]} řádků × {df.shape[1]} sloupců")
types = detect_var_types(df)

with st.expander("Náhled dat a typů proměnných", expanded=False):
    st.dataframe(df.head(10))
    typemap = pd.DataFrame({"proměnná": list(types.keys()), "typ": list(types.values())})
    st.dataframe(typemap)

# ---------------------------
# Analýzy
# ---------------------------

result_text = ""
fig_buf = None
meta_desc = f"Počet řádků: {df.shape[0]}, počet proměnných: {df.shape[1]}."

if analysis == "Korelace dvou proměnných":
    num_cols = [c for c,t in types.items() if t == "numerická"]
    if len(num_cols) < 2:
        st.error("Pro korelaci jsou potřeba alespoň 2 numerické proměnné.")
        st.stop()
    x = st.selectbox("Proměnná X", num_cols, index=0)
    y = st.selectbox("Proměnná Y", num_cols, index=min(1, len(num_cols)-1))
    method = st.radio("Metoda korelace", ["Pearson", "Spearman"], horizontal=True)

    if st.button("Spustit analýzu"):
        sx, sy = clean_series_pair(df[x], df[y])
        if len(sx) < 5:
            st.error("Příliš málo platných pozorování (min. 5).")
            st.stop()
        if method == "Pearson":
            r, p = stats.pearsonr(sx, sy)
        else:
            r, p = stats.spearmanr(sx, sy)
        result_text = interpret_correlation(r, p, len(sx), method.lower(), x, y)

        fig, ax = plt.subplots()
        ax.scatter(sx, sy)
        ax.set_xlabel(x)
        ax.set_ylabel(y)
        ax.set_title(f"Rozptylový graf: {x} × {y}")
        fig_buf = io.BytesIO()
        fig.savefig(fig_buf, format="png", bbox_inches="tight")
        st.pyplot(fig)

        st.subheader("Interpretace")
        st.write(wrap(result_text))

# (zbytek kódu pokračuje stejně jako předtím – t-test, χ², ANOVA, export do DOCX)
