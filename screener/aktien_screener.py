# -*- coding: utf-8 -*-
"""
Aktien-Screener: Technik (RSI + MACD) UND Fundamentaldaten (KGV sinkend, EPS steigend) für 101 ISINs.

START (Windows, einmalig installieren):
    py -m pip install pandas numpy yfinance playwright beautifulsoup4
    py -m playwright install chromium
START:
    py aktien_screener.py                      # Technik lokal berechnet (empfohlen), Fundamentaldaten von Finanzen.net
    py aktien_screener.py --technik stock3     # Technik von Stock3 lesen (nur nach Konfiguration, siehe unten)
    py aktien_screener.py --sichtbar           # Browserfenster anzeigen (gut zum Fehlersuchen)
    py aktien_screener.py --limit 5            # nur die ersten 5 ISINs testen

WICHTIGE HINWEISE (bitte lesen):
 * Dieses Skript wurde OHNE Internetzugang geschrieben. Die Auswertungslogik (RSI, MACD, Trendregeln, Zahlenparser,
   ISIN-Prüfsumme) ist getestet. Die Selektoren/URLs für Finanzen.net und Stock3 sind NICHT gegen die Live-Seiten
   getestet, weil Webseiten ihr Layout ändern. Sie stehen oben in der KONFIGURATION, damit du sie leicht anpassen kannst.
 * Prüfe die Nutzungsbedingungen (AGB) von Stock3 und Finanzen.net, bevor du automatisiert abrufst. Das Skript wartet
   zwischen den Abrufen und ruft nichts parallel ab.
 * Technik "lokal": RSI(14) und MACD(12,26,9) werden aus Tageskursen (Yahoo) berechnet – das sind dieselben Standard-
   Indikatoren, die Stock3 anzeigt, nur zuverlässiger, als Zahlen aus einem Chart-Bild abzulesen.
"""
from __future__ import annotations
import argparse, json, random, re, sys, time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

# ----------------------------------------------------------------------------------------------------------------
# KONFIGURATION
# ----------------------------------------------------------------------------------------------------------------
ISINS = [
    "US00724F1012", "US0090661010", "US02043Q1076", "US02079K1079", "US02079K3059", "US0231351067", "US0079031078", "US0255371017",
    "US0311621009", "US0326541051", "US0378331005", "US0382221051", "US03831W1080", "US0420682058", "USN070592100", "US04626A1034",
    "US0527691069", "US0530151036", "US05464C1018", "US05722G1004", "US09857L1089", "US11135F1012", "US1273871087", "US1729081059",
    "US17275R1023", "GB00BDCPN049", "US20030N1019", "US21037T1097", "US2172041061", "US21873S1087", "US22160K1051", "US22788C1053",
    "US1264081035", "US23804L1035", "US2521311074", "US25278X1090", "US25809K1051", "US2855121099", "US30161N1019", "US3119001044",
    "NL0015001FS8", "US34959E1091", "US36266G1076", "US3755581036", "US4385161066", "US45168D1046", "US4581401001", "US4612021034",
    "US46120E6023", "US49271V1008", "US4824801009", "US5007541064", "US5128073062", "IE000S9YS762", "US55024U1097", "US5719032022",
    "US5738741041", "US58733R1023", "US30303M1027", "US5950171042", "US5951121038", "US5949181045", "US6092071058", "US6098391054",
    "US61174X1090", "NL0009805522", "US64110L1061", "US67066G1040", "NL0009538784", "US67103H1077", "US6795801009", "US6937181088",
    "US69608A1088", "US6974351057", "US7043261079", "US70450Y1038", "US7134481081", "US7223041028", "US7475251036", "US75886F1075",
    "US7731211089", "US7766961061", "US7782961038", "US80004C2008", "IE00BKVD2N49", "CA82509L1076", "US8552441094", "US5949724083",
    "US8716071076", "US8725901040", "US8740541094", "US8807701029", "US88160R1014", "US8825081040", "CA8849038085", "US92532F1003",
    "US9311421039", "US9344231041", "US9581021055", "US98138H1014", "US98389B1008",
]

# --- Technische Regeln ---
RSI_PERIOD, MACD_FAST, MACD_SLOW, MACD_SIGNAL = 14, 12, 26, 9
RSI_OVERSOLD = 30
RSI_RECENT_BARS = 5        # "kürzlich die 30 nach oben durchbrochen" = innerhalb der letzten 5 Handelstage
MACD_RECENT_BARS = 3       # "Bullish Crossover" = innerhalb der letzten 3 Handelstage
CHART_MONTHS = 6           # Betrachtungszeitraum (6-Monats-Chart)

# --- Finanzen.net (NICHT live getestet – bei Bedarf anpassen) ---
# Die Suche per ISIN leitet normalerweise auf die Aktienseite weiter. Falls nicht: Muster hier ändern.
FINANZEN_SEARCH_URL = "https://www.finanzen.net/suchergebnis.asp?frmAktiensucheTextfeld={isin}"
COOKIE_BUTTON_TEXT = re.compile(r"(alle akzeptieren|akzeptieren|zustimmen|einverstanden|accept all|agree)", re.I)
EPS_LABEL = re.compile(r"^\s*(gewinn\s*/?\s*aktie|ergebnis\s*je\s*aktie|eps)", re.I)
KGV_LABEL = re.compile(r"^\s*kgv", re.I)

# --- Stock3 (nur für --technik stock3) ---
# Trage hier das URL-Muster der Chart-Seite ein (z. B. aus deinem Browser kopieren, ISIN durch {isin} ersetzen).
STOCK3_URL_TEMPLATE = ""

# Manuelle Zuordnung ISIN -> Yahoo-Ticker für Fälle, die die Yahoo-Suche nicht findet (jederzeit ergänzbar).
TICKER_OVERRIDES = {"US02079K3059": "GOOGL", "CA8849038085": "TRI"}
US_EXCHANGES = {"NMS", "NGM", "NCM", "NYQ", "ASE", "PCX", "BTS", "NAS", "NYS"}   # bevorzugte US-Börsen bei Yahoo

PAUSE_SECONDS = (2.5, 5.0)  # zufällige Wartezeit zwischen zwei Aktien (höflich gegenüber den Webseiten)
CACHE_FILE = Path("screener_cache.json")   # speichert Zwischenergebnisse: bei Abbruch einfach neu starten


# ----------------------------------------------------------------------------------------------------------------
# HILFSFUNKTIONEN: ISIN, Zahlen
# ----------------------------------------------------------------------------------------------------------------
def isin_is_valid(isin: str) -> bool:
    """Formal prüfen: 12 Zeichen, Länderkürzel + Prüfziffer (Luhn). Eine ungültige ISIN kann nie gefunden werden."""
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", isin):
        return False
    digits = "".join(str(int(c, 36)) for c in isin)          # Buchstaben A=10 ... Z=35
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            d = d - 9 if d > 9 else d
        total += d
    return total % 10 == 0


def parse_de_number(text: str) -> float | None:
    """'1.234,56' -> 1234.56 ; '-', '–', 'n.a.' -> None."""
    t = (text or "").strip().replace("\xa0", " ")
    m = re.search(r"-?\d[\d.\s]*(?:,\d+)?|-?\d+(?:\.\d+)?", t)
    if not m or t in {"-", "–", "—", "n.a.", "k.A."}:
        return None
    s = m.group(0).replace(" ", "")
    s = s.replace(".", "").replace(",", ".") if "," in s else s
    try:
        return float(s)
    except ValueError:
        return None


# ----------------------------------------------------------------------------------------------------------------
# TECHNIK: RSI (Wilder) und MACD – identisch zu den im Hauptprojekt gegen Referenzwerte getesteten Funktionen
# ----------------------------------------------------------------------------------------------------------------
def rsi_wilder(close: pd.Series, period: int = 14) -> pd.Series:
    c = close.to_numpy(float)
    out = np.full(len(c), np.nan)
    if len(c) <= period:
        return pd.Series(out, index=close.index)
    d = np.diff(c)
    gain, loss = np.where(d > 0, d, 0.0), np.where(d < 0, -d, 0.0)
    ag, al = gain[:period].mean(), loss[:period].mean()
    for i in range(period, len(c)):
        if i > period:
            ag = (ag * (period - 1) + gain[i - 1]) / period
            al = (al * (period - 1) + loss[i - 1]) / period
        out[i] = 100.0 if al == 0 and ag > 0 else (50.0 if al == 0 else 100 - 100 / (1 + ag / al))
    return pd.Series(out, index=close.index)


def macd_lines(close: pd.Series, fast=12, slow=26, signal=9) -> pd.DataFrame:
    line = close.ewm(span=fast, adjust=False).mean() - close.ewm(span=slow, adjust=False).mean()
    sig = line.ewm(span=signal, adjust=False).mean()
    out = pd.DataFrame({"macd": line, "signal": sig})
    out.iloc[: slow - 1] = np.nan
    return out


def evaluate_technicals(close: pd.Series) -> dict:
    """Regeln: Kauf-RSI = RSI<30 ODER RSI hat in den letzten N Tagen die 30 nach oben durchbrochen.
               Kauf-MACD = MACD-Linie kreuzt die Signallinie in den letzten M Tagen von unten nach oben."""
    r = rsi_wilder(close, RSI_PERIOD)
    m = macd_lines(close, MACD_FAST, MACD_SLOW, MACD_SIGNAL).dropna()
    if r.dropna().empty or len(m) < 5:
        return {"tech_ok": False, "fehler": "zu wenig Kursdaten"}
    rsi_now = float(r.iloc[-1])
    crossed30 = ((r.shift(1) < RSI_OVERSOLD) & (r >= RSI_OVERSOLD)).iloc[-RSI_RECENT_BARS:].any()
    rsi_ok = bool(rsi_now < RSI_OVERSOLD or crossed30)
    cross_up = ((m["macd"] > m["signal"]) & (m["macd"].shift(1) <= m["signal"].shift(1)))
    macd_ok = bool(cross_up.iloc[-MACD_RECENT_BARS:].any())
    return {"rsi": round(rsi_now, 1), "rsi_ok": rsi_ok, "rsi_info": "unter 30" if rsi_now < RSI_OVERSOLD else ("30er-Marke kürzlich nach oben durchbrochen" if crossed30 else "kein Signal"),
            "macd": round(float(m["macd"].iloc[-1]), 4), "macd_signal": round(float(m["signal"].iloc[-1]), 4),
            "macd_ok": macd_ok, "macd_info": "Bullish Crossover" if macd_ok else ("MACD über Signal" if m["macd"].iloc[-1] > m["signal"].iloc[-1] else "MACD unter Signal"),
            "tech_ok": rsi_ok and macd_ok}


def pick_symbol(quotes: list) -> str | None:
    """Wählt aus den Yahoo-Suchtreffern bevorzugt die Aktie an einer US-Börse (statt z. B. Stuttgart/Amsterdam)."""
    eq = [q for q in quotes if q.get("symbol") and q.get("quoteType", "EQUITY") == "EQUITY"] or [q for q in quotes if q.get("symbol")]
    us = [q for q in eq if q.get("exchange") in US_EXCHANGES and "." not in q["symbol"]]
    for group in (us, eq):
        if group:
            return group[0]["symbol"]
    return None


def resolve_ticker(isin: str) -> str | None:
    if isin in TICKER_OVERRIDES:
        return TICKER_OVERRIDES[isin]
    import yfinance as yf
    return pick_symbol(yf.Search(isin, max_results=8).quotes)


def technicals_local(isin: str) -> dict:
    """ISIN -> Yahoo-Ticker -> Tageskurse -> RSI/MACD. Der 6-Monats-Zeitraum wird für die Auswertung genutzt,
    zusätzlich wird 1 Jahr geladen, damit RSI/EMA sauber eingeschwungen sind."""
    import yfinance as yf
    try:
        sym = resolve_ticker(isin)
    except Exception as exc:
        return {"tech_ok": False, "fehler": f"ISIN-Suche bei Yahoo fehlgeschlagen: {exc}"}
    if not sym:
        return {"tech_ok": False, "fehler": "ISIN bei Yahoo nicht gefunden (ggf. Ticker manuell zuordnen oder Aktie nicht mehr börsennotiert)"}
    df = yf.download(sym, period="1y", interval="1d", auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if df is None or df.empty or "Close" not in df:
        return {"tech_ok": False, "fehler": f"keine Kursdaten für {sym}", "ticker": sym}
    res = evaluate_technicals(df["Close"].dropna())
    res["ticker"] = sym
    res["kurs"] = float(df["Close"].dropna().iloc[-1])
    res["letzte_kerze"] = str(df.index[-1])[:10]
    return res


# ----------------------------------------------------------------------------------------------------------------
# FUNDAMENTAL: Finanzen.net (Playwright lädt die Seite, BeautifulSoup liest die Tabellen)
# ----------------------------------------------------------------------------------------------------------------
def parse_fundamentals(html: str) -> dict:
    """Sucht Tabellenzeilen 'Gewinn/Aktie' und 'KGV' samt Jahres-Kopfzeile. Gibt {'eps': {jahr: wert}, 'kgv': {...}} zurück.
    Es werden nur Werte übernommen, die tatsächlich auf der Seite stehen (sonst Daten nicht verfügbar)."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    out = {"eps": {}, "kgv": {}}
    for table in soup.find_all("table"):
        rows = [[c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])] for tr in table.find_all("tr")]
        years = None
        for cells in rows:                                           # Kopfzeile mit mindestens 3 Jahreszahlen
            ys = [re.search(r"(20\d\d|19\d\d)", c) for c in cells]
            ys = [int(m.group(1)) for m in ys if m]
            if len(ys) >= 3:
                years = ys; break
        if not years:
            continue
        for cells in rows:
            if not cells:
                continue
            key = "eps" if EPS_LABEL.match(cells[0]) else "kgv" if KGV_LABEL.match(cells[0]) else None
            if key and not out[key]:
                vals = [parse_de_number(c) for c in cells[1:]]
                vals = vals[-len(years):] if len(vals) >= len(years) else vals
                out[key] = {y: v for y, v in zip(years[:len(vals)], vals) if v is not None}
    return out


def evaluate_fundamentals(data: dict, now_year: int | None = None) -> dict:
    """KGV muss sinken, EPS muss steigen: Durchschnitt (aktuelles + zukünftige Jahre) gegen Durchschnitt (vergangene Jahre).
    Nicht aussagekräftige KGVs (<= 0) werden ignoriert."""
    y0 = now_year or datetime.now().year
    def split(series, positive_only=False):
        s = {y: v for y, v in series.items() if (v > 0 or not positive_only)}
        past = [v for y, v in s.items() if y < y0]; fut = [v for y, v in s.items() if y >= y0]
        return past, fut
    ep, ef = split(data.get("eps", {})); kp, kf = split(data.get("kgv", {}), positive_only=True)
    res = {"eps_info": "Daten nicht verfügbar", "kgv_info": "Daten nicht verfügbar", "eps_ok": False, "kgv_ok": False}
    if len(ep) >= 2 and ef:
        a, b = float(np.mean(ep)), float(np.mean(ef)); res["eps_ok"] = b > a
        res["eps_info"] = f"Ø früher {a:.2f} → Ø aktuell/Prognose {b:.2f}"
    if len(kp) >= 2 and kf:
        a, b = float(np.mean(kp)), float(np.mean(kf)); res["kgv_ok"] = b < a
        res["kgv_info"] = f"Ø früher {a:.1f} → Ø aktuell/Prognose {b:.1f}"
    res["fund_ok"] = res["eps_ok"] and res["kgv_ok"]
    return res


def close_cookie_banner(page) -> None:
    """Versucht, ein Cookie-Banner (auch in iFrames) zu schließen. Fehler werden bewusst ignoriert."""
    for frame in [page] + list(page.frames):
        try:
            btn = frame.get_by_role("button", name=COOKIE_BUTTON_TEXT).first
            if btn.is_visible(timeout=1500):
                btn.click(timeout=2000); page.wait_for_timeout(800); return
        except Exception:
            continue


def fundamentals_finanzen(page, isin: str) -> dict:
    page.goto(FINANZEN_SEARCH_URL.format(isin=isin), wait_until="domcontentloaded", timeout=45000)
    close_cookie_banner(page)
    try:
        page.wait_for_load_state("networkidle", timeout=15000)       # dynamische Inhalte fertig laden lassen
    except Exception:
        pass
    html = page.content()
    if isin not in html.replace(" ", ""):
        pass                                                         # ISIN muss nicht im Text stehen; Parser entscheidet
    data = parse_fundamentals(html)
    if not data["eps"] and not data["kgv"]:
        return {"fund_ok": False, "fehler": "keine Kennzahlen-Tabelle gefunden (Seite/Selektor prüfen)", "url": page.url}
    res = evaluate_fundamentals(data); res["url"] = page.url
    return res


def fundamentals_requests(isin: str, timeout: int = 25) -> dict:
    """Wie fundamentals_finanzen, aber OHNE Browser (einfacher HTTP-Abruf). Genutzt von der Webseiten-Version, weil das
    auch auf Servern (z. B. Streamlit Cloud) ohne installierten Browser läuft. Funktioniert nur, wenn Finanzen.net die
    Kennzahlen bereits im HTML ausliefert (nicht live getestet) und den Abruf nicht blockiert."""
    import requests
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
               "Accept-Language": "de-DE,de;q=0.9", "Accept": "text/html,application/xhtml+xml"}
    r = requests.get(FINANZEN_SEARCH_URL.format(isin=isin), headers=headers, timeout=timeout, allow_redirects=True)
    if r.status_code != 200:
        return {"fund_ok": False, "fehler": f"Finanzen.net antwortet mit HTTP {r.status_code} (Abruf evtl. blockiert)", "url": r.url}
    data = parse_fundamentals(r.text)
    if not data["eps"] and not data["kgv"]:
        return {"fund_ok": False, "fehler": "keine Kennzahlen-Tabelle gefunden (Seite/Selektor prüfen)", "url": r.url}
    res = evaluate_fundamentals(data); res["url"] = r.url
    return res


def parse_en_number(text: str) -> float | None:
    """Englisches Zahlenformat: '1,234.56', '8.83', '$5', '12%', '416.16B' -> float. '-', 'Upgrade', 'Pro' -> None."""
    t = (text or "").strip().replace("\xa0", " ")
    if t in {"", "-", "–", "—", "n/a", "N/A", "Upgrade", "Pro"}:
        return None
    m = re.fullmatch(r"\(?(-?)\$?([\d,]*\.?\d+)\s*([KMBT%x]?)\)?", t)
    if not m:
        return None
    val = float(m.group(2).replace(",", ""))
    val *= {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}.get(m.group(3), 1)
    return -val if m.group(1) else val


def parse_stockanalysis(fin_html: str, fc_html: str) -> dict:
    """Liest StockAnalysis.com: Tabellen 'Earnings Per Share' und 'PE Ratio' (Jahresspalten 'FY 2025' ...) aus der
    Financials-Übersicht und die Karten 'EPS This Year' / 'EPS Next Year' aus der Forecast-Seite.
    Gibt {'eps': {...}, 'kgv': {...}, 'last_fy': int, 'eps_this': x, 'eps_next': y} zurück (leer, wenn nichts gefunden)."""
    from bs4 import BeautifulSoup
    out = {"eps": {}, "kgv": {}}
    soup = BeautifulSoup(fin_html, "html.parser")
    for table in soup.find_all("table"):
        rows = [[c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])] for tr in table.find_all("tr")]
        years = None
        for cells in rows:
            ys = [re.search(r"FY\s*(20\d\d)", c) for c in cells]
            ys = [int(m.group(1)) for m in ys if m]
            if len(ys) >= 3:
                years = ys; break
        if not years:
            continue
        for cells in rows:
            if not cells: continue
            label = cells[0]
            key = "eps" if label.lower().startswith("earnings per share") else "kgv" if re.match(r"^PE Ratio\b", label) else None
            if key and not out[key]:
                vals = [parse_en_number(c) for c in cells[1:]]
                vals = vals[-len(years):]                     # die Jahresspalten stehen am Ende (davor TTM/Current)
                out[key] = {y: v for y, v in zip(years, vals) if v is not None}
    if out["eps"]:
        out["last_fy"] = max(out["eps"])
    text = BeautifulSoup(fc_html, "html.parser").get_text(" ", strip=True)
    for key, label in (("eps_this", "EPS This Year"), ("eps_next", "EPS Next Year")):
        m = re.search(label + r"\s+(-?[\d,]*\.?\d+)", text)
        out[key] = parse_en_number(m.group(1)) if m else None
    return out


def fundamentals_stockanalysis(sym: str, price: float | None = None, timeout: int = 25) -> dict:
    """Ersatzquelle StockAnalysis.com (nur US-Ticker): vergangene EPS und KGV aus den Jahresabschlüssen, EPS-Schätzungen für das
    laufende und nächste Geschäftsjahr. KGV der Prognosejahre = aktueller Kurs / geschätztes EPS (wenn der Kurs bekannt ist).
    Hinweis: Prognosen können bereinigt (non-GAAP) sein, historische Werte sind GAAP."""
    import requests
    if "." in sym or not re.fullmatch(r"[A-Za-z]{1,6}", sym):
        return {"fund_ok": False, "fehler": f"StockAnalysis: Ticker {sym} nicht unterstützt (nur US-Ticker ohne Börsen-Endung)"}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
               "Accept-Language": "en-US,en;q=0.9"}
    base = f"https://stockanalysis.com/stocks/{sym.lower()}"
    pages = []
    for suffix in ("/financials/", "/forecast/"):
        r = requests.get(base + suffix, headers=headers, timeout=timeout)
        if r.status_code != 200:
            return {"fund_ok": False, "fehler": f"StockAnalysis antwortet mit HTTP {r.status_code} für {sym}"}
        pages.append(r.text)
    d = parse_stockanalysis(*pages)
    if not d["eps"]:
        return {"fund_ok": False, "fehler": "StockAnalysis: keine EPS-Tabelle gefunden"}
    last = d["last_fy"]
    eps, kgv = dict(d["eps"]), dict(d["kgv"])
    for key, y in (("eps_this", last + 1), ("eps_next", last + 2)):
        e = d.get(key)
        if e is not None:
            eps[y] = e
            if price and e > 0:
                kgv[y] = price / e
    if not any(y > last for y in eps):
        return {"fund_ok": False, "fehler": "StockAnalysis: keine Gewinnschätzungen verfügbar"}
    res = evaluate_fundamentals({"eps": eps, "kgv": kgv}, now_year=last + 1)
    res["quelle"] = "StockAnalysis.com"
    return res


def fundamentals_yahoo(sym: str) -> dict:
    """Ersatzquelle, wenn Finanzen.net den Abruf blockiert: EPS-Historie (Jahresabschlüsse) und Analystenschätzungen
    von Yahoo. KGV wird BERECHNET: vergangene Jahre = Kurs am Geschäftsjahresende / EPS, Prognosejahre = aktueller Kurs /
    geschätztes EPS. Daten, die fehlen, werden nicht ergänzt."""
    import yfinance as yf
    t = yf.Ticker(sym)
    try:
        inc = t.income_stmt
    except Exception as exc:
        return {"fund_ok": False, "fehler": f"Yahoo: Gewinnhistorie nicht ladbar ({exc})"}
    if inc is None or inc.empty:
        return {"fund_ok": False, "fehler": "Yahoo: keine Gewinnhistorie (EPS) verfügbar"}
    name = next((n for n in ("Diluted EPS", "Basic EPS") if n in inc.index), None)
    if name is None:
        return {"fund_ok": False, "fehler": "Yahoo: Zeile 'EPS' in den Jahreszahlen nicht vorhanden"}
    eps_hist = inc.loc[name].dropna()
    if len(eps_hist) < 2:
        return {"fund_ok": False, "fehler": "Yahoo: weniger als 2 Jahre EPS-Historie"}
    hist = t.history(period="6y", auto_adjust=False)["Close"].dropna()
    if getattr(hist.index, "tz", None) is not None:
        hist.index = hist.index.tz_localize(None)
    if hist.empty:
        return {"fund_ok": False, "fehler": "Yahoo: keine Kurshistorie für KGV-Berechnung"}
    eps, kgv = {}, {}
    for ts, val in eps_hist.items():
        ts = pd.Timestamp(ts).tz_localize(None) if getattr(pd.Timestamp(ts), "tzinfo", None) else pd.Timestamp(ts)
        eps[ts.year] = float(val)
        px = hist[hist.index <= ts]
        if len(px) and val > 0:
            kgv[ts.year] = float(px.iloc[-1]) / float(val)
    last_year = max(eps)
    price = float(hist.iloc[-1])
    try:
        est = t.get_earnings_estimate()
    except Exception:
        est = None
    if est is not None and not est.empty and "avg" in est.columns:
        for key, y in (("0y", last_year + 1), ("+1y", last_year + 2)):
            if key in est.index and pd.notna(est.loc[key, "avg"]):
                e = float(est.loc[key, "avg"]); eps[y] = e
                if e > 0: kgv[y] = price / e
    if not any(y > last_year for y in eps):
        return {"fund_ok": False, "fehler": "Yahoo: keine Gewinnschätzungen (Analysten) verfügbar"}
    res = evaluate_fundamentals({"eps": eps, "kgv": kgv}, now_year=last_year + 1)
    res["quelle"] = "Yahoo (berechnet)"
    pos = [v for _, v in sorted(eps.items()) if v > 0]
    if any(b / a > 4 or b / a < 0.25 for a, b in zip(pos, pos[1:])):
        res["fehler"] = "Hinweis: sehr starke EPS-Sprünge (evtl. Aktiensplit/Sondereffekt) – Ergebnis prüfen"
    return res


_FINANZEN_FAIL_STREAK = 0     # nach 3 Fehlschlägen in Folge wird Finanzen.net für den Rest des Laufs übersprungen


def reset_finanzen_block() -> None:
    global _FINANZEN_FAIL_STREAK
    _FINANZEN_FAIL_STREAK = 0


def screen_isin(isin: str, with_fundamentals: bool = True, source: str = "auto") -> dict:
    """Komplette Prüfung EINER ISIN. source: 'auto' (Finanzen.net, dann StockAnalysis, dann Yahoo), 'finanzen', 'stockanalysis' oder 'yahoo'."""
    global _FINANZEN_FAIL_STREAK
    row = {"isin": isin}
    if not isin_is_valid(isin):
        row.update({"tech_ok": False, "fund_ok": False, "kauf": False, "fehler": "ISIN formal ungültig (Länge/Prüfziffer)"})
        return row
    try:
        row.update(technicals_local(isin))
    except Exception as exc:
        row.update({"tech_ok": False, "fehler": f"Technik: {exc}"})
    if not with_fundamentals:
        row["kauf"] = bool(row.get("tech_ok")); return row

    chain = {"auto": ["finanzen", "stockanalysis", "yahoo"], "finanzen": ["finanzen"],
             "stockanalysis": ["stockanalysis"], "yahoo": ["yahoo"]}[source]
    errors, good, sym = [], None, row.get("ticker")
    for name in chain:
        if name == "finanzen" and source == "auto" and _FINANZEN_FAIL_STREAK >= 3:
            continue                                              # Finanzen.net blockiert -> für den Rest des Laufs überspringen
        try:
            if name == "finanzen":
                f = fundamentals_requests(isin)
                if not f.get("fehler"): f["quelle"] = "Finanzen.net"
            elif not sym:
                f = {"fund_ok": False, "fehler": "kein Ticker für " + name}
            elif name == "stockanalysis":
                f = fundamentals_stockanalysis(sym, row.get("kurs"))
            else:
                f = fundamentals_yahoo(sym)
        except Exception as exc:
            f = {"fund_ok": False, "fehler": f"{name}: {exc}"}
        if name == "finanzen":
            _FINANZEN_FAIL_STREAK = 0 if f.get("quelle") else _FINANZEN_FAIL_STREAK + 1
        if f.get("quelle"):
            good, errors = f, ([f["fehler"]] if f.get("fehler") else [])     # frühere Fehlschläge sind dann unwichtig
            break
        errors.append(f.get("fehler", f"{name}: nicht verfügbar"))
    if good:
        row.update({k: v for k, v in good.items() if k != "fehler"})
    else:
        row["fund_ok"] = False
    for e in errors:
        row["fehler"] = (row.get("fehler", "") + " | " + e).strip(" |")
    row["kauf"] = bool(row.get("tech_ok") and row.get("fund_ok"))
    return row


def results_frame(rows: list) -> pd.DataFrame:
    """Ergebnisse als lesbare Tabelle (für Anzeige und CSV)."""
    tick = lambda v: "✅" if v is True else ("❌" if v is False else "")
    out = []
    for r in rows:
        out.append({"ISIN": r.get("isin"), "Ticker": r.get("ticker", ""), "RSI": r.get("rsi"),
                    "RSI-Signal": r.get("rsi_info", ""), "MACD-Signal": r.get("macd_info", ""), "Technik": tick(r.get("tech_ok")),
                    "KGV-Entwicklung": r.get("kgv_info", ""), "EPS-Entwicklung": r.get("eps_info", ""), "Fundamental": tick(r.get("fund_ok")),
                    "Kaufkandidat": tick(r.get("kauf")), "Quelle Fundamental": r.get("quelle", ""), "Hinweis": r.get("fehler", "")})
    return pd.DataFrame(out)


# ----------------------------------------------------------------------------------------------------------------
# OPTIONAL: Technik direkt von Stock3 lesen (Charts sind oft Canvas-Grafiken -> Werte stehen evtl. nicht im Seitentext)
# ----------------------------------------------------------------------------------------------------------------
def technicals_stock3(page, isin: str) -> dict:
    if not STOCK3_URL_TEMPLATE:
        return {"tech_ok": False, "fehler": "STOCK3_URL_TEMPLATE ist leer – bitte URL-Muster eintragen"}
    page.goto(STOCK3_URL_TEMPLATE.format(isin=isin), wait_until="domcontentloaded", timeout=45000)
    close_cookie_banner(page)
    page.wait_for_timeout(6000)                                      # Chart laden lassen
    Path("debug").mkdir(exist_ok=True); page.screenshot(path=f"debug/stock3_{isin}.png")
    text = page.inner_text("body")
    def grab(label):
        m = re.search(label + r"[^0-9\-]{0,40}(-?\d+[.,]?\d*)", text, re.I)
        return parse_de_number(m.group(1)) if m else None
    rsi_v = grab(r"RSI(?:\s*\(?\d+\)?)?")
    if rsi_v is None:
        return {"tech_ok": False, "fehler": "RSI im Seitentext nicht lesbar (Chart ist vermutlich eine Grafik) – siehe debug/-Screenshot"}
    return {"tech_ok": False, "rsi": rsi_v, "fehler": "MACD/Crossover nicht zuverlässig aus Seitentext lesbar – lokale Berechnung nutzen"}


# ----------------------------------------------------------------------------------------------------------------
# HAUPTPROGRAMM
# ----------------------------------------------------------------------------------------------------------------
def load_cache() -> dict:
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8")) if CACHE_FILE.exists() else {}
    except Exception:
        return {}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--technik", choices=["lokal", "stock3"], default="lokal")
    ap.add_argument("--sichtbar", action="store_true", help="Browser sichtbar öffnen")
    ap.add_argument("--limit", type=int, default=0, help="nur die ersten N ISINs")
    ap.add_argument("--neu", action="store_true", help="Cache ignorieren")
    args = ap.parse_args(argv)

    isins = list(dict.fromkeys(ISINS))                               # Duplikate entfernen, Reihenfolge behalten
    invalid = [i for i in isins if not isin_is_valid(i)]
    if invalid:
        print(f"⚠ Formal ungültige ISIN(s), werden übersprungen: {', '.join(invalid)}  (Länge/Prüfziffer stimmt nicht – bitte Tippfehler prüfen)")
    todo = [i for i in isins if i not in invalid]
    if args.limit: todo = todo[: args.limit]

    from playwright.sync_api import sync_playwright
    cache = {} if args.neu else load_cache()
    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.sichtbar)
        ctx = browser.new_context(locale="de-DE", user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36")
        page = ctx.new_page()
        for n, isin in enumerate(todo, 1):
            if isin in cache:
                rows.append(cache[isin]); print(f"[{n}/{len(todo)}] {isin} (aus Cache)"); continue
            print(f"[{n}/{len(todo)}] {isin} ...", end=" ", flush=True)
            row = {"isin": isin}
            try:
                row.update(technicals_local(isin) if args.technik == "lokal" else technicals_stock3(page, isin))
            except Exception as exc:
                row.update({"tech_ok": False, "fehler": f"Technik: {exc}"})
            try:
                f = fundamentals_finanzen(page, isin); row.update({k: v for k, v in f.items() if k != "fehler"})
                if f.get("fehler"): row["fehler"] = (row.get("fehler", "") + " | " + f["fehler"]).strip(" |")
            except Exception as exc:
                row.update({"fund_ok": False}); row["fehler"] = (row.get("fehler", "") + f" | Finanzen.net: {exc}").strip(" |")
            row["kauf"] = bool(row.get("tech_ok") and row.get("fund_ok"))
            rows.append(row); cache[isin] = row
            CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
            print("KAUFKANDIDAT" if row["kauf"] else "-")
            time.sleep(random.uniform(*PAUSE_SECONDS))
        browser.close()

    df = pd.DataFrame(rows)
    df.to_csv("alle_ergebnisse.csv", sep=";", index=False, encoding="utf-8-sig")          # Diagnose: alle Aktien + Grund
    cand = df[df.get("kauf", False) == True] if "kauf" in df else df.iloc[0:0]             # noqa: E712
    cols = {"isin": "ISIN", "ticker": "Ticker", "rsi": "RSI", "rsi_info": "RSI-Signal", "macd_info": "MACD-Signal", "kgv_info": "KGV-Entwicklung", "eps_info": "EPS-Entwicklung"}
    out = cand[[c for c in cols if c in cand.columns]].rename(columns=cols)
    out.to_csv("kaufkandidaten.csv", sep=";", index=False, encoding="utf-8-sig")
    print("\n" + "=" * 100)
    print(f"Geprüft: {len(df)} | Technik ok: {int(df.get('tech_ok', pd.Series(dtype=bool)).sum())} | Fundamental ok: {int(df.get('fund_ok', pd.Series(dtype=bool)).sum())} | Kaufkandidaten (beides): {len(out)}")
    if out.empty:
        print("Keine Aktie erfüllt aktuell ALLE Bedingungen. Details je Aktie: alle_ergebnisse.csv")
    else:
        print(out.to_string(index=False))
    print("Gespeichert: kaufkandidaten.csv, alle_ergebnisse.csv.  Keine Anlageberatung.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
