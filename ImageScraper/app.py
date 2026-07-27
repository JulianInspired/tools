from __future__ import annotations

import io
import os
import re
import sys
import time
import zipfile
import hashlib
import subprocess
from pathlib import Path
from urllib.parse import urlparse, urljoin, parse_qsl, urlencode, urlunparse, quote_plus
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests
import streamlit as st
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

DOWNLOAD_DIR = Path("downloads")

AGEWALL_OVERLAY = ".overlay--agewall"
AGEWALL_BODY_CLASS = "agewall-show"
AGEWALL_DOB_MONTH = "#dob__month"
AGEWALL_DOB_DAY = "#dob__day"
AGEWALL_DOB_YEAR = "#dob__year"
AGEWALL_VERIFY = "button[data-to-step='confirm']"

DOB_MONTH = "01"
DOB_DAY = "01"
DOB_YEAR = "1990"

TARGET_SELECTORS = [
    ".product-images.has-product-properties img",
    "img.product-images.has-product-properties",
    "[class~='product-images'][class~='has-product-properties'] img",
]

PRODUCT_LINK_SELECTORS = [
    "a.product-tile__product-link",
    "a[class*='product-tile'][href*='/products/']",
    "a[href*='/products/']",
]

SEARCH_URL_TEMPLATE = "https://ocs.ca/search?q={q}"
MIN_IMAGE_BYTES = 5_000


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def slugify(value: str, fallback: str = "product") -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-_.")
    return value or fallback


def folder_for_url(url: str) -> str:
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return slugify(parsed.netloc or "product")
    return slugify(parts[-1])


def is_url(s: str) -> bool:
    s = s.strip().lower()
    return s.startswith("http://") or s.startswith("https://")


def is_likely_product_image(url: str) -> bool:
    if not url or not url.startswith("http"):
        return False
    lowered = url.lower()
    skip = ["icon", "logo", "sprite", "pixel", "tracker", "tracking",
            "analytics", "1x1", "spacer", "favicon", "loader"]
    if any(k in lowered for k in skip):
        return False
    return True


def upscale_image_url(url: str) -> str:
    new_url = re.sub(
        r"_(?:\d+x\d+|\d+x|x\d+)(\.[A-Za-z0-9]{3,5})",
        r"\1",
        url,
        count=1,
    )
    if "?" in new_url:
        parsed = urlparse(new_url)
        kept = [
            (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
            if k.lower() not in ("width", "height", "crop")
        ]
        new_url = urlunparse(parsed._replace(query=urlencode(kept)))
    return new_url


# ---------------------------------------------------------------------------
# scraping
# ---------------------------------------------------------------------------


def collect_target_images(page) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    for selector in TARGET_SELECTORS:
        try:
            elements = page.query_selector_all(selector)
        except Exception:
            continue

        for el in elements:
            for attr in ["src", "data-src", "data-lazy-src", "data-original",
                         "srcset", "data-srcset"]:
                try:
                    value = el.get_attribute(attr)
                except Exception:
                    value = None
                if not value:
                    continue

                if "srcset" in attr:
                    parts = [p.strip().split(" ")[0] for p in value.split(",") if p.strip()]
                else:
                    parts = [value.strip()]

                for c in parts:
                    abs_url = urljoin(page.url, c)
                    abs_url = upscale_image_url(abs_url)
                    if abs_url in seen:
                        continue
                    if not is_likely_product_image(abs_url):
                        continue
                    seen.add(abs_url)
                    found.append(abs_url)

    return found


def scroll_page(page, passes: int = 6, pause: float = 0.7):
    last_height = 0
    for _ in range(passes):
        page.evaluate("window.scrollBy(0, window.innerHeight)")
        time.sleep(pause)
        height = page.evaluate("document.body.scrollHeight")
        if height == last_height:
            break
        last_height = height
    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(0.3)


def is_agewall_visible(page) -> bool:
    try:
        if page.locator(AGEWALL_OVERLAY).first.is_visible():
            return True
    except Exception:
        pass
    try:
        cls = page.evaluate("document.body.className || ''")
        return AGEWALL_BODY_CLASS in cls
    except Exception:
        return False


def handle_age_gate(page) -> bool:
    try:
        page.wait_for_selector(AGEWALL_DOB_MONTH, timeout=6000)
    except PlaywrightTimeoutError:
        return False

    if not is_agewall_visible(page):
        return False

    try:
        page.click(AGEWALL_DOB_MONTH)
        page.locator(AGEWALL_DOB_MONTH).fill("")
        page.locator(AGEWALL_DOB_MONTH).type(DOB_MONTH, delay=40)

        page.locator(AGEWALL_DOB_DAY).fill("")
        page.locator(AGEWALL_DOB_DAY).type(DOB_DAY, delay=40)

        page.locator(AGEWALL_DOB_YEAR).fill("")
        page.locator(AGEWALL_DOB_YEAR).type(DOB_YEAR, delay=40)

        page.locator(AGEWALL_DOB_YEAR).press("Tab")

        page.wait_for_function(
            """() => {
                const b = document.querySelector("button[data-to-step='confirm']");
                return b && !b.disabled && !b.classList.contains('btn--disabled');
            }""",
            timeout=5000,
        )
        page.locator(AGEWALL_VERIFY).first.click()

        page.wait_for_function(
            """() => {
                const o = document.querySelector('.overlay--agewall');
                const visible = o && o.offsetParent !== null;
                const showing = document.body.classList.contains('agewall-show');
                return !visible && !showing;
            }""",
            timeout=10000,
        )
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except PlaywrightTimeoutError:
            pass
        return True
    except Exception:
        return False


def wait_for_target(page, timeout_ms: int = 8000) -> bool:
    try:
        page.wait_for_selector(TARGET_SELECTORS[0], timeout=timeout_ms)
        return True
    except PlaywrightTimeoutError:
        return False


def resolve_query_to_url(page, query: str, log) -> str | None:
    query = query.strip()
    if not query:
        return None
    if is_url(query):
        return query

    search_url = SEARCH_URL_TEMPLATE.format(q=quote_plus(query))
    log(f"   search '{query}' -> {search_url}")
    try:
        page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
    except PlaywrightTimeoutError:
        log(f"   search timed out for '{query}'")
        return None

    try:
        page.wait_for_load_state("networkidle", timeout=6000)
    except PlaywrightTimeoutError:
        pass

    if is_agewall_visible(page):
        handle_age_gate(page)

    for selector in PRODUCT_LINK_SELECTORS:
        try:
            link = page.locator(selector).first
            href = link.get_attribute("href", timeout=3500)
            if href:
                resolved = urljoin(page.url, href)
                p = urlparse(resolved)
                resolved = urlunparse(p._replace(query="", fragment=""))
                log(f"   resolved '{query}' -> {resolved}")
                return resolved
        except PlaywrightTimeoutError:
            continue
        except Exception:
            continue

    log(f"   no product found for '{query}'")
    return None


def scrape_one(page, url: str, log) -> list[str]:
    log(f"-> {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=45000)

    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except PlaywrightTimeoutError:
        pass

    if is_agewall_visible(page):
        if handle_age_gate(page):
            log("   age gate passed")

    wait_for_target(page, timeout_ms=8000)
    scroll_page(page)
    urls = collect_target_images(page)
    log(f"   found {len(urls)} image(s)")
    return urls


def scrape_queries(queries: list[str], log, progress=None) -> dict[str, list[str]]:
    results: dict[str, list[str]] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1366, "height": 900},
        )
        page = context.new_page()

        try:
            for i, query in enumerate(queries, start=1):
                if progress is not None:
                    progress.progress(i / len(queries),
                                       text=f"Scraping {i}/{len(queries)}")

                product_url = resolve_query_to_url(page, query, log)
                if not product_url:
                    results[query] = []
                    continue

                if product_url in results:
                    log(f"   already scraped {product_url} - skipping duplicate")
                    continue

                try:
                    results[product_url] = scrape_one(page, product_url, log)
                except PlaywrightTimeoutError as e:
                    log(f"   timeout: {e}")
                    results[product_url] = []
                except Exception as e:
                    log(f"   error: {e}")
                    results[product_url] = []
        finally:
            context.close()
            browser.close()

    return results


# ---------------------------------------------------------------------------
# download
# ---------------------------------------------------------------------------


def _filename_for(img_url: str) -> str:
    base = os.path.basename(urlparse(img_url).path) or "image"
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    if "." not in base:
        base += ".jpg"
    stem, ext = os.path.splitext(base)
    digest = hashlib.md5(img_url.encode()).hexdigest()[:8]
    return f"{stem}_{digest}{ext}"


def _fetch_image(img_url: str, referer: str) -> bytes | None:
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": referer,
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }
    r = requests.get(img_url, headers=headers, timeout=20)
    r.raise_for_status()
    content = r.content
    if len(content) < MIN_IMAGE_BYTES:
        return None
    return content


def _build_tasks(results: dict[str, list[str]]):
    tasks = []
    for product_url, image_urls in results.items():
        if not image_urls:
            continue
        folder = folder_for_url(product_url)
        for img_url in image_urls:
            tasks.append((folder, img_url, product_url))
    return tasks


def _worker(folder: str, img_url: str, referer: str):
    try:
        content = _fetch_image(img_url, referer)
    except Exception as e:
        return ("error", folder, img_url, f"{img_url} - {e}", None)
    if content is None:
        return ("error", folder, img_url, f"Too small: {img_url}", None)
    return ("ok", folder, _filename_for(img_url), None, content)


def download_to_disk(
    results: dict[str, list[str]],
    progress=None,
    max_workers: int = 6,
    target_dir: Path | None = None,
) -> tuple[int, list[str]]:
    base = Path(target_dir) if target_dir else DOWNLOAD_DIR
    base.mkdir(parents=True, exist_ok=True)
    saved = 0
    errors: list[str] = []

    tasks = _build_tasks(results)
    total = len(tasks)
    if total == 0:
        return 0, []

    seen_folders: set[str] = set()
    for folder, _, _ in tasks:
        if folder not in seen_folders:
            (base / folder).mkdir(parents=True, exist_ok=True)
            seen_folders.add(folder)

    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(_worker, f, u, r) for f, u, r in tasks]
        for f in as_completed(futures):
            kind, folder, name_or_url, err, content = f.result()
            if kind == "ok":
                (base / folder / name_or_url).write_bytes(content)
                saved += 1
            else:
                errors.append(err)
            done += 1
            if progress is not None:
                progress.progress(done / total, text=f"Downloading {done}/{total}")

    return saved, errors


def build_zip(
    results: dict[str, list[str]],
    progress=None,
    max_workers: int = 6,
) -> bytes:
    tasks = _build_tasks(results)
    total = len(tasks)
    completed: list[tuple[str, str, bytes]] = []

    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(_worker, f, u, r) for f, u, r in tasks]
        for f in as_completed(futures):
            kind, folder, name, _err, content = f.result()
            if kind == "ok":
                completed.append((folder, name, content))
            done += 1
            if progress is not None and total:
                progress.progress(done / total, text=f"Downloading {done}/{total}")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for folder, name, content in completed:
            z.writestr(f"{folder}/{name}", content)
    buf.seek(0)
    return buf.read()


# ---------------------------------------------------------------------------
# file / spreadsheet input
# ---------------------------------------------------------------------------


def read_uploaded_table(uploaded) -> pd.DataFrame:
    name = uploaded.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(uploaded)
    if name.endswith(".xlsx") or name.endswith(".xls"):
        return pd.read_excel(uploaded)
    raise ValueError("Unsupported file type. Use CSV or XLSX.")


def guess_query_column(df: pd.DataFrame) -> str:
    for col in df.columns:
        if re.search(r"url|link|product|name|sku|title", str(col), re.I):
            return col
    return df.columns[0]


def dedupe_queries(queries: list[str]) -> list[str]:
    """Drop duplicates ignoring case, whitespace, and URL trailing slashes /
    query strings. Keeps the first occurrence."""
    seen: set[str] = set()
    out: list[str] = []
    for q in queries:
        q = (q or "").strip()
        if not q:
            continue
        norm = re.sub(r"\s+", " ", q.lower())
        if is_url(norm):
            p = urlparse(norm)
            norm = urlunparse(p._replace(query="", fragment="")).rstrip("/")
        if norm in seen:
            continue
        seen.add(norm)
        out.append(q)
    return out


def extract_queries_from_df(df: pd.DataFrame, column: str) -> tuple[list[str], int]:
    """Returns (unique_queries, raw_row_count). Duplicates are dropped."""
    series = df[column].dropna().astype(str).str.strip()
    series = series[series != ""]
    raw = list(series)
    return dedupe_queries(raw), len(raw)


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


def init_state():
    st.session_state.setdefault("results", {})
    st.session_state.setdefault("logs", [])
    st.session_state.setdefault("missing", [])
    st.session_state.setdefault("uploader_key", 0)
    st.session_state.setdefault("save_dir", str(DOWNLOAD_DIR.resolve()))


def clear_queue(also_text: bool = False, also_uploader: bool = False):
    st.session_state.results = {}
    st.session_state.logs = []
    st.session_state.missing = []
    if also_text:
        st.session_state["text_inputs"] = ""
    if also_uploader:
        st.session_state.uploader_key += 1


def pick_folder(initial: str | None = None) -> str | None:
    """Open the macOS native folder picker via osascript.

    Tk's askdirectory crashes Python when called from a Streamlit worker
    thread (Cocoa requires the main thread). osascript runs in its own
    process, so it sidesteps the issue entirely.
    """
    if sys.platform != "darwin":
        return None

    initial_path = Path(initial).expanduser() if initial else Path.cwd()
    if not initial_path.exists():
        initial_path = Path.cwd()
    safe = str(initial_path).replace("\\", "\\\\").replace('"', '\\"')

    script = (
        'try\n'
        '  set chosenFolder to choose folder with prompt '
        '"Choose folder to save images" '
        f'default location POSIX file "{safe}"\n'
        '  return POSIX path of chosenFolder\n'
        'on error\n'
        '  return ""\n'
        'end try'
    )

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return None

    if result.returncode != 0:
        return None
    chosen = result.stdout.strip()
    return chosen or None


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


def render_results():
    results = st.session_state.results
    missing = st.session_state.get("missing", [])

    if not results and not missing:
        return

    total_imgs = sum(len(v) for v in results.values())
    products_with_images = sum(1 for v in results.values() if v)

    section_label("Results")

    c1, c2, c3 = st.columns(3)
    c1.metric("Products", len(results))
    c2.metric("With images", products_with_images)
    c3.metric("Total images", total_imgs)

    if missing:
        with st.expander(f"{len(missing)} input(s) couldn't be resolved"):
            for q in missing:
                st.write(f"— {q}")

    if total_imgs == 0:
        st.warning("No images matched the target selector on any page.")
        return

    spacer("md")

    section_label("Save to")
    typed_dir = st.text_input(
        "Save folder",
        value=st.session_state.save_dir,
        label_visibility="collapsed",
        key="save_dir_input",
    )
    st.session_state.save_dir = typed_dir

    spacer("sm")

    col_a, col_b, _spacer, col_browse = st.columns([2, 2, 5, 2])
    with col_a:
        save_clicked = st.button(
            f"Save {total_imgs} to disk",
            type="primary",
            key="save_disk",
        )
    with col_b:
        zip_clicked = st.button("Build ZIP", key="build_zip")
    with col_browse:
        if st.button("Browse", key="browse_dir", help="Choose folder…"):
            chosen = pick_folder(st.session_state.save_dir)
            if chosen:
                st.session_state.save_dir = chosen
                st.rerun()
            else:
                st.toast("Folder picker unavailable or cancelled.")

    if save_clicked:
        target = Path(st.session_state.save_dir).expanduser()
        progress = st.progress(0.0, text=f"Downloading 0/{total_imgs}")
        t0 = time.time()
        with st.spinner("Downloading…"):
            try:
                saved, errors = download_to_disk(
                    results, progress=progress, target_dir=target
                )
            except Exception as e:
                progress.empty()
                st.error(f"Could not save to {target}: {e}")
                return
        progress.empty()
        st.success(
            f"Saved {saved} file(s) to {target.resolve()} "
            f"in {time.time() - t0:.1f}s"
        )
        if errors:
            with st.expander(f"{len(errors)} issue(s)"):
                for e in errors:
                    st.write(f"— {e}")

    if zip_clicked:
        progress = st.progress(0.0, text=f"Downloading 0/{total_imgs}")
        with st.spinner("Packaging ZIP…"):
            data = build_zip(results, progress=progress)
        progress.empty()
        st.download_button(
            "Download images.zip",
            data=data,
            file_name="images.zip",
            mime="application/zip",
        )

    spacer("md")

    for product_url, image_urls in results.items():
        with st.expander(
            f"{folder_for_url(product_url)} — {len(image_urls)} image(s)"
        ):
            st.caption(product_url)
            if not image_urls:
                st.info("No matching images found.")
                continue
            cols = st.columns(3)
            for i, img_url in enumerate(image_urls):
                with cols[i % 3]:
                    try:
                        st.image(
                            img_url,
                            use_container_width=True,
                            caption=os.path.basename(urlparse(img_url).path),
                        )
                    except Exception:
                        st.write(img_url)


def render_log():
    if not st.session_state.logs:
        return
    section_label("Activity log")
    with st.expander("View log", expanded=False):
        st.code("\n".join(st.session_state.logs), language="text")


def run_scrape(queries: list[str]):
    st.session_state.logs = []
    log_box = st.empty()

    def log(msg: str):
        st.session_state.logs.append(msg)
        log_box.code("\n".join(st.session_state.logs[-14:]), language="text")

    progress = st.progress(0.0, text=f"Scraping 0/{len(queries)}")
    try:
        results = scrape_queries(queries, log=log, progress=progress)
    except Exception as e:
        progress.empty()
        st.error(f"Scraping failed: {e}")
        return

    progress.empty()
    st.session_state.results = {k: v for k, v in results.items() if is_url(k)}
    st.session_state.missing = [k for k in results if not is_url(k)]


def render_ocs_scraper():
    """OCS product image scraper — original tool."""
    st.markdown(
        '<p class="display-sub">'
        'Targets <code>.product-images.has-product-properties</code> · '
        'Accepts URLs, names, or a spreadsheet'
        '</p>',
        unsafe_allow_html=True,
    )

    tab_text, tab_bulk = st.tabs(["URLs / Names", "Bulk CSV / XLSX"])

    with tab_text:
        section_label("Input")
        st.markdown(
            "Paste **product URLs**, **names**, or a mix — one per line. "
            "Names are resolved through OCS search."
        )
        raw = st.text_area(
            "Inputs",
            placeholder=(
                "Cherry OG\n"
                "https://ocs.ca/products/blue-dream-broken-coast-blue-dream-blueberry-x-haze\n"
                "Pink Kush"
            ),
            height=200,
            label_visibility="collapsed",
            key="text_inputs",
        )
        col_run, col_clear, _ = st.columns([1, 1, 18], gap="small")
        start_text = col_run.button(
            "▶", type="primary", key="start_text", help="Start scraping"
        )
        clear_text = col_clear.button(
            "✕", key="clear_text", help="Clear queue"
        )

        if start_text:
            queries = dedupe_queries(raw.splitlines())
            if not queries:
                st.error("Please enter at least one URL or product name.")
            else:
                run_scrape(queries)
        if clear_text:
            clear_queue(also_text=True)
            st.rerun()

    with tab_bulk:
        section_label("File upload")
        uploaded = st.file_uploader(
            "Upload a CSV or Excel file. URLs or product names both work.",
            type=["csv", "xlsx", "xls"],
            label_visibility="collapsed",
            key=f"uploader_{st.session_state.uploader_key}",
        )

        if uploaded is not None:
            try:
                df = read_uploaded_table(uploaded)
            except Exception as e:
                st.error(f"Could not read file: {e}")
                df = None

            if df is not None and not df.empty:
                section_label(f"Preview · {len(df)} row(s)")
                st.dataframe(df.head(10), use_container_width=True)

                default_col = guess_query_column(df)
                col_pick, col_lim = st.columns([3, 2])
                with col_pick:
                    col = st.selectbox(
                        "Query column",
                        options=list(df.columns),
                        index=list(df.columns).index(default_col),
                    )
                queries, raw_count = extract_queries_from_df(df, col)
                with col_lim:
                    limit = st.number_input(
                        "Max entries (0 = all)",
                        min_value=0,
                        max_value=max(len(queries), 1),
                        value=min(len(queries), 25),
                    )

                dropped = raw_count - len(queries)
                if dropped:
                    st.info(
                        f"Found {len(queries)} unique entry(s) in column `{col}` "
                        f"({dropped} duplicate(s) ignored)."
                    )
                else:
                    st.info(f"Found {len(queries)} entry(s) in column `{col}`.")

                col_run, col_clear, _ = st.columns([1, 1, 18], gap="small")
                start_bulk = col_run.button(
                    "▶", type="primary", key="start_bulk", help="Start scraping"
                )
                clear_bulk = col_clear.button(
                    "✕", key="clear_bulk", help="Clear queue"
                )

                if start_bulk:
                    target = queries if limit == 0 else queries[:int(limit)]
                    if not target:
                        st.error("No valid entries to scrape.")
                    else:
                        run_scrape(target)
                if clear_bulk:
                    clear_queue(also_uploader=True)
                    st.rerun()

    render_results()
    render_log()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main():
    st.set_page_config(
        page_title="IMAGE SCRAPER",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st.markdown(PAGE_CSS, unsafe_allow_html=True)
    init_state()

    # top nav-style strip
    st.markdown(
        '<div class="top-bar">'
        '<div class="left">'
        '<span>IMAGE SCRAPER</span>'
        '<span class="top-bar-tag">House of Brands · tool module</span>'
        '</div>'
        '<div class="right">'
        '<span>v0.2</span>'
        '<span>Streamlit</span>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # display headline
    st.markdown(
        '<h1 class="display-title">IMAGE SCRAPER</h1>',
        unsafe_allow_html=True,
    )
    st.markdown('<hr class="thick-rule">', unsafe_allow_html=True)

    render_ocs_scraper()


if __name__ == "__main__":
    main()
