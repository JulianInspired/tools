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
    --input-bg: #F2EEE3;
    --accent: #E5682E;       /* Inspired orange — PMS Orange 021C */
    --accent-deep: #BF4F1D;
    --font-display: 'Bebas Neue', 'Arial Narrow', sans-serif;
    --font-body: 'Roboto', -apple-system, 'Helvetica Neue', Arial, sans-serif;
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

/* ------- section dividers ------- */
.section-row {
    display: flex;
    align-items: baseline;
    gap: 1.2rem;
    margin: 1.8rem 0 0.6rem 0;
}
.section-label {
    font-weight: 600;
    font-size: 11px;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--muted);
    flex-shrink: 0;
    min-width: 130px;
}
.section-row .rule {
    flex: 1;
    height: 1px;
    background: var(--line);
}
.thick-rule {
    border: none !important;
    border-top: 2px solid var(--accent) !important;
    margin: 0.6rem 0 1.6rem 0 !important;
}

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

/* ------- buttons (hub style: flat navy rectangles) ------- */
.stButton > button,
.stDownloadButton > button {
    border-radius: 0 !important;
    border: none !important;
    background-color: var(--ink) !important;
    color: var(--tile) !important;
    font-weight: 600 !important;
    letter-spacing: 0.1em !important;
    text-transform: uppercase !important;
    padding: 0.7rem 1.4rem !important;
    font-size: 11px !important;
    transition: background-color 140ms ease;
    box-shadow: none !important;
    width: 100%;
    line-height: 1.1 !important;
}

.stButton > button p,
.stDownloadButton > button p {
    color: var(--tile) !important;
}

.stButton > button:hover,
.stDownloadButton > button:hover {
    background-color: var(--accent-deep) !important;
    color: var(--tile) !important;
}

.stButton > button[kind="primary"],
[data-testid="baseButton-primary"] {
    background-color: var(--ink) !important;
    color: var(--tile) !important;
    border: none !important;
}
.stButton > button[kind="primary"]:hover,
[data-testid="baseButton-primary"]:hover {
    background-color: var(--accent-deep) !important;
    color: var(--tile) !important;
}

.stButton > button:focus,
.stButton > button:focus-visible,
.stDownloadButton > button:focus,
.stDownloadButton > button:focus-visible {
    outline: 2px solid var(--accent) !important;
    outline-offset: 2px !important;
    box-shadow: none !important;
}

/* icon-only buttons (play / clear): larger glyph, no tracking */
.st-key-start_text button,
.st-key-start_bulk button,
.st-key-clear_text button,
.st-key-clear_bulk button {
    font-size: 16px !important;
    letter-spacing: 0 !important;
    padding: 0.7rem 1.4rem !important;
}

/* Scraper start buttons → signal orange block */
.st-key-start_text button,
.st-key-start_bulk button {
    background-color: var(--accent) !important;
    color: #fff !important;
    font-weight: 700 !important;
}
.st-key-start_text button:hover,
.st-key-start_bulk button:hover {
    background-color: var(--accent-deep) !important;
}
.st-key-start_text button p,
.st-key-start_bulk button p {
    color: #fff !important;
}

/* Clear / delete buttons → deep signal, same family as accents */
.st-key-clear_text button,
.st-key-clear_bulk button,
[class*="st-key-qr_h_del_"] button {
    border-radius: 0 !important;
    background-color: transparent !important;
    border: 1px solid var(--accent-deep) !important;
    color: var(--accent-deep) !important;
    font-size: 15px !important;
    letter-spacing: 0 !important;
    font-weight: 700 !important;
}
.st-key-clear_text button:hover,
.st-key-clear_bulk button:hover,
[class*="st-key-qr_h_del_"] button:hover {
    background-color: var(--accent-deep) !important;
    color: #fff !important;
}
.st-key-clear_text button p,
.st-key-clear_bulk button p,
[class*="st-key-qr_h_del_"] button p {
    color: inherit !important;
}
[class*="st-key-qr_h_del_"] button {
    padding: 0.55rem 0.9rem !important;
}

/* ------- inputs ------- */
.stTextArea textarea {
    background-color: var(--input-bg) !important;
    border: 1px solid var(--line-strong) !important;
    border-radius: 0 !important;
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
    font-weight: 500 !important;
    font-size: 11px !important;
    letter-spacing: 0.08em !important;
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
    border-radius: 0 !important;
}
.stNumberInput input, .stTextInput input {
    background-color: transparent !important;
    border: none !important;
    border-radius: 0 !important;
    color: var(--ink) !important;
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
    border-radius: 0 !important;
}
.stNumberInput button {
    background-color: transparent !important;
    border: 1px solid var(--line-strong) !important;
    border-radius: 0 !important;
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

/* ------- images ------- */
[data-testid="stImage"] img {
    background-color: #fff;
    border: 1px solid var(--line);
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


def section_label(text: str):
    st.markdown(
        f'<div class="section-row">'
        f'<span class="section-label">{text}</span>'
        f'<span class="rule"></span>'
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


def _qr_thumbnail_png(url: str, scale: int = 4) -> bytes:
    """Render a small PNG of the QR for in-UI thumbnails. PNG bytes are the
    safest input for st.image() across all Streamlit versions — passing raw
    SVG bytes can route through PIL on some versions and fail."""
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


def _qr_history_row(entry: dict):
    """Render one history row with thumbnail, label, url, downloads, delete."""
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

    with st.container(border=True):
        col_thumb, col_meta, col_actions = st.columns([1, 5, 4])
        with col_thumb:
            st.image(thumb_png, width=72)
        with col_meta:
            st.markdown(
                f"<div style='font-weight:700; font-size:13px; "
                f"letter-spacing:0.04em;'>{label}</div>"
                f"<div style='font-family:\"Roboto\",sans-serif; "
                f"font-size:11px; color:var(--muted); "
                f"word-break:break-all; margin-top:2px;'>{url}</div>"
                f"<div style='font-family:\"Roboto\",sans-serif; "
                f"font-size:10px; color:var(--muted); margin-top:4px;'>"
                f"{relative_time(ts)}</div>",
                unsafe_allow_html=True,
            )
        with col_actions:
            b_svg, b_pdf, b_eps, b_del = st.columns(4)
            with b_svg:
                st.download_button(
                    "SVG",
                    data=svg,
                    file_name=f"{safe_stem}.svg",
                    mime="image/svg+xml",
                    key=f"qr_h_svg_{eid}",
                )
            with b_pdf:
                try:
                    st.download_button(
                        "PDF",
                        data=_qr_bytes(url, "pdf"),
                        file_name=f"{safe_stem}.pdf",
                        mime="application/pdf",
                        key=f"qr_h_pdf_{eid}",
                    )
                except Exception:
                    st.caption("PDF —")
            with b_eps:
                try:
                    st.download_button(
                        "EPS",
                        data=_qr_bytes(url, "eps"),
                        file_name=f"{safe_stem}.eps",
                        mime="application/postscript",
                        key=f"qr_h_eps_{eid}",
                    )
                except Exception:
                    st.caption("EPS —")
            with b_del:
                if st.button("✕", key=f"qr_h_del_{eid}",
                             help="Remove from history"):
                    remove_qr_history_entry(eid)
                    st.rerun()


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

    section_label("Generate")
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
            placeholder="INS-TENTCARD-TRENTON",
            key=f"qr_label_{nonce}",
            help="A name for this QR — used as the filename and shown in history.",
        )

    spacer("sm")
    col_go, _ = st.columns([2, 9])
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

    spacer("md")
    section_label(f"History · {len(history)}")
    for entry in history:
        _qr_history_row(entry)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main():
    st.set_page_config(
        page_title="QR GENERATOR",
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

    st.markdown('<h1 class="display-title">QR GENERATOR</h1>', unsafe_allow_html=True)
    st.markdown('<hr class="thick-rule">', unsafe_allow_html=True)

    render_qrbuddy()


if __name__ == "__main__":
    main()
