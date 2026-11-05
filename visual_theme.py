"""Presentation-only theme for the vendor-onboarding Streamlit app."""

from __future__ import annotations

import streamlit as st


THEME_CSS = """
<style>
:root {
    --vo-bg: #0B0F18;
    --vo-panel: #111827;
    --vo-panel-soft: #151E2E;
    --vo-input: #0C1422;
    --vo-line: #25324A;
    --vo-line-soft: #1D2940;
    --vo-text: #E7EDF7;
    --vo-muted: #94A3B8;
    --vo-indigo: #818CF8;
    --vo-blue: #38BDF8;
    --vo-teal: #2DD4BF;
}

header[data-testid="stHeader"] {
    background: rgba(11, 15, 24, 0.90);
    backdrop-filter: blur(12px);
}

.block-container {
    max-width: 1280px;
    padding-top: 1.45rem;
    padding-bottom: 3rem;
}

.block-container::before {
    content: "";
    display: block;
    width: 74px;
    height: 4px;
    margin-bottom: 1.25rem;
    border-radius: 999px;
    background: linear-gradient(90deg, var(--vo-indigo), var(--vo-blue), var(--vo-teal));
}

h1 {
    color: #F8FAFC;
    font-size: clamp(2.1rem, 4vw, 3rem);
    line-height: 1.08;
    letter-spacing: -0.035em;
    margin-bottom: 0.25rem;
}

h2, h3, h4 {
    color: #F1F5F9;
    letter-spacing: -0.018em;
}

p, label {
    line-height: 1.55;
}

div[data-baseweb="tab-list"] {
    gap: 0.35rem;
    background: var(--vo-panel);
    border: 1px solid var(--vo-line);
    border-radius: 0.75rem;
    padding: 0.32rem;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.16);
}

button[data-baseweb="tab"] {
    color: var(--vo-muted);
    border-radius: 0.52rem;
    padding-left: 1rem;
    padding-right: 1rem;
}

button[data-baseweb="tab"][aria-selected="true"] {
    color: #FFFFFF;
    background: #27335A;
    font-weight: 700;
}

div[data-testid="stForm"] {
    background: linear-gradient(145deg, #111827 0%, #0F1725 100%);
    border: 1px solid var(--vo-line);
    border-radius: 0.9rem;
    padding: 1.5rem;
    box-shadow: 0 16px 40px rgba(0, 0, 0, 0.22);
}

div[data-testid="stMetric"] {
    background: linear-gradient(145deg, #151E2E 0%, #101827 100%);
    border: 1px solid var(--vo-line);
    border-radius: 0.78rem;
    padding: 0.95rem 1.05rem;
    box-shadow: 0 8px 22px rgba(0, 0, 0, 0.14);
}

div[data-testid="stMetricLabel"] {
    color: var(--vo-muted);
}

div[data-testid="stMetricValue"] {
    color: #F8FAFC;
}

div[data-testid="stVerticalBlockBorderWrapper"] {
    background: rgba(17, 24, 39, 0.72);
    border-color: var(--vo-line);
    border-radius: 0.78rem;
}

div[data-testid="stExpander"] {
    background: var(--vo-panel);
    border-color: var(--vo-line);
    border-radius: 0.75rem;
}

div[data-testid="stAlert"] {
    border-radius: 0.72rem;
    border-width: 1px;
}

div[data-testid="stFileUploader"] section {
    background: var(--vo-input);
    border-color: #334266;
    border-radius: 0.72rem;
}

div[data-testid="stDataFrame"] {
    border: 1px solid var(--vo-line);
    border-radius: 0.72rem;
    overflow: hidden;
}

div[data-baseweb="input"],
div[data-baseweb="select"] > div {
    background-color: var(--vo-input);
}

.stFormSubmitButton > button,
.stButton > button[kind="primary"] {
    color: #FFFFFF;
    background: linear-gradient(100deg, #6366F1, #2563EB);
    border: 0;
    border-radius: 0.65rem;
    min-height: 2.8rem;
    font-weight: 700;
    box-shadow: 0 9px 22px rgba(37, 99, 235, 0.22);
}

.stFormSubmitButton > button:hover,
.stButton > button[kind="primary"]:hover {
    color: #FFFFFF;
    background: linear-gradient(100deg, #7C83F7, #3B82F6);
    box-shadow: 0 11px 26px rgba(37, 99, 235, 0.30);
}

.stButton > button[kind="secondary"] {
    color: var(--vo-text);
    background: var(--vo-panel-soft);
    border-color: var(--vo-line);
    border-radius: 0.65rem;
}

div[data-testid="stTextInput"] input:focus,
div[data-testid="stSelectbox"] > div:focus-within {
    border-color: var(--vo-indigo);
    box-shadow: 0 0 0 1px var(--vo-indigo);
}

/* Streamlit renders a "Press Enter to submit form" hint inside focused form
   inputs. On narrower columns it overlaps the placeholder and typed value. */
div[data-testid="stForm"] div[data-testid="InputInstructions"] {
    display: none;
}

.stCaption {
    color: var(--vo-muted);
}

hr {
    border-color: var(--vo-line-soft);
}

@media (max-width: 700px) {
    .block-container {
        padding-top: 1rem;
    }
    div[data-testid="stForm"] {
        padding: 1rem;
    }
}
</style>
"""


def apply_visual_theme() -> None:
    st.markdown(THEME_CSS, unsafe_allow_html=True)
