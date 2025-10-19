# app.py — QuantBuddy (Vylepšená verze)
# Webová appka pro kvantitativní analýzy s českou interpretací
# Spuštění: streamlit run app.py

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
from statsmodels.formula.api import ols
from docx import Document
from docx.shared import Inches

# ========================================
# NASTAVENÍ STRÁNKY
# ========================================

st.set_page_config(
    page_title="QuantBuddy — chytrý parťák pro analýzu dat",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ========================================
# CUSTOM CSS — Tmavý/světlý režim + design
# ========================================

st.markdown("""
<style>
    /* Sjednocený font */
    html, body, [class*="css"] {
        font-family: 'Inter', 'Segoe UI', sans-serif;
    }
    
    /* Stylování hlavičky */
    .main-header {
        text-align: center;
        padding: 2rem 0;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border-radius: 10px;
        margin-bottom: 2rem;
        color: white;
    }
    
    /* Karty pro výsledky */
    .result-card {
        background-color: rgba(100, 126, 234, 0.1);
        padding: 1.5rem;
        border-radius: 10px;
        border-left: 4px solid #667eea;
        margin: 1rem 0;
    }
    
    /* Tlačítka */
    .stButton>button {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border-radius: 8px;
        padding: 0.5rem 2rem;
        font-weight: 600;
        border: none;
        transition: all 0.3s;
    }
    
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4);
    }
</style>
""", unsafe_allow_html=True)

# ========================================
# HLAVIČKA
# ========================================

st.markdown("""
<div class="main-header">
    <h1>📊 QuantBuddy</h1>
    <p style="font-size: 1.2rem; margin: 0;">Tvůj chytrý parťák pro kvantitativní výzkum</p>
    <p style="font-size: 0.9rem; opacity: 0.9;">Nahraj data → vyber analýzu → získej výsledky v češtině</p>
</div>
""", unsafe_allow_html=True)

# ========================================
# POMOCNÉ FUNKCE
# ========================================

def detect_var_types(df: pd.DataFrame, cat_unique_threshold: int = 10):
    """Detekce typů proměnných."""
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
    """Odstranění chybějících hodnot."""
    df = pd.concat([x, y], axis=1).dropna()
    return df.iloc[:,0], df.iloc[:,1]

def cohen_d_from_groups(g1, g2):
    """Výpočet Cohenova d."""
    n1, n2 = len(g1), len(g2)
    s1, s2 = np.var(g1, ddof=1), np.var(g2, ddof=1)
    sp = np.sqrt(((n1-1)*s1 + (n2-1)*s2) / (n1+n2-2))
    if sp == 0:
        return np.nan
    return (np.mean(g1) - np.mean(g2)) / sp

def cramers_v(chi2, n, r, c):
    """Výpočet Cramérova V."""
    return np.sqrt(chi2 / (n * (min(r-1, c-1))))

def eta_squared_anova(anova_table):
    """Výpočet η²."""
    try:
        ss_effect = anova_table.loc['C(group)', 'sum_sq']
        ss_resid = anova_table.loc['Residual', 'sum_sq']
        return ss_effect / (ss_effect + ss_resid)
    except Exception:
        return np.nan

# ========================================
# INTERPRETACE (CZ)
# ========================================

def interpret_correlation(stat, p, n, method, varx, vary):
    sig = p < 0.05
    absr = abs(stat)
    if absr >= 0.7:
        strength = "silný"
    elif absr >= 0.4:
        strength = "středně silný"
    elif absr >= 0.2:
        strength = "slabý"
    else:
        strength = "velmi slabý"
    trend = "pozitivní" if stat > 0 else ("negativní" if stat < 0 else "nulový")
    
    lines = [
        f"Byla provedena {method} korelace mezi „{varx}" a „{vary}" (n = {n}).",
        f"Výsledek ukazuje {strength} {trend} vztah (r = {stat:.3f}, p = {p:.4f})."
    ]
    if sig:
        lines.append("Vztah je statisticky významný (α = 0,05).")
    else:
        lines.append("Vztah není statisticky významný (α = 0,05).")
    return " ".join(lines)

def interpret_ttest(t, p, d, n1, n2, group, outcome):
    sig = p < 0.05
    eff = ""
    if not np.isnan(d):
        if abs(d) >= 0.8:
            mag = "velký"
        elif abs(d) >= 0.5:
            mag = "střední"
        else:
            mag = "malý"
        eff = f" (Cohenovo d = {d:.2f}, {mag} efekt)."
    
    lines = [
        f"T-test pro nezávislé výběry: „{outcome}" mezi skupinami „{group}" (n₁ = {n1}, n₂ = {n2}).",
        f"Výsledek: t = {t:.3f}, p = {p:.4f}{eff}"
    ]
    if sig:
        lines.append("Rozdíl je statisticky významný.")
    else:
        lines.append("Rozdíl není statisticky významný.")
    return " ".join(lines)

def interpret_chi2(chi2, p, dof, v, n, var1, var2):
    sig = p < 0.05
    mag = ""
    if not np.isnan(v):
        if v >= 0.5:
            size = "silná"
        elif v >= 0.3:
            size = "střední"
        else:
            size = "slabá"
        mag = f" Cramérovo V = {v:.2f} ({size} asociace)."
    
    lines = [
        f"Chí-kvadrát test: „{var1}" × „{var2}" (n = {n}, df = {dof}).",
        f"Výsledek: χ² = {chi2:.2f}, p = {p:.4f}.{mag}"
    ]
    if sig:
        lines.append("Asociace je statisticky významná.")
    else:
        lines.append("Asociace není statisticky významná.")
    return " ".join(lines)

def interpret_anova(F, p, eta2, k, n, group, outcome):
    sig = p < 0.05
    mag = ""
    if not np.isnan(eta2):
        if eta2 >= 0.14:
            size = "velký"
        elif eta2 >= 0.06:
            size = "střední"
        else:
            size = "malý"
        mag = f" (η² = {eta2:.3f}, {size} efekt)."
    
    lines = [
        f"ANOVA: „{outcome}" napříč {k} skupinami „{group}" (n = {n}).",
        f"Výsledek: F = {F:.3f}, p = {p:.4f}{mag}"
    ]
    if sig:
        lines.append("Rozdíly mezi skupinami jsou statisticky významné.")
    else:
        lines.append("Rozdíly nejsou statisticky významné.")
    return " ".join(lines)

def interpret_regression(r2, adj_r2, f_stat, f_p, coef, coef_p, n, x_var, y_var):
    sig = f_p < 0.05
    lines = [
        f"Lineární regrese: predikce „{y_var}" pomocí „{x_var}" (n = {n}).",
        f"Model: R² = {r2:.3f}, adjustované R² = {adj_r2:.3f}, F = {f_stat:.2f}, p = {f_p:.4f}.",
        f"Koeficient pro „{x_var}": β = {coef:.3f}, p = {coef_p:.4f}."
    ]
    if sig:
        lines.append("Model je statisticky významný.")
    else:
        lines.append("Model není statisticky významný.")
    return " ".join(lines)

# ========================================
# EXPORT DO DOCX
# ========================================

def build_docx(report_title, meta, results_text, fig_bytes=None):
    doc = Document()
    doc.add_heading(report_title, level=1)
    doc.add_paragraph(f"Datum: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    
    doc.add_heading("Popis dat", level=2)
    doc.add_paragraph(meta)
    
    doc.add_heading("Výsledky a interpretace", level=2)
    doc.add_paragraph(results_text)
    
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

# ========================================
# SIDEBAR — Načítání dat
# ========================================

with st.sidebar:
    st.markdown("### 📂 Nahraj data")
    file = st.file_uploader("CSV nebo Excel (.xlsx)", type=["csv", "xlsx"])
    
    df = None
    if file:
        try:
            if file.name.lower().endswith(".xlsx"):
                xls = pd.ExcelFile(file)
                sheet_name = st.selectbox("Vyber list", xls.sheet_names)
                df = pd.read_excel(file, sheet_name=sheet_name, engine='openpyxl')
            elif file.name.lower().endswith(".csv"):
                # Zkusí nejprve UTF-8, pak latin1
                try:
                    df = pd.read_csv(file, encoding='utf-8')
                except:
                    file.seek(0)
                    df = pd.read_csv(file, encoding='latin1', sep=';')
            st.success("✅ Data úspěšně načtena!")
        except Exception as e:
            st.error(f"❌ Chyba při načítání: {e}")
    
    st.markdown("---")
    st.markdown("### 🔬 Vyber analýzu")
    analysis = st.selectbox(
        "Typ analýzy",
        [
            "Korelace dvou proměnných",
            "Porovnání dvou skupin (t-test)",
            "Asociace kategoriálních (χ²)",
            "Porovnání více skupin (ANOVA)",
            "Lineární regrese"
        ]
    )

# ========================================
# HLAVNÍ OBSAH
# ========================================

if df is None:
    st.info("👈 Nahraj prosím datový soubor v levém panelu.")
    st.stop()

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Počet řádků", df.shape[0])
with col2:
    st.metric("Počet sloupců", df.shape[1])
with col3:
    st.metric("Chybějící hodnoty", df.isnull().sum().sum())

types = detect_var_types(df)

with st.expander("👀 Náhled dat a typů proměnných"):
    st.dataframe(df.head(10), use_container_width=True)
    typemap = pd.DataFrame({"Proměnná": list(types.keys()), "Typ": list(types.values())})
    st.dataframe(typemap, use_container_width=True)

# ========================================
# ANALÝZY
# ========================================

result_text = ""
fig_buf = None
meta_desc = f"Počet řádků: {df.shape[0]}, sloupců: {df.shape[1]}."

st.markdown("---")

# KORELACE
if analysis == "Korelace dvou proměnných":
    st.subheader("📈 Korelace dvou proměnných")
    num_cols = [c for c,t in types.items() if t == "numerická"]
    if len(num_cols) < 2:
        st.error("Potřebuješ alespoň 2 numerické proměnné.")
        st.stop()
    
    col1, col2, col3 = st.columns(3)
    with col1:
        x = st.selectbox("Proměnná X", num_cols, index=0)
    with col2:
        y = st.selectbox("Proměnná Y", num_cols, index=min(1, len(num_cols)-1))
    with col3:
        method = st.radio("Metoda", ["Pearson", "Spearman"], horizontal=True)
    
    if st.button("▶️ Spustit analýzu", use_container_width=True):
        sx, sy = clean_series_pair(df[x], df[y])
        if len(sx) < 5:
            st.error("Příliš málo platných hodnot (min. 5).")
            st.stop()
        
        if method == "Pearson":
            r, p = stats.pearsonr(sx, sy)
        else:
            r, p = stats.spearmanr(sx, sy)
        
        result_text = interpret_correlation(r, p, len(sx), method.lower(), x, y)
        
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.scatter(sx, sy, alpha=0.6, edgecolors='k')
        ax.set_xlabel(x, fontsize=12)
        ax.set_ylabel(y, fontsize=12)
        ax.set_title(f"Rozptylový graf: {x} × {y}", fontsize=14, weight='bold')
        ax.grid(alpha=0.3)
        fig_buf = io.BytesIO()
        fig.savefig(fig_buf, format="png", bbox_inches="tight", dpi=150)
        st.pyplot(fig)
        
        st.markdown(f'<div class="result-card"><strong>Interpretace:</strong><br>{result_text}</div>', unsafe_allow_html=True)

# T-TEST
elif analysis == "Porovnání dvou skupin (t-test)":
    st.subheader("📊 T-test pro nezávislé výběry")
    cat_cols = [c for c,t in types.items() if t == "kategorická"]
    num_cols = [c for c,t in types.items() if t == "numerická"]
    
    if not cat_cols or not num_cols:
        st.error("Potřebuješ alespoň 1 kategorickou a 1 numerickou proměnnou.")
        st.stop()
    
    col1, col2 = st.columns(2)
    with col1:
        group = st.selectbox("Skupinová proměnná", cat_cols)
    with col2:
        outcome = st.selectbox("Výstupní proměnná", num_cols)
    
    if st.button("▶️ Spustit analýzu", use_container_width=True):
        tmp = df[[group, outcome]].dropna()
        groups = tmp[group].unique()
        if len(groups) != 2:
            st.error(f"Skupinová proměnná musí mít přesně 2 úrovně (má {len(groups)}).")
            st.stop()
        
        g1 = tmp[tmp[group] == groups[0]][outcome]
        g2 = tmp[tmp[group] == groups[1]][outcome]
        t, p = stats.ttest_ind(g1, g2)
        d = cohen_d_from_groups(g1, g2)
        result_text = interpret_ttest(t, p, d, len(g1), len(g2), group, outcome)
        
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.boxplot([g1, g2], labels=groups, patch_artist=True)
        ax.set_ylabel(outcome, fontsize=12)
        ax.set_xlabel(group, fontsize=12)
        ax.set_title(f"Box plot: {outcome} podle {group}", fontsize=14, weight='bold')
        ax.grid(axis='y', alpha=0.3)
        fig_buf = io.BytesIO()
        fig.savefig(fig_buf, format="png", bbox_inches="tight", dpi=150)
        st.pyplot(fig)
        
        st.markdown(f'<div class="result-card"><strong>Interpretace:</strong><br>{result_text}</div>', unsafe_allow_html=True)

# CHÍ-KVADRÁT
elif analysis == "Asociace kategoriálních (χ²)":
    st.subheader("🔢 Chí-kvadrát test nezávislosti")
    cat_cols = [c for c,t in types.items() if t == "kategorická"]
    if len(cat_cols) < 2:
        st.error("Potřebuješ alespoň 2 kategorické proměnné.")
        st.stop()
    
    col1, col2 = st.columns(2)
    with col1:
        var1 = st.selectbox("Proměnná 1", cat_cols, index=0)
    with col2:
        var2 = st.selectbox("Proměnná 2", cat_cols, index=min(1, len(cat_cols)-1))
    
    if st.button("▶️ Spustit analýzu", use_container_width=True):
        tmp = df[[var1, var2]].dropna()
        ctab = pd.crosstab(tmp[var1], tmp[var2])
        chi2, p, dof, _ = stats.chi2_contingency(ctab)
        n = ctab.sum().sum()
        r, c = ctab.shape
        v = cramers_v(chi2, n, r, c)
        result_text = interpret_chi2(chi2, p, dof, v, n, var1, var2)
        
        fig, ax = plt.subplots(figsize=(8, 5))
        ctab.plot(kind='bar', stacked=True, ax=ax, colormap='viridis')
        ax.set_xlabel(var1, fontsize=12)
        ax.set_ylabel("Počet", fontsize=12)
        ax.set_title(f"Kontingenční tabulka: {var1} × {var2}", fontsize=14, weight='bold')
        ax.legend(title=var2)
        plt.xticks(rotation=45)
        fig_buf = io.BytesIO()
        fig.savefig(fig_buf, format="png", bbox_inches="tight", dpi=150)
        st.pyplot(fig)
        
        st.markdown(f'<div class="result-card"><strong>Interpretace:</strong><br>{result_text}</div>', unsafe_allow_html=True)

# ANOVA
elif analysis == "Porovnání více skupin (ANOVA)":
    st.subheader("📉 Jednofaktorová ANOVA")
    cat_cols = [c for c,t in types.items() if t == "kategorická"]
    num_cols = [c for c,t in types.items() if t == "numerická"]
    
    if not cat_cols or not num_cols:
        st.error("Potřebuješ alespoň 1 kategorickou a 1 numerickou proměnnou.")
        st.stop()
    
    col1, col2 = st.columns(2)
    with col1:
        group = st.selectbox("Skupinová proměnná", cat_cols)
    with col2:
        outcome = st.selectbox("Výstupní proměnná", num_cols)
    
    if st.button("▶️ Spustit analýzu", use_container_width=True):
        tmp = df[[group, outcome]].dropna()
        k = tmp[group].nunique()
        if k < 2:
            st.error("Skupinová proměnná musí mít alespoň 2 úrovně.")
            st.stop()
        
        formula = f"{outcome} ~ C({group})"
        model = ols(formula, data=tmp).fit()
        anova_table = sm.stats.anova_lm(model, typ=2)
        F = anova_table.loc[f'C({group})', 'F']
        p = anova_table.loc[f'C({group})', 'PR(>F)']
        eta2 = eta_squared_anova(anova_table)
        result_text = interpret_anova(F, p, eta2, k, len(tmp), group, outcome)
        
        fig, ax = plt.subplots(figsize=(8, 5))
        tmp.boxplot(column=outcome, by=group, ax=ax, patch_artist=True)
        ax.set_xlabel(group, fontsize=12)
        ax.set_ylabel(outcome, fontsize=12)
        ax.set_title(f"Box plot: {outcome} podle {group}", fontsize=14, weight='bold')
        plt.suptitle("")
        ax.grid(axis='y', alpha=0.3)
        fig_buf = io.BytesIO()
        fig.savefig(fig_buf, format="png", bbox_inches="tight", dpi=150)
        st.pyplot(fig)
        
        st.markdown(f'<div class="result-card"><strong>Interpretace:</strong><br>{result_text}</div>', unsafe_allow_html=True)

# LINEÁRNÍ REGRESE
elif analysis == "Lineární regrese":
    st.subheader("📐 Lineární regrese")
    num_cols = [c for c,t in types.items() if t == "numerická"]
    if len(num_cols) < 2:
        st.error("Potřebuješ alespoň 2 numerické proměnné.")
        st.stop()
    
    col1, col2 = st.columns(2)
    with col1:
        x_var = st.selectbox("Prediktory (X)", num_cols, index=0)
    with col2:
        y_var = st.selectbox("Výstup (Y)", num_cols, index=min(1, len(num_cols)-1))
    
    if st.button("▶️ Spustit analýzu", use_container_width=True):
        sx, sy = clean_series_pair(df[x_var], df[y_var])
        if len(sx) < 5:
            st.error("Příliš málo platných hodnot (min. 5).")
            st.stop()
        
        X = sm.add_constant(sx)
        model = sm.OLS(sy, X).fit()
        
        r2 = model.rsquared
        adj_r2 = model.rsquared_adj
        f_stat = model.fvalue
        f_p = model.f_pvalue
        coef = model.params[x_var]
        coef_p = model.pvalues[x_var]
        
        result_text = interpret_regression(r2, adj_r2, f_stat, f_p, coef, coef_p, len(sx), x_var, y_var)
        
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.scatter(sx, sy, alpha=0.6, label='Data', edgecolors='k')
        ax.plot(sx, model.predict(X), color='red', linewidth=2, label='Regresní přímka')
        ax.set_xlabel(x_var, fontsize=12)
        ax.set_ylabel(y_var, fontsize=12)
        ax.set_title(f"Lineární regrese: {y_var} ~ {x_var}", fontsize=14, weight='bold')
        ax.legend()
        ax.grid(alpha=0.3)
        fig_buf = io.BytesIO()
        fig.savefig(fig_buf, format="png", bbox_inches="tight", dpi=150)
        st.pyplot(fig)
        
        st.markdown(f'<div class="result-card"><strong>Interpretace:</strong><br>{result_text}</div>', unsafe_allow_html=True)
        
        with st.expander("📋 Detailní výsledky modelu"):
            st.text(model.summary())

# ========================================
# EXPORT DO DOCX
# ========================================

if result_text:
    st.markdown("---")
    st.subheader("💾 Export výsledků")
    if st.button("📄 Stáhnout jako DOCX", use_container_width=True):
        docx_file = build_docx(
            report_title=f"QuantBuddy — {analysis}",
            meta=meta_desc,
            results_text=result_text,
            fig_bytes=fig_buf
        )
        st.download_button(
            label="⬇️ Stáhnout report",
            data=docx_file,
            file_name=f"quantbuddy_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )

# ========================================
# FOOTER
# ========================================

st.markdown("---")
st.markdown("""
<div style="text-align: center; color: gray; font-size: 0.9rem;">
    Vytvořeno s ❤️ pomocí Streamlit | QuantBuddy v2.0
</div>
""", unsafe_allow_html=True)
