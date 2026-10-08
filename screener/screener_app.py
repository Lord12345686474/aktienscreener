# -*- coding: utf-8 -*-
"""Webseiten-Version des Aktien-Screeners (Streamlit).  Start:  py -m streamlit run screener_app.py
Beide Dateien (screener_app.py und aktien_screener.py) müssen im selben Ordner liegen."""
import pathlib, sys, time, random
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import pandas as pd
import streamlit as st
import aktien_screener as sc

st.set_page_config(page_title="Aktien-Screener", layout="wide")
st.title("🔎 Aktien-Screener: RSI + MACD + KGV + EPS")
st.caption("Kaufkandidat = Technik (RSI und MACD) UND Fundamentaldaten (KGV sinkend, EPS steigend). Keine Anlageberatung.")

with st.sidebar:
    st.header("Einstellungen")
    only_tech = st.checkbox("Nur Technik prüfen (ohne Fundamentaldaten, viel schneller)", value=False)
    SOURCES = {"Automatisch (Finanzen.net → StockAnalysis → Yahoo)": "auto", "Nur StockAnalysis.com (nur US-Aktien)": "stockanalysis",
               "Nur Yahoo (berechnet)": "yahoo", "Nur Finanzen.net": "finanzen"}
    src_label = st.selectbox("Quelle für KGV/EPS", list(SOURCES), help="Finanzen.net blockiert einfache Abrufe häufig (HTTP 403). Dann springt 'Automatisch' weiter.")
    source = SOURCES[src_label]
    manual = st.text_area("Ticker manuell zuordnen (ISIN=TICKER, eine pro Zeile)", "\n".join(f"{k}={v}" for k, v in sc.TICKER_OVERRIDES.items()),
                          help="Für ISINs, die Yahoo nicht automatisch findet.")
    for line in manual.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            if k.strip() and v.strip(): sc.TICKER_OVERRIDES[k.strip().upper()] = v.strip()
    limit = st.number_input("Nur die ersten N ISINs (0 = alle)", 0, 500, 0)
    pause = st.slider("Pause zwischen Aktien (Sekunden)", 0.0, 6.0, 2.0, 0.5, help="Höflich gegenüber den Webseiten; bei 'Nur Technik' kannst du auf 0 stellen.")
    sc.RSI_RECENT_BARS = st.slider("RSI-Durchbruch 30: wie viele Tage zählt 'kürzlich'?", 1, 15, sc.RSI_RECENT_BARS)
    sc.MACD_RECENT_BARS = st.slider("MACD-Crossover: wie viele Tage zählt 'aktuell'?", 1, 10, sc.MACD_RECENT_BARS)
    fresh = st.checkbox("Gespeicherte Ergebnisse verwerfen", value=False)

default_text = "\n".join(sc.ISINS)
text = st.text_area("ISIN-Liste (eine pro Zeile, frei änderbar)", default_text, height=160)
isins = list(dict.fromkeys(x.strip().upper() for x in text.replace(",", "\n").splitlines() if x.strip()))
bad = [i for i in isins if not sc.isin_is_valid(i)]
st.write(f"**{len(isins)} ISINs** eingelesen." + (f"  ⚠ Formal ungültig: {', '.join(bad)}" if bad else "  Alle formal gültig."))

if "results" not in st.session_state or fresh:
    st.session_state["results"] = {}
results = st.session_state["results"]

if st.button("▶ Screener starten", type="primary"):
    todo = [i for i in isins if i not in bad][: (limit or None)]
    sc.reset_finanzen_block()
    bar, status, live = st.progress(0.0), st.empty(), st.empty()
    for n, isin in enumerate(todo, 1):
        if isin not in results:                                   # bereits geprüfte überspringen (Fortsetzen möglich)
            status.write(f"Prüfe {isin}  ({n}/{len(todo)}) …")
            results[isin] = sc.screen_isin(isin, with_fundamentals=not only_tech, source=source)
            if pause and not only_tech: time.sleep(random.uniform(pause, pause * 1.8))
        bar.progress(n / len(todo))
        live.dataframe(sc.results_frame([results[i] for i in todo if i in results]), hide_index=True)
    status.success("Fertig.")

rows = [results[i] for i in isins if i in results]
if rows:
    frame = sc.results_frame(rows)
    cand = frame[frame["Kaufkandidat"] == "✅"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Geprüft", len(frame)); c2.metric("Technik erfüllt", int((frame["Technik"] == "✅").sum())); c3.metric("Kaufkandidaten", len(cand))
    st.subheader("Kaufkandidaten")
    if cand.empty:
        st.info("Aktuell erfüllt keine Aktie alle Bedingungen. Das ist bei einer UND-Verknüpfung nicht ungewöhnlich. Unten siehst du, woran es je Aktie liegt.")
    else:
        st.dataframe(cand.drop(columns=["Kaufkandidat"]), hide_index=True)
        st.download_button("⬇ kaufkandidaten.csv", cand.to_csv(sep=";", index=False).encode("utf-8-sig"), "kaufkandidaten.csv", "text/csv")
    with st.expander("Alle Ergebnisse (mit Hinweisen und Fehlern)"):
        st.dataframe(frame, hide_index=True)
        st.download_button("⬇ alle_ergebnisse.csv", frame.to_csv(sep=";", index=False).encode("utf-8-sig"), "alle_ergebnisse.csv", "text/csv")
    errs = frame[frame["Hinweis"] != ""]
    if len(errs) > 0.5 * len(frame):
        st.warning("Bei vielen Aktien gab es Hinweise/Fehler (Spalte 'Hinweis'). Die Fundamentaldaten-Anbindung ist nicht live getestet und muss ggf. angepasst werden.")
