"""QR GENERATOR — labeled URL → vector QR codes with persistent history.

Split out of the original DESIGNBOX toolbox so the QR generator and the
image scraper run as independent tools. Shares the ImageScraper virtualenv
(see Launch QRGenerator.command).
"""

from __future__ import annotations

import io
import re
import json
import time
import hashlib
import html
from pathlib import Path

import segno
import streamlit as st


def slugify(value: str, fallback: str = "product") -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-_.")
    return value or fallback


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------


PAGE_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Roboto:wght@400;500;600;700&display=swap');

/* House of Brands hub theme — matches ../../styles.css tokens */
:root {
    --bg: #E8E3D5;           /* cream */
    --panel: #DED8C6;        /* recessed panel */
    --tile: #F2EEE3;         /* raised tile */
    --ink: #062553;          /* navy — Inspired PMS 654C */
    --muted: rgba(6, 37, 83, 0.62);
    --line: rgba(6, 37, 83, 0.28);
    --line-strong: rgba(6, 37, 83, 0.85);
    --input-bg: #E8E3D5;
    --accent: #E5682E;       /* Inspired orange — PMS Orange 021C */
    --accent-deep: #BF4F1D;
    --font-display: 'Bebas Neue', 'Arial Narrow', sans-serif;
    --font-body: 'Roboto', -apple-system, 'Helvetica Neue', Arial, sans-serif;

    /* Raised card — borderless tiles that lift on hover, cast in orange */
    --card-shadow: 0 1px 2px rgba(6, 37, 83, 0.06), 0 4px 12px rgba(6, 37, 83, 0.09);
    --card-shadow-lift: 0 2px 4px rgba(229, 104, 46, 0.075), 0 16px 32px rgba(229, 104, 46, 0.15);
}

html, body, .stApp, [data-testid="stAppViewContainer"] {
    background-color: var(--bg) !important;
}

[data-testid="stHeader"], [data-testid="stToolbar"] {
    background-color: transparent !important;
}

#MainMenu, footer, [data-testid="collapsedControl"] {
    visibility: hidden;
}

* {
    font-family: var(--font-body);
    color: var(--ink);
}

.block-container {
    padding-top: 2.2rem !important;
    padding-bottom: 6rem !important;
    padding-left: 3rem !important;
    padding-right: 3rem !important;
    max-width: 100% !important;
}

/* ------- top bar (mirrors hub masthead) ------- */
.top-bar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-bottom: 0.8rem;
    border-bottom: 1px solid var(--line);
    margin-bottom: 0;
    font-size: 11px;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    font-weight: 600;
}
.top-bar .left, .top-bar .right { display: flex; gap: 1.6rem; align-items: center; }
.top-bar .top-bar-tag {
    font-weight: 400;
    letter-spacing: 0.06em;
    text-transform: none;
    color: var(--muted);
    font-size: 11px;
}

/* ------- display headline (hub hero treatment) ------- */
.display-title {
    font-family: var(--font-display) !important;
    font-weight: 400 !important;
    font-size: clamp(64px, 12vw, 200px) !important;
    line-height: 0.88 !important;
    letter-spacing: -0.01em !important;
    text-transform: uppercase;
    margin: 0.55rem 0 0.5rem 0 !important;
    color: var(--ink) !important;
}

.stMarkdown p.display-sub,
.display-sub {
    color: var(--accent-deep) !important;
    font-size: 12px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--accent-deep);
    margin: 0 0 0.6rem 0;
    font-weight: 500;
}
.display-sub code {
    background-color: transparent !important;
    border: 1px solid var(--line-strong);
    padding: 1px 6px;
    font-family: var(--font-body) !important;
    font-size: 10px;
    text-transform: none;
    letter-spacing: 0;
    color: var(--accent-deep) !important;
}

/* ------- section heads (hub .section__title treatment) ------- */
.section-head {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.4rem 2rem;
    margin: 2.2rem 0 1.2rem 0;
    padding-bottom: 0.7rem;
    border-bottom: 1px solid var(--line);
}
.section-title {
    font-family: var(--font-display) !important;
    font-weight: 400 !important;
    text-transform: uppercase;
    font-size: clamp(1.6rem, 3.4vw, 2.4rem);
    line-height: 1;
    letter-spacing: 0.01em;
    color: var(--ink);
}
.section-note {
    font-family: var(--font-body);
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--muted);
}
.thick-rule {
    border: none !important;
    border-top: 2px solid var(--accent) !important;
    margin: 0.6rem 0 1.6rem 0 !important;
}

/* ------- cards (hub shared card system: borderless raised tiles) -------
   Streamlit tags any st.container(key=...) with an `st-key-<key>` class, so
   the card treatment hangs off our own keys rather than Streamlit's internal
   block wrappers — no risk of every column turning into a tile. */
[class*="st-key-qr_card_"],
.st-key-qr_panel {
    border: none !important;
    border-radius: 15px !important;
    background: var(--tile) !important;
    box-shadow: var(--card-shadow);
    transition: transform 220ms cubic-bezier(0.34, 1.3, 0.64, 1),
        box-shadow 220ms ease;
}
.st-key-qr_panel { padding: 1.25rem 1.3rem 1.4rem !important; }
[class*="st-key-qr_card_"]:hover,
[class*="st-key-qr_card_"]:focus-within,
.st-key-qr_panel:hover,
.st-key-qr_panel:focus-within {
    transform: translateY(-6px);
    box-shadow: var(--card-shadow-lift);
}

/* Cards keep a common height so a row reads as one band, however long a label
   wraps. A Streamlit column is only as tall as its content by default, so the
   height has to be handed down from the row through its two wrapper divs. */
[data-testid="stColumn"] > [data-testid="stVerticalBlock"],
[data-testid="stColumn"] > [data-testid="stVerticalBlock"] > [data-testid="stLayoutWrapper"] {
    height: 100%;
}

/* Card layout — QR plate takes the whole left side, the export buttons stack
   in a narrow strip on the right, and the label + link sit at the bottom left.
   A CSS grid rather than st.columns: the cards already live inside a nested
   column, and Streamlit only allows one level of column nesting. The three
   children are, in order, the plate, the label block and the button strip. */
[class*="st-key-qr_card_"] {
    height: 100%;
    display: grid;
    grid-template-columns: minmax(0, 1fr) 1.9rem;
    grid-template-rows: auto 1fr;
    /* The label spans the full width on the second row: the button strip and
       the plate come out to about the same height, so there's nothing to sit
       beside, and the label gets the whole card to wrap in. */
    grid-template-areas:
        "qr   acts"
        "meta meta";
    gap: 0.35rem;
    padding: 0.55rem !important;
    position: relative; /* anchors the jump target — see .qr-anchor */
}
[class*="st-key-qr_card_"] > *:nth-child(1) { grid-area: qr; }
[class*="st-key-qr_card_"] > *:nth-child(2) { grid-area: meta; align-self: end; }
[class*="st-key-qr_card_"] > *:nth-child(3) { grid-area: acts; }

/* Export strip — small stacked buttons, tight against the plate. Descendant
   selectors (not `>`): the delete button carries a help tooltip, so Streamlit
   buries it under a couple of wrapper divs. The extra class also outweighs
   the general button rules further down the sheet. */
[class*="st-key-qr_foot_"] {
    gap: 0.22rem !important;
}
[class*="st-key-qr_foot_"] .stDownloadButton button,
[class*="st-key-qr_foot_"] .stButton button {
    padding: 0.1rem 0.1rem !important;
    font-size: 8px !important;
    letter-spacing: 0.03em !important;
    /* A fixed height keeps all four the same: Streamlit's own label wrappers
       carry different line-heights per button type. */
    min-height: 0 !important;
    height: 1.45rem !important;
    border-radius: 4px !important;
    width: 100%;
}
[class*="st-key-qr_foot_"] .stButton button { font-size: 10px !important; }
[class*="st-key-qr_foot_"] button div,
[class*="st-key-qr_foot_"] button p {
    font-size: inherit !important;
    line-height: 1.1 !important;
}
[class*="st-key-qr_foot_"] [data-testid="stTooltipIcon"],
[class*="st-key-qr_foot_"] [data-testid="stTooltipHoverTarget"] {
    display: block;
    width: 100%;
}

/* Sits at the card's top edge so the index links land on the whole card
   rather than scrolling to the label at its foot. */
.qr-anchor {
    position: absolute;
    top: 0;
    left: 0;
    scroll-margin-top: 1.5rem;
}

/* The label clamps to two lines and the link to one, so a single long URL
   can't stretch a whole row of cards — the full address stays in the link's
   href and its tooltip. Streamlit sets `display: flow-root` on the children
   of a markdown block, hence the !important on both. */
.qr-card__name {
    font-family: var(--font-display) !important;
    font-weight: 400;
    text-transform: uppercase;
    font-size: 0.95rem;
    line-height: 1.02;
    letter-spacing: 0.01em;
    color: var(--ink);
    margin: 0 0 0.15rem;
    display: -webkit-box !important;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    word-break: break-word;
}
.qr-card__url {
    font-family: var(--font-body);
    font-size: 9px;
    font-weight: 500;
    line-height: 1.35;
    color: var(--muted);
    text-decoration: none;
    display: block !important;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.qr-card__url:hover { color: var(--accent-deep); text-decoration: underline; }
.qr-card__meta {
    font-family: var(--font-body);
    font-size: 8px;
    font-weight: 500;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: var(--muted);
    margin-top: 0.25rem;
}

/* ------- history index (sticky list nav beside the card grid) ------- */
.qr-nav {
    position: sticky;
    top: 0.25rem;
    background: var(--tile);
    border-radius: 15px;
    box-shadow: var(--card-shadow);
    padding: 0.9rem 0.9rem 0.5rem;
}
.qr-nav__head {
    font-family: var(--font-display);
    font-weight: 400;
    text-transform: uppercase;
    font-size: 1.15rem;
    line-height: 1;
    letter-spacing: 0.02em;
    color: var(--ink);
    padding-bottom: 0.5rem;
    border-bottom: 2px solid var(--accent);
}
.qr-nav__list {
    list-style: none;
    margin: 0;
    padding: 0;
    max-height: 62vh;
    overflow-y: auto;
}
.qr-nav__list li { border-bottom: 1px solid var(--line); }
.qr-nav__list li:last-child { border-bottom: none; }
.qr-nav__list a {
    display: flex;
    gap: 0.5rem;
    padding: 0.45rem 0.35rem;
    border-radius: 4px;
    font-family: var(--font-body);
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    line-height: 1.3;
    color: var(--ink);
    text-decoration: none;
}
.qr-nav__list a:hover {
    color: var(--accent-deep);
    background: var(--bg);
}
.qr-nav__idx {
    flex: none;
    color: var(--accent);
    font-weight: 700;
}
/* Labels are hyphenated slugs, so they need to break anywhere rather than
   overflow the panel — flex items also need min-width:0 to shrink at all. */
.qr-nav__list a span:last-child {
    min-width: 0;
    overflow-wrap: anywhere;
}
/* Streamlit's scroll container is the main block, so the smooth scroll and
   the jump both have to be set there rather than on <html>. */
[data-testid="stMain"] { scroll-behavior: smooth; }

/* ------- tabs ------- */
.stTabs [data-baseweb="tab-list"] {
    gap: 0;
    border-bottom: 2px solid var(--accent);
    background-color: transparent;
}
.stTabs [data-baseweb="tab"] {
    background-color: transparent;
    color: var(--ink);
    font-weight: 600;
    font-size: 12px;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    padding: 16px 28px;
    border: none;
    border-radius: 0;
}
.stTabs [aria-selected="true"] {
    background-color: var(--ink) !important;
    color: var(--tile) !important;
}
.stTabs [aria-selected="true"] p {
    color: var(--tile) !important;
}
.stTabs [data-baseweb="tab"]:hover {
    background-color: var(--tile);
}
.stTabs [aria-selected="true"]:hover {
    background-color: var(--ink) !important;
}
.stTabs [data-baseweb="tab-highlight"] { display: none; }
.stTabs [data-baseweb="tab-panel"] { padding-top: 1.6rem; }

/* ------- buttons (hub .fmt-btn: navy pill, orange on hover) ------- */
.stButton > button,
.stDownloadButton > button {
    border-radius: 5px !important;
    border: none !important;
    background-color: var(--ink) !important;
    color: var(--tile) !important;
    font-family: var(--font-body) !important;
    font-weight: 600 !important;
    letter-spacing: 0.1em !important;
    text-transform: uppercase !important;
    padding: 0.55rem 0.6rem !important;
    font-size: 11px !important;
    transition: background-color 140ms ease;
    box-shadow: none !important;
    width: 100%;
    line-height: 1.1 !important;
}

.stButton > button p,
.stDownloadButton > button p {
    color: var(--tile) !important;
    font-family: var(--font-body) !important;
}

.stButton > button:hover,
.stDownloadButton > button:hover {
    background-color: var(--accent) !important;
    color: var(--tile) !important;
}

.stButton > button[kind="primary"],
[data-testid="baseButton-primary"] {
    background-color: var(--ink) !important;
    color: var(--tile) !important;
    border: none !important;
    padding: 0.7rem 1.6rem !important;
}
.stButton > button[kind="primary"]:hover,
[data-testid="baseButton-primary"]:hover {
    background-color: var(--accent) !important;
    color: var(--tile) !important;
}

.stButton > button:focus,
.stButton > button:focus-visible,
.stDownloadButton > button:focus,
.stDownloadButton > button:focus-visible {
    outline: 2px solid var(--accent) !important;
    outline-offset: 3px !important;
    box-shadow: none !important;
}

/* Delete buttons → outlined deep signal, same family as the hub accents */
[class*="st-key-qr_h_del_"] button {
    border-radius: 5px !important;
    background-color: transparent !important;
    border: 1px solid var(--accent-deep) !important;
    color: var(--accent-deep) !important;
    font-size: 14px !important;
    letter-spacing: 0 !important;
    font-weight: 700 !important;
    padding: 0.5rem 0.5rem !important;
}
[class*="st-key-qr_h_del_"] button:hover {
    background-color: var(--accent-deep) !important;
    color: #fff !important;
}
[class*="st-key-qr_h_del_"] button p {
    color: inherit !important;
}

/* ------- inputs (hub .input: cream field, 5px radius) ------- */
.stTextArea textarea {
    background-color: var(--input-bg) !important;
    border: 1px solid var(--line-strong) !important;
    border-radius: 5px !important;
    color: var(--ink) !important;
    font-family: var(--font-body) !important;
    font-size: 13px !important;
    padding: 14px !important;
}
.stTextArea label,
.stFileUploader label,
.stSelectbox label,
.stNumberInput label,
.stTextInput label {
    font-family: var(--font-body) !important;
    font-weight: 500 !important;
    font-size: 10px !important;
    letter-spacing: 0.1em !important;
    text-transform: uppercase !important;
    color: var(--muted) !important;
}

[data-testid="stFileUploader"] section {
    background-color: transparent !important;
    border: 1px dashed var(--line-strong) !important;
    border-radius: 0 !important;
    padding: 1.4rem !important;
}
[data-testid="stFileUploader"] section button {
    border-radius: 0 !important;
    border: 1px solid var(--line-strong) !important;
    background-color: transparent !important;
    color: var(--ink) !important;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    font-size: 11px;
    font-weight: 600;
}
[data-testid="stFileUploader"] section button:hover {
    background-color: var(--ink) !important;
    color: var(--tile) !important;
}

[data-baseweb="select"] > div {
    background-color: var(--input-bg) !important;
    border: 1px solid var(--line-strong) !important;
    border-radius: 5px !important;
}
.stNumberInput input, .stTextInput input {
    background-color: transparent !important;
    border: none !important;
    border-radius: 5px !important;
    color: var(--ink) !important;
    font-family: var(--font-body) !important;
    font-size: 14px !important;
}
.stTextInput input::placeholder {
    color: var(--muted) !important;
    opacity: 0.7;
}
/* The Base Web wrapper around text/number inputs is what actually paints
   the field background — the inner <input> is layered on top, so we set
   the colour on the wrapper and let the input itself stay transparent. */
.stTextInput [data-baseweb="input"],
.stTextInput [data-baseweb="base-input"],
.stNumberInput [data-baseweb="input"],
.stNumberInput [data-baseweb="base-input"] {
    background-color: var(--input-bg) !important;
    border: 1px solid var(--line-strong) !important;
    border-radius: 5px !important;
}
.stNumberInput button {
    background-color: transparent !important;
    border: 1px solid var(--line-strong) !important;
    border-radius: 5px !important;
    color: var(--ink) !important;
}

/* ------- metrics ------- */
[data-testid="stMetric"] {
    background-color: transparent;
    border-top: 1px solid var(--line-strong);
    border-bottom: 1px solid var(--line-strong);
    padding: 20px 0 24px 0;
}
[data-testid="stMetricLabel"] p {
    font-size: 11px !important;
    letter-spacing: 0.1em !important;
    text-transform: uppercase !important;
    font-weight: 500 !important;
    color: var(--muted) !important;
    margin-bottom: 0.45rem !important;
}
[data-testid="stMetricValue"] {
    font-family: var(--font-display) !important;
    font-size: 72px !important;
    font-weight: 400 !important;
    color: var(--ink);
    line-height: 1;
    letter-spacing: 0;
}

/* ------- expander ------- */
[data-testid="stExpander"] {
    border-radius: 0 !important;
    border: none !important;
    border-top: 1px solid var(--line) !important;
    background-color: transparent !important;
}
[data-testid="stExpander"] summary {
    background-color: transparent !important;
    font-weight: 600 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.1em !important;
    font-size: 11px !important;
    padding: 0.95rem 0.4rem !important;
}
[data-testid="stExpander"] summary p {
    font-weight: 600 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.1em !important;
    font-size: 11px !important;
    color: var(--ink) !important;
}

/* ------- progress ------- */
.stProgress > div > div > div > div {
    background-color: var(--accent) !important;
    border-radius: 0 !important;
}
.stProgress > div > div > div {
    background-color: var(--line) !important;
    border-radius: 0 !important;
}

/* ------- code / log ------- */
pre, code {
    background-color: transparent !important;
    color: var(--ink) !important;
    font-family: var(--font-body) !important;
    font-size: 11px !important;
    letter-spacing: 0.02em;
}
[data-testid="stCode"], .stCodeBlock {
    background-color: var(--panel) !important;
    border: 1px solid var(--line) !important;
    border-radius: 0 !important;
}
[data-testid="stCode"] pre { background-color: transparent !important; }

/* ------- captions / alerts ------- */
[data-testid="stCaptionContainer"] {
    color: var(--muted) !important;
    font-size: 11px !important;
    letter-spacing: 0.04em !important;
    font-family: var(--font-body) !important;
}
[data-testid="stAlert"] {
    background-color: transparent !important;
    border: none !important;
    border-left: 2px solid var(--accent) !important;
    border-radius: 0 !important;
    color: var(--ink) !important;
    font-size: 12px !important;
    letter-spacing: 0.04em !important;
    padding: 0.6rem 1rem !important;
}
[data-testid="stAlert"] p, [data-testid="stAlert"] div {
    color: var(--ink) !important;
}
[data-testid="stAlert"] svg { display: none; }

/* ------- markdown body ------- */
.stMarkdown p {
    font-size: 13px;
    line-height: 1.6;
    color: var(--ink);
}

/* ------- dataframe ------- */
[data-testid="stDataFrame"] {
    border: 1px solid var(--line-strong) !important;
    border-radius: 0 !important;
}

/* ------- images (the QR plate reads as the card's own tile) ------- */
[data-testid="stImage"] img {
    background-color: #fff;
    border: 1px solid var(--line);
    border-radius: 10px;
}
/* The plate fills the card's width — the PNG carries its own quiet zone, so
   it needs no inner padding. Every wrapper Streamlit puts between the element
   container and the <img> is shrink-to-fit, so each one has to be opened up,
   and the <img> itself is sized by an inline width — hence the !important. */
[class*="st-key-qr_card_"] [data-testid="stFullScreenFrame"] > div,
[class*="st-key-qr_card_"] [data-testid="stImage"],
[class*="st-key-qr_card_"] [data-testid="stImageContainer"] {
    width: 100% !important;
}
[class*="st-key-qr_card_"] [data-testid="stImage"] img {
    width: 100% !important;
    height: auto !important;
}
[data-testid="stImage"] figcaption {
    font-family: var(--font-body) !important;
    font-size: 10px !important;
    letter-spacing: 0.04em !important;
    color: var(--muted) !important;
    text-align: left !important;
    padding-top: 6px;
}

/* ------- divider ------- */
hr {
    border-top: 1px solid var(--line) !important;
    margin: 1.2rem 0 !important;
    opacity: 1;
}

/* ------- spacer helpers ------- */
.spacer-sm { height: 0.8rem; }
.spacer-md { height: 1.5rem; }
.spacer-lg { height: 2.5rem; }
</style>
"""


def section_head(title: str, note: str = ""):
    """Bebas Neue section title with a Roboto note, as on the hub sections."""
    note_html = f'<span class="section-note">{note}</span>' if note else ""
    st.markdown(
        f'<div class="section-head">'
        f'<h2 class="section-title">{title}</h2>'
        f'{note_html}'
        f'</div>',
        unsafe_allow_html=True,
    )


def spacer(size: str = "md"):
    st.markdown(f'<div class="spacer-{size}"></div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# QRBuddy — labeled URL → vector QR with persistent history
# ---------------------------------------------------------------------------

# History is stored as JSON next to app.py so it survives Streamlit restarts.
QR_HISTORY_PATH = Path(__file__).resolve().parent / "qrbuddy_history.json"

# Sensible defaults — sizing/colors are handled in the user's design tool.
QR_ERROR_LEVEL = "Q"        # ~25% recovery — solid middle ground
QR_DEFAULT_SCALE = 10       # for SVG/PDF/EPS exports (unitless module scale)
QR_DEFAULT_BORDER = 4       # spec-recommended quiet zone in modules
QR_FG = "#000000"
QR_BG = "#FFFFFF"


def _qr_bytes(url: str, kind: str) -> bytes:
    """Render `url` as a vector QR in the requested format.

    `kind` is one of: 'svg', 'pdf', 'eps'. Sizing is handled in the user's
    design tool, so we emit at a known scale with sensible defaults.
    """
    qr = segno.make(url, error=QR_ERROR_LEVEL, micro=False)
    # segno's EPS writer is text-mode; PDF and SVG write bytes.
    buf = io.StringIO() if kind == "eps" else io.BytesIO()
    qr.save(
        buf,
        kind=kind,
        scale=QR_DEFAULT_SCALE,
        border=QR_DEFAULT_BORDER,
        dark=QR_FG,
        light=QR_BG,
    )
    out = buf.getvalue()
    return out.encode("utf-8") if isinstance(out, str) else out


def _qr_thumbnail_png(url: str, scale: int = 8) -> bytes:
    """Render a PNG of the QR for the in-card plate. PNG bytes are the safest
    input for st.image() across all Streamlit versions — passing raw SVG bytes
    can route through PIL on some versions and fail. The scale is set so the
    plate is rendered at, not upscaled to, its card width."""
    qr = segno.make(url, error=QR_ERROR_LEVEL, micro=False)
    buf = io.BytesIO()
    qr.save(
        buf,
        kind="png",
        scale=scale,
        border=QR_DEFAULT_BORDER,
        dark=QR_FG,
        light=QR_BG,
    )
    return buf.getvalue()


# ---------------------------------------------------------------------------
# QRBuddy — history persistence
# ---------------------------------------------------------------------------


def load_qr_history() -> list[dict]:
    """Read the on-disk history. Returns [] if the file is missing/corrupt."""
    if not QR_HISTORY_PATH.exists():
        return []
    try:
        data = json.loads(QR_HISTORY_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return []


def save_qr_history(items: list[dict]) -> None:
    QR_HISTORY_PATH.write_text(
        json.dumps(items, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def add_qr_history_entry(label: str, url: str) -> dict:
    """Prepend a new entry. If an entry with the same label exists, replace it
    in place (most recent stays first)."""
    items = load_qr_history()
    items = [i for i in items if i.get("label") != label]
    entry = {
        "id": hashlib.md5(f"{label}|{url}|{time.time()}"
                          .encode("utf-8")).hexdigest()[:12],
        "label": label,
        "url": url,
        "ts": int(time.time()),
    }
    items.insert(0, entry)
    save_qr_history(items)
    return entry


def remove_qr_history_entry(entry_id: str) -> None:
    items = [i for i in load_qr_history() if i.get("id") != entry_id]
    save_qr_history(items)


def relative_time(ts: int) -> str:
    delta = max(0, int(time.time()) - int(ts))
    if delta < 5:
        return "just now"
    if delta < 60:
        return f"{delta}s ago"
    if delta < 3600:
        return f"{delta // 60}m ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    if delta < 86400 * 30:
        return f"{delta // 86400}d ago"
    return time.strftime("%Y-%m-%d", time.localtime(ts))


# ---------------------------------------------------------------------------
# QRBuddy — UI
# ---------------------------------------------------------------------------


# QR cards per row. Five keeps the plate around 130–190px depending on window
# width — still comfortably scannable off the screen. Push this higher and the
# plate starts dropping below a readable module size.
QR_CARDS_PER_ROW = 5


def _qr_card(entry: dict):
    """Render one history entry as a hub-style card: QR plate on top, Bebas
    label, Roboto url/timestamp, then the export row."""
    label = entry.get("label", "")
    url = entry.get("url", "")
    eid = entry.get("id", "")
    ts = entry.get("ts", 0)

    safe_stem = slugify(label, fallback="qrbuddy")

    try:
        svg = _qr_bytes(url, "svg")
        thumb_png = _qr_thumbnail_png(url)
    except Exception as e:
        st.error(f"Couldn't render '{label}': {e}")
        return

    # Three children in this order — the CSS grid places them into the plate,
    # label and button-strip areas. Adding one means updating PAGE_CSS.
    with st.container(border=True, key=f"qr_card_{eid}"):
        st.image(thumb_png)
        # st.html, not st.markdown: the markdown pass auto-links any bare URL
        # in the text, which replaces this styled anchor with its own.
        st.html(
            f'<div class="qr-card__meta-block">'
            f'<span class="qr-anchor" id="qr-{eid}"></span>'
            f'<div class="qr-card__name">{html.escape(label)}</div>'
            f'<a class="qr-card__url" href="{html.escape(url, quote=True)}" '
            f'title="{html.escape(url, quote=True)}" '
            f'target="_blank" rel="noopener">{html.escape(url)}</a>'
            f'<div class="qr-card__meta">{relative_time(ts)}</div>'
            f'</div>'
        )
        with st.container(key=f"qr_foot_{eid}"):
            st.download_button(
                "SVG",
                data=svg,
                file_name=f"{safe_stem}.svg",
                mime="image/svg+xml",
                key=f"qr_h_svg_{eid}",
                width="stretch",
            )
            try:
                st.download_button(
                    "PDF",
                    data=_qr_bytes(url, "pdf"),
                    file_name=f"{safe_stem}.pdf",
                    mime="application/pdf",
                    key=f"qr_h_pdf_{eid}",
                    width="stretch",
                )
            except Exception:
                st.caption("PDF —")
            try:
                st.download_button(
                    "EPS",
                    data=_qr_bytes(url, "eps"),
                    file_name=f"{safe_stem}.eps",
                    mime="application/postscript",
                    key=f"qr_h_eps_{eid}",
                    width="stretch",
                )
            except Exception:
                st.caption("EPS —")
            if st.button("✕", key=f"qr_h_del_{eid}",
                         help="Remove from history", width="stretch"):
                remove_qr_history_entry(eid)
                st.rerun()


def _qr_index(history: list[dict]):
    """Sticky list nav beside the grid — each row jumps to that entry's card."""
    items = "".join(
        f'<li><a href="#qr-{e.get("id", "")}">'
        f'<span class="qr-nav__idx">{i:02d}</span>'
        f'<span>{html.escape(e.get("label", ""))}</span>'
        f'</a></li>'
        for i, e in enumerate(history, start=1)
    )
    st.html(
        f'<nav class="qr-nav" aria-label="QR history index">'
        f'<div class="qr-nav__head">Index</div>'
        f'<ol class="qr-nav__list">{items}</ol>'
        f'</nav>'
    )


def render_qrbuddy():
    """QRBuddy — labeled URL → vector QR with persistent history."""
    st.markdown(
        '<p class="display-sub">'
        'Vector QR codes · keep a labeled history'
        '</p>',
        unsafe_allow_html=True,
    )

    # Bumped each time we successfully generate so the next run gets fresh
    # widget keys (i.e. the URL and Label fields render empty). Streamlit
    # forbids mutating a widget's session_state key after it has rendered,
    # so we can't just clear the values directly.
    st.session_state.setdefault("qr_input_nonce", 0)
    nonce = st.session_state["qr_input_nonce"]

    section_head("Generate", "Label it, and it keeps — vector exports on tap")
    with st.container(border=True, key="qr_panel"):
        col_url, col_label = st.columns([3, 2])
        with col_url:
            url = st.text_input(
                "URL",
                placeholder="https://example.com",
                key=f"qr_url_{nonce}",
            )
        with col_label:
            label = st.text_input(
                "Label",
                placeholder="Label this QR",
                key=f"qr_label_{nonce}",
                help="A name for this QR — used as the filename and shown in history.",
            )

        spacer("sm")
        col_go, _ = st.columns([2, 7])
        with col_go:
            generate = st.button("Generate", type="primary", key="qr_generate")

    if generate:
        u = (url or "").strip()
        l = (label or "").strip()
        if not u:
            st.error("URL is required.")
        elif not l:
            st.error("Label is required.")
        else:
            add_qr_history_entry(label=l, url=u)
            # Bump the nonce so the next run uses brand-new widget keys
            # (effectively clearing the inputs without mutating the old keys).
            st.session_state["qr_input_nonce"] = nonce + 1
            st.rerun()

    history = load_qr_history()
    if not history:
        spacer("md")
        st.info("No QR codes yet. Add a URL and a label above.")
        return

    section_head("History", f"{len(history)} saved · newest first")
    # 6:1 keeps the plates as large as possible — the index only needs enough
    # width for a two-line label.
    col_grid, col_index = st.columns([6, 1], gap="large")
    with col_grid:
        # Cards laid out row by row so a short row still keeps the column
        # widths of a full one — the last row's tiles don't stretch out.
        for start in range(0, len(history), QR_CARDS_PER_ROW):
            row = history[start:start + QR_CARDS_PER_ROW]
            cols = st.columns(QR_CARDS_PER_ROW, gap="small")
            for col, entry in zip(cols, row):
                with col:
                    _qr_card(entry)
            spacer("sm")
    with col_index:
        _qr_index(history)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main():
    st.set_page_config(
        page_title="QRafty",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st.markdown(PAGE_CSS, unsafe_allow_html=True)

    st.markdown(
        '<div class="top-bar">'
        '<div class="left">'
        '<span>QR GENERATOR</span>'
        '<span class="top-bar-tag">House of Brands · tool module</span>'
        '</div>'
        '<div class="right">'
        '<span>v1.0</span>'
        '<span>Streamlit</span>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    st.markdown('<h1 class="display-title">QRafty</h1>', unsafe_allow_html=True)
    st.markdown('<hr class="thick-rule">', unsafe_allow_html=True)

    render_qrbuddy()


if __name__ == "__main__":
    main()
