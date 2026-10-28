"""
TAIFEX 三大法人－區分各期貨契約：臺股期貨（大台）、小型臺指、微型臺指的未平倉餘額
來源：https://www.taifex.com.tw/cht/3/futContractsDate
輸出：data/fut_oi.csv（契約金額單位：千元）

用法：
    python scraper_futures.py                          # 抓今天
    python scraper_futures.py --date 2026/10/16        # 抓指定日期
    python scraper_futures.py --backfill 2025/10/01 2026/10/16
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

URL = "https://www.taifex.com.tw/cht/3/futContractsDate"
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
CSV_PATH = os.path.join(DATA_DIR, "fut_oi.csv")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": URL,
}
CSV_HEADER = [
    "date", "product", "investor_type",
    "oi_long_volume", "oi_long_value_k",
    "oi_short_volume", "oi_short_value_k",
    "oi_net_volume", "oi_net_value_k",
]
PRODUCTS = {"臺股期貨": "TX", "小型臺指期貨": "MTX", "微型臺指期貨": "TMF"}
INVESTORS = {"自營商": "dealer", "投信": "trust", "外資": "foreign"}


def _num(v):
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        return 0 if v != v else int(round(v))
    t = str(v).strip().replace(",", "")
    if t in ("", "-", "－", "nan"):
        return 0
    try:
        return int(float(t))
    except ValueError:
        return 0


def _post(date_str, retries=4):
    last = None
    for i in range(retries):
        try:
            r = requests.post(URL, data={"queryDate": date_str, "commodityId": ""}, headers=HEADERS, timeout=30)
            r.raise_for_status()
            if "</html>" not in r.text.lower():
                raise requests.exceptions.ChunkedEncodingError("回應不完整")
            return r
        except (requests.exceptions.RequestException,) as e:
            last = e
            wait = 5 * 2 ** i
            print(f"  ⚠️ 第 {i + 1} 次抓取失敗（{e!r}），{wait} 秒後重試")
            time.sleep(wait)
    raise last


def fetch(date_str):
    """回傳 list[dict]；非交易日或頁面日期不符時回傳 []"""
    r = _post(date_str)
    m = re.search(r"日期\s*(\d{4}/\d{1,2}/\d{1,2})", r.text)
    shown = m.group(1) if m else None
    if shown != date_str:
        print(f"  {date_str}：頁面日期為 {shown}，視為非交易日，略過")
        return []
    tables = pd.read_html(io.StringIO(r.text))
    table = None
    for t in tables:
        if t.shape[1] == 15 and "未平倉餘額" in " ".join(map(str, t.columns)):
            table = t
            break
    if table is None:
        print(f"  ⚠️ {date_str}：找不到預期的表格（欄位格式可能改了）")
        return []

    records = []
    for row in table.itertuples(index=False):
        cells = list(row)
        product = re.sub(r"\s+", "", str(cells[1]))
        investor = re.sub(r"\s+", "", str(cells[2]))
        if product not in PRODUCTS or investor not in INVESTORS:
            continue
        n = [_num(x) for x in cells[9:15]]
        records.append({
            "date": date_str,
            "product": PRODUCTS[product],
            "investor_type": INVESTORS[investor],
            "oi_long_volume": n[0], "oi_long_value_k": n[1],
            "oi_short_volume": n[2], "oi_short_value_k": n[3],
            "oi_net_volume": n[4], "oi_net_value_k": n[5],
        })
    if records and all(r["oi_long_volume"] == 0 and r["oi_short_volume"] == 0 for r in records):
        print(f"  ⚠️ {date_str}：未平倉全部為 0，可能尚未收盤，不寫入")
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


def run_one(date_str, have):
    if date_str in have:
        print(f"{date_str} 已有期貨資料，略過")
        return True
    recs = fetch(date_str)
    append(recs)
    if recs:
        fx = next((r for r in recs if r["product"] == "TX" and r["investor_type"] == "foreign"), None)
        print(f"✅ {date_str} 寫入 {len(recs)} 筆；外資大台淨未平倉 {fx['oi_net_volume'] if fx else '?'} 口")
    return bool(recs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--backfill", nargs=2)
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
    if not run_one(date_str, have):
        # 沒資料不在這裡報錯；由 tools/check_today.py post 統一判斷是休市、尚未公布，還是真的壞掉
        print("⚠️ 沒有寫入期貨資料（是否異常由最後的資料檢查步驟判斷）")


if __name__ == "__main__":
    main()
