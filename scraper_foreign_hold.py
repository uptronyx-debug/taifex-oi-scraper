"""
證交所：外資及陸資持股市值（集中市場普通股，排除 ETF）
  持股股數：https://www.twse.com.tw/rwd/zh/fund/MI_QFIIS（selectType=ALLBUT0999）
  收盤價  ：https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX（type=ALLBUT0999）
外資持股市值 = Σ（全體外資及陸資持有股數 × 收盤價）
上市市值     = Σ（發行股數 × 收盤價），兩者相除即外資整體持股比率
輸出：data/foreign_hold.csv
  date, foreign_value（元）, market_value（元）, stocks（計入檔數）

用法：
    python scraper_foreign_hold.py
    python scraper_foreign_hold.py --date 2026/11/06
    python scraper_foreign_hold.py --backfill 2025/10/01 2026/11/06
"""

import argparse
import csv
import os
import sys
import time
from datetime import datetime, timedelta

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scraper_margin import index_month  # noqa: E402

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
CSV_PATH = os.path.join(DATA_DIR, "foreign_hold.csv")
CSV_HEADER = ["date", "foreign_value", "market_value", "stocks"]
QFIIS_URL = "https://www.twse.com.tw/rwd/zh/fund/MI_QFIIS"
INDEX_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}


def _num(t):
    try:
        return float(str(t).replace(",", "").strip())
    except ValueError:
        return None


def _get(url, params, retries=4):
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=60)
            r.raise_for_status()
            return r.json()
        except (requests.exceptions.RequestException, ValueError) as e:
            last = e
            wait = 5 * 2 ** i
            print(f"  ⚠️ 第 {i + 1} 次抓取失敗（{e!r}），{wait} 秒後重試")
            time.sleep(wait)
    raise last


def is_stock(code):
    return len(code) == 4 and code.isdigit() and not code.startswith("00")


def fetch(date_str):
    ymd = datetime.strptime(date_str, "%Y/%m/%d").strftime("%Y%m%d")
    q = _get(QFIIS_URL, {"date": ymd, "selectType": "ALLBUT0999", "response": "json"})
    if q.get("stat") != "OK" or q.get("date") != ymd:
        print(f"  {date_str}：外資持股資料尚未公布（{q.get('stat')}）")
        return None
    time.sleep(3)
    p = _get(INDEX_URL, {"date": ymd, "type": "ALLBUT0999", "response": "json"})
    if p.get("stat") != "OK" or p.get("date") != ymd:
        print(f"  {date_str}：收盤行情尚未公布（{p.get('stat')}）")
        return None
    qf = q["fields"]
    iq_code, iq_issued, iq_hold = qf.index("證券代號"), qf.index("發行股數"), qf.index("全體外資及陸資持有股數")
    tbl = next((t for t in p.get("tables", []) if "收盤價" in (t.get("fields") or [])), None)
    if not tbl:
        print(f"  ⚠️ {date_str}：找不到每日收盤行情表")
        return None
    pf = tbl["fields"]
    ip_code, ip_close = pf.index("證券代號"), pf.index("收盤價")
    close = {}
    for row in tbl["data"]:
        c = _num(row[ip_close])
        if c:
            close[str(row[ip_code]).strip()] = c
    fv = mv = 0.0
    n = 0
    for row in q["data"]:
        code = str(row[iq_code]).strip()
        if not is_stock(code) or code not in close:
            continue
        hold, issued = _num(row[iq_hold]), _num(row[iq_issued])
        if hold is None or issued is None:
            continue
        fv += hold * close[code]
        mv += issued * close[code]
        n += 1
    if n < 500:
        print(f"  ⚠️ {date_str}：只對到 {n} 檔股票，資料可能不完整，不寫入")
        return None
    return {"date": date_str, "foreign_value": f"{fv:.0f}", "market_value": f"{mv:.0f}", "stocks": n}


def existing_dates():
    if not os.path.exists(CSV_PATH) or os.path.getsize(CSV_PATH) == 0:
        return set()
    with open(CSV_PATH, newline="", encoding="utf-8") as fh:
        return {row["date"] for row in csv.DictReader(fh)}


def append(rec):
    os.makedirs(DATA_DIR, exist_ok=True)
    new_file = not os.path.exists(CSV_PATH) or os.path.getsize(CSV_PATH) == 0
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_HEADER)
        if new_file:
            w.writeheader()
        w.writerow(rec)


def run_one(date_str, have):
    if date_str in have:
        print(f"{date_str} 已有外資持股資料，略過")
        return True
    rec = fetch(date_str)
    if not rec:
        return False
    append(rec)
    have.add(date_str)
    fv, mv = float(rec["foreign_value"]), float(rec["market_value"])
    print(f"✅ {date_str} 外資持股市值 {fv / 1e12:,.2f} 兆／上市市值 {mv / 1e12:,.2f} 兆（{fv / mv * 100:.2f}%，{rec['stocks']} 檔）")
    return True


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
            ds = d.strftime("%Y/%m/%d")
            if ds not in have and ds in index_month(d.year, d.month):
                run_one(ds, have)
                time.sleep(3)
            d += timedelta(days=1)
        return
    date_str = a.date or datetime.now().strftime("%Y/%m/%d")
    if datetime.strptime(date_str, "%Y/%m/%d").weekday() >= 5:
        print(f"{date_str} 是週末，略過")
        return
    if not run_one(date_str, have):
        print("⚠️ 沒有寫入外資持股資料（是否異常由最後的資料檢查步驟判斷）")


if __name__ == "__main__":
    main()
