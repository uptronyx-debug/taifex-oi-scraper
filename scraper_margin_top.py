"""
證交所：個股融資增減排行（集中市場，排除 ETF）
來源：https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN（selectType=ALL，融資融券彙總）
每天約 21:30 公布。存每日「資增前 5」與「資減前 5」（以融資張數增減排序）。
輸出：data/margin_top.csv
  date, side（inc 資增 / dec 資減）, rank, code, name, change_lots, balance_lots

用法：
    python scraper_margin_top.py
    python scraper_margin_top.py --date 2026/11/06
    python scraper_margin_top.py --backfill 2025/10/01 2026/11/06
"""

import argparse
import csv
import os
import sys
import time
from datetime import datetime, timedelta

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scraper_margin import index_month  # 用加權指數表判斷交易日  # noqa: E402

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
CSV_PATH = os.path.join(DATA_DIR, "margin_top.csv")
CSV_HEADER = ["date", "side", "rank", "code", "name", "change_lots", "balance_lots"]
URL = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}
TOP_N = 5


def _int(t):
    try:
        return int(str(t).replace(",", "").strip())
    except ValueError:
        return None


def _get(params, retries=4):
    last = None
    for i in range(retries):
        try:
            r = requests.get(URL, params=params, headers=HEADERS, timeout=60)
            r.raise_for_status()
            return r.json()
        except (requests.exceptions.RequestException, ValueError) as e:
            last = e
            wait = 5 * 2 ** i
            print(f"  ⚠️ 第 {i + 1} 次抓取失敗（{e!r}），{wait} 秒後重試")
            time.sleep(wait)
    raise last


def fetch(date_str):
    dt = datetime.strptime(date_str, "%Y/%m/%d")
    j = _get({"date": dt.strftime("%Y%m%d"), "selectType": "ALL", "response": "json"})
    if j.get("stat") != "OK" or j.get("date") != dt.strftime("%Y%m%d"):
        print(f"  {date_str}：個股融資資料尚未公布（{j.get('stat')}）")
        return None
    table = next((t for t in j.get("tables", []) if (t.get("fields") or [])[:2] == ["代號", "名稱"]), None)
    if not table:
        print(f"  ⚠️ {date_str}：找不到融資融券彙總表（格式可能改了）")
        return None
    f = table["fields"]
    i_prev, i_now = f.index("前日餘額"), f.index("今日餘額")  # 第一組是融資
    stocks = []
    for row in table.get("data", []):
        code = str(row[0]).strip()
        if code.startswith("00") or not code[:4].isdigit():  # 排除 ETF 等
            continue
        prev, now = _int(row[i_prev]), _int(row[i_now])
        if prev is None or now is None:
            continue
        stocks.append((code, str(row[1]).strip(), now - prev, now))
    if not stocks:
        return None
    inc = sorted(stocks, key=lambda x: -x[2])[:TOP_N]
    dec = sorted(stocks, key=lambda x: x[2])[:TOP_N]
    recs = []
    for side, lst in (("inc", inc), ("dec", dec)):
        for k, (code, name, chg, bal) in enumerate(lst, 1):
            recs.append({"date": date_str, "side": side, "rank": k, "code": code, "name": name,
                         "change_lots": chg, "balance_lots": bal})
    return recs


def existing_dates():
    if not os.path.exists(CSV_PATH) or os.path.getsize(CSV_PATH) == 0:
        return set()
    with open(CSV_PATH, newline="", encoding="utf-8") as fh:
        return {row["date"] for row in csv.DictReader(fh)}


def append(recs):
    os.makedirs(DATA_DIR, exist_ok=True)
    new_file = not os.path.exists(CSV_PATH) or os.path.getsize(CSV_PATH) == 0
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_HEADER)
        if new_file:
            w.writeheader()
        w.writerows(recs)


def run_one(date_str, have):
    if date_str in have:
        print(f"{date_str} 已有個股融資排行，略過")
        return True
    recs = fetch(date_str)
    if not recs:
        return False
    append(recs)
    have.add(date_str)
    top = lambda s: "、".join(f"{r['name']}{r['change_lots']:+,}" for r in recs if r["side"] == s)
    print(f"✅ {date_str} 資增：{top('inc')}｜資減：{top('dec')}")
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
        print("⚠️ 沒有寫入個股融資排行（是否異常由最後的資料檢查步驟判斷）")


if __name__ == "__main__":
    main()
