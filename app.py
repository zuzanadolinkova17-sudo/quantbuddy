# app.py — QuantBuddy (MVP)
# Webová appka pro základní kvantitativní analýzy s česky psanou interpretací.
# Spuštění: 1) pip install -r requirements.txt  2) streamlit run app.py

import streamlit as st

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
    """Zarovná dvojici sérií na společné nenulové indexy bez NaN."""
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
    # jednoduché eta^2 = SSeffect / SStotal
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
    r = stat
    absr = abs(r)
    if absr >= 0.7:
        strength = "silný"
    elif absr >= 0.4:
        strength = "středně silný"
    elif absr >= 0.2:
        strength = "slabý"
    trend = "pozitivní" if r > 0 else ("negativní" if r < 0 else "nulový")

    lines = []
    lines.append(f"Byla provedena {method} korelace mezi „{varx}“ a „{vary}“ (n = {n}).")
    lines.append(f"Výsledek ukazuje {strength} {trend} vztah (r = {r:.2f}, p = {p:.3f}).")
    if sig:
        lines.append("Vztah je statisticky významný na hladině α = 0,05.")
        lines.append("To naznačuje, že vyšší hodnoty jedné proměnné jsou systematicky spojeny se změnou druhé proměnné.")
    else:
        lines.append("Vztah není statisticky významný na hladině α = 0,05.")
        lines.append("Nelze tedy spolehlivě tvrdit, že mezi proměnnými existuje lineární souvislost v populaci.")
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

    lines = []
    lines.append(f"Byl proveden dvouvýběrový t-test pro nezávislé výběry pro porovnání průměrů proměnné „{outcome}“ mezi dvěma úrovněmi „{group}“ (n₁ = {n1}, n₂ = {n2}).")
    lines.append(f"Výsledek: t = {t:.2f}, p = {p:.3f}{eff}")
    if sig:
        lines.append("Rozdíl je statisticky významný na hladině α = 0,05.")
        lines.append("To naznačuje, že průměrné hodnoty výstupové proměnné se mezi skupinami liší více, než by bylo očekáváno náhodou.")
    else:
        lines.append("Rozdíl není statisticky významný na hladině α = 0,05.")
        lines.append("Data neposkytují dostatek důkazů pro tvrzení o rozdílu průměrů v populaci.")
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
    lines = []
    lines.append(f"Byl proveden chí-kvadrát test nezávislosti pro „{var1}“ × „{var2}“ (n = {n}, df = {dof}).")
    lines.append(f"Výsledek: χ² = {chi2:.2f}, p = {p:.3f}.{mag}")
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
    lines = []
    lines.append(f"Jednofaktorová ANOVA pro „{outcome}“ napříč {k} skupinami proměnné „{group}“ (n = {n}).")
    lines.append(f"Výsledek: F = {F:.2f}, p = {p:.3f}{mag}")
    if sig:
        lines.append("Rozdíly mezi alespoň dvěma skupinami jsou statisticky významné.")
        lines.append("Doporučení: provést post-hoc testy (např. Tukey HSD) k identifikaci konkrétních rozdílů.")
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

st.set_page_config(page_title="QuantBuddy (MVP)", page_icon="📊", layout="centered")
st.title("📊 QuantBuddy — MVP")
st.write("Chytrý parťák pro základní kvantitativní analýzy a česky psanou interpretaci.")

with st.sidebar:
    st.header("1) Nahraj data")
    file = st.file_uploader("CSV nebo Excel (.xlsx)", type=["csv", "xlsx"])
    sheet_name = None
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
# VÝBĚR PROMĚNNÝCH A ANALÝZY
# ---------------------------

result_text = ""
fig_buf = None
meta_desc = f"Počet řádků: {df.shape[0]}, počet proměnných: {df.shape[1]}. " \
            f"Automatická detekce typů proměnných (heuristika)."

if analysis == "Korelace dvou proměnných":
    num_cols = [c for c,t in types.items() if t == "numerická"]
    if len(num_cols) < 2:
        st.error("Pro korelaci jsou potřeba alespoň 2 numerické proměnné.")
        st.stop()
    x = st.selectbox("Proměnná X (numerická)", num_cols, index=0)
    y = st.selectbox("Proměnná Y (numerická)", num_cols, index=min(1, len(num_cols)-1))
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

        # Graf
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

elif analysis == "Porovnání dvou skupin (t-test)":
    cat_cols = [c for c,t in types.items() if t == "kategorická" and df[c].dropna().nunique() == 2]
    num_cols = [c for c,t in types.items() if t == "numerická"]
    if not cat_cols or not num_cols:
        st.error("Potřebuji 1 binární kategoriální a 1 numerickou proměnnou.")
        st.stop()
    g = st.selectbox("Skupinová proměnná (2 úrovně)", cat_cols)
    y = st.selectbox("Výstupová proměnná (numerická)", num_cols)

    if st.button("Spustit analýzu"):
        tmp = df[[g, y]].dropna()
        groups = tmp[g].unique()
        if len(groups) != 2:
            st.error("Skupinová proměnná musí mít právě 2 úrovně.")
            st.stop()
        g1 = tmp[tmp[g] == groups[0]][y].astype(float)
        g2 = tmp[tmp[g] == groups[1]][y].astype(float)
        t, p = stats.ttest_ind(g1, g2, equal_var=False)  # Welchův t-test
        d = cohen_d_from_groups(g1.values, g2.values)
        result_text = interpret_ttest(t, p, d, len(g1), len(g2), g, y)

        # Graf (krabicový)
        fig, ax = plt.subplots()
        ax.boxplot([g1, g2], labels=[str(groups[0]), str(groups[1])])
        ax.set_title(f"{y} podle {g}")
        ax.set_ylabel(y)
        fig_buf = io.BytesIO()
        fig.savefig(fig_buf, format="png", bbox_inches="tight")
        st.pyplot(fig)

        st.subheader("Interpretace")
        st.write(wrap(result_text))

elif analysis == "Asociace dvou kategoriálních (χ²)":
    cat_cols = [c for c,t in types.items() if t == "kategorická"]
    if len(cat_cols) < 2:
        st.error("Potřebuji 2 kategoriální proměnné.")
        st.stop()
    a = st.selectbox("Proměnná 1 (kategorická)", cat_cols, index=0)
    b = st.selectbox("Proměnná 2 (kategorická)", cat_cols, index=min(1, len(cat_cols)-1))

    if st.button("Spustit analýzu"):
        tab = pd.crosstab(df[a], df[b], dropna=True)
        if tab.shape[0] < 2 or tab.shape[1] < 2:
            st.error("Každá proměnná musí mít alespoň 2 kategorie.")
            st.stop()
        chi2, p, dof, exp = stats.chi2_contingency(tab)
        n = tab.values.sum()
        v = cramers_v(chi2, n, tab.shape[0], tab.shape[1])
        result_text = interpret_chi2(chi2, p, dof, v, n, a, b)

        # Graf (mozaika = sloupcový stacked)
        fig, ax = plt.subplots()
        (tab / tab.sum()).plot(kind="bar", stacked=True, ax=ax)
        ax.set_title(f"Podíly kategorií: {a} × {b}")
        ax.set_ylabel("Podíl")
        fig_buf = io.BytesIO()
        fig.savefig(fig_buf, format="png", bbox_inches="tight")
        st.pyplot(fig)

        st.subheader("Interpretace")
        st.write(wrap(result_text))

elif analysis == "Porovnání více skupin (ANOVA)":
    cat_cols = [c for c,t in types.items() if t == "kategorická" and df[c].dropna().nunique() >= 2]
    num_cols = [c for c,t in types.items() if t == "numerická"]
    if not cat_cols or not num_cols:
        st.error("Potřebuji 1 kategoriální (≥2 skupiny) a 1 numerickou proměnnou.")
        st.stop()
    g = st.selectbox("Skupinová proměnná (≥2)", cat_cols)
    y = st.selectbox("Výstupová proměnná (numerická)", num_cols)

    if st.button("Spustit analýzu"):
        tmp = df[[g, y]].dropna()
        tmp = tmp.rename(columns={g: "group", y: "outcome"})
        if tmp["group"].nunique() < 2:
            st.error("Skupinová proměnná musí mít alespoň 2 úrovně.")
            st.stop()
        model = smf.ols("outcome ~ C(group)", data=tmp).fit()
        anova_tbl = sm.stats.anova_lm(model, typ=2)
        F = anova_tbl.loc['C(group)', 'F']
        p = anova_tbl.loc['C(group)', 'PR(>F)']
        eta2 = eta_squared_anova(anova_tbl)
        result_text = interpret_anova(F, p, eta2, tmp["group"].nunique(), len(tmp), g, y)

        # Graf (krabicový)
        fig, ax = plt.subplots()
        data_by_group = [tmp[tmp["group"] == lvl]["outcome"].values for lvl in tmp["group"].unique()]
        ax.boxplot(data_by_group, labels=[str(l) for l in tmp["group"].unique()])
        ax.set_title(f"{y} podle {g}")
        ax.set_ylabel(y)
        fig_buf = io.BytesIO()
        fig.savefig(fig_buf, format="png", bbox_inches="tight")
        st.pyplot(fig)

        st.subheader("Interpretace")
        st.write(wrap(result_text))

# ---------------------------
# EXPORT
# ---------------------------

st.divider()
st.subheader("📤 Export výsledků")
report_title = st.text_input("Název zprávy", value="Zpráva z kvantitativní analýzy (MVP)")
if st.button("Vygenerovat Word (DOCX)", disabled=(len(result_text.strip()) == 0)):
    bio = build_docx(report_title, meta_desc, result_text, fig_bytes=fig_buf)
    st.download_button(
        label="Stáhnout DOCX",
        data=bio,
        file_name="quantbuddy_vysledky.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

st.caption("⚠️ Pozn.: Jde o MVP pro rychlou orientaci. Před závěry vždy zvažte kontext, předpoklady testů a kvalitu dat.")

