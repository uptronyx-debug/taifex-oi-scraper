"""
TAIFEX 期貨每日交易行情：臺股期貨（TX）一般交易時段，各月份契約的未沖銷契約量（全市場）
來源：https://www.taifex.com.tw/cht/3/futDailyMarketReport
輸出：data/tx_month_oi.csv

用法：
    python scraper_tx_months.py
    python scraper_tx_months.py --date 2026/10/16
    python scraper_tx_months.py --backfill 2025/10/01 2026/10/16
"""

import argparse
import csv
import io
import os
import re
import sys
import time
from datetime import datetime, timedelta

import pandas as pd
import requests

URL = "https://www.taifex.com.tw/cht/3/futDailyMarketReport"
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
CSV_PATH = os.path.join(DATA_DIR, "tx_month_oi.csv")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": URL,
}
CSV_HEADER = ["date", "contract", "settle", "volume", "oi"]


def _num(v):
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        return 0 if v != v else int(round(v))
    t = str(v).strip().replace(",", "")
    t = re.sub(r"[^\d.\-]", "", t)
    if t in ("", "-", "."):
        return 0
    try:
        return int(round(float(t)))
    except ValueError:
        return 0


def _post(date_str, retries=4):
    last = None
    for i in range(retries):
        try:
            r = requests.post(URL, data={"queryDate": date_str, "MarketCode": "0", "commodity_id": "TX"},
                              headers=HEADERS, timeout=30)
            r.raise_for_status()
            if "</html>" not in r.text.lower():
                raise requests.exceptions.ChunkedEncodingError("回應不完整")
            return r
        except requests.exceptions.RequestException as e:
            last = e
            wait = 5 * 2 ** i
            print(f"  ⚠️ 第 {i + 1} 次抓取失敗（{e!r}），{wait} 秒後重試")
            time.sleep(wait)
    raise last


def _flat(col):
    if isinstance(col, tuple):
        col = " ".join(str(c) for c in col if not str(c).startswith("Unnamed"))
    return re.sub(r"\s+", "", str(col))


def fetch(date_str, debug=False):
    r = _post(date_str)
    m = re.search(r"日期\s*[:：]?\s*(\d{4}/\d{1,2}/\d{1,2})", r.text)
    shown = m.group(1) if m else None
    if shown != date_str:
        print(f"  {date_str}：頁面日期為 {shown}，視為非交易日，略過")
        return []
    tables = pd.read_html(io.StringIO(r.text))
    table = None
    for t in tables:
        cols = [_flat(c) for c in t.columns]
        if any("未沖銷" in c for c in cols) and any("到期" in c for c in cols):
            t = t.copy()
            t.columns = cols
            table = t
            break
    if table is None:
        print(f"  ⚠️ {date_str}：找不到行情表，表格欄位：{[[_flat(c) for c in t.columns] for t in tables][:3]}")
        return []
    if debug:
        print(table.head(10).to_string())
    c_contract = next(c for c in table.columns if c.startswith("契約"))
    c_month = next(c for c in table.columns if "到期" in c)
    c_oi = next(c for c in table.columns if "未沖銷" in c)
    c_settle = next((c for c in table.columns if "結算價" in c), None)
    c_vol = next((c for c in table.columns if "合計成交量" in c), None)

    records = []
    for _, row in table.iterrows():
        if str(row[c_contract]).strip() != "TX":
            continue
        mv = row[c_month]
        month = str(int(mv)) if isinstance(mv, float) and mv == mv and mv.is_integer() else re.sub(r"\s+", "", str(mv))
        if not re.fullmatch(r"\d{6}", month):  # 只要月契約，排除週契約與價差
            continue
        records.append({
            "date": date_str,
            "contract": month,
            "settle": _num(row[c_settle]) if c_settle else 0,
            "volume": _num(row[c_vol]) if c_vol else 0,
            "oi": _num(row[c_oi]),
        })
    records.sort(key=lambda r: r["contract"])
    if records and sum(r["oi"] for r in records) == 0:
        print(f"  ⚠️ {date_str}：未沖銷量全部為 0，可能尚未收盤，不寫入")
        return []
    return records


def existing_dates():
    if not os.path.exists(CSV_PATH) or os.path.getsize(CSV_PATH) == 0:
        return set()
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        return {row["date"] for row in csv.DictReader(f)}


def append(records):
    if not records:
        return
    os.makedirs(DATA_DIR, exist_ok=True)
    new_file = not os.path.exists(CSV_PATH) or os.path.getsize(CSV_PATH) == 0
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_HEADER)
        if new_file:
            w.writeheader()
        w.writerows(records)


def run_one(date_str, have, debug=False):
    if date_str in have:
        print(f"{date_str} 已有大台各月份資料，略過")
        return True
    recs = fetch(date_str, debug)
    append(recs)
    if recs:
        print(f"✅ {date_str} " + "　".join(f"{r['contract']}:{r['oi']:,}" for r in recs[:3]))
    return bool(recs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--backfill", nargs=2)
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args()
    have = existing_dates()
    if a.backfill:
        d = datetime.strptime(a.backfill[0], "%Y/%m/%d")
        end = datetime.strptime(a.backfill[1], "%Y/%m/%d")
        while d <= end:
            if d.weekday() < 5:
                ds = d.strftime("%Y/%m/%d")
                if ds not in have:
                    run_one(ds, have)
                    time.sleep(1.5)
            d += timedelta(days=1)
        return
    date_str = a.date or datetime.now().strftime("%Y/%m/%d")
    if datetime.strptime(date_str, "%Y/%m/%d").weekday() >= 5:
        print(f"{date_str} 是週末，略過")
        return
    if not run_one(date_str, have, a.debug):
        # 沒資料不在這裡報錯；由 tools/check_today.py post 統一判斷是休市、尚未公布，還是真的壞掉
        print("⚠️ 沒有寫入大台各月份資料（是否異常由最後的資料檢查步驟判斷）")


if __name__ == "__main__":
    main()
