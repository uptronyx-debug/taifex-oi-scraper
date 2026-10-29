"""
證交所：全市場（集中市場）融資餘額 ＋ 加權指數收盤
來源：
  融資：https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN（信用交易統計，每日約 21:30 公布）
  指數：https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK（每日市場成交資訊，按月查詢）
輸出：data/margin.csv
  date, taiex, margin_lots（融資今日餘額，張）, margin_amount_k（融資金額今日餘額，仟元）

用法：
    python scraper_margin.py
    python scraper_margin.py --date 2026/10/28
    python scraper_margin.py --backfill 2025/10/01 2026/10/28
"""

import argparse
import csv
import os
import sys
import time
from datetime import datetime, timedelta

import requests

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
CSV_PATH = os.path.join(DATA_DIR, "margin.csv")
CSV_HEADER = ["date", "taiex", "margin_lots", "margin_amount_k"]
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}
MARGIN_URL = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
INDEX_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK"
_index_cache = {}


def _num(t):
    t = str(t).strip().replace(",", "")
    try:
        return float(t)
    except ValueError:
        return None


def _get(url, params, retries=4):
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=30)
            r.raise_for_status()
            return r.json()
        except (requests.exceptions.RequestException, ValueError) as e:
            last = e
            wait = 5 * 2 ** i
            print(f"  ⚠️ 第 {i + 1} 次抓取失敗（{e!r}），{wait} 秒後重試")
            time.sleep(wait)
    raise last


def index_month(year, month):
    """回傳 {YYYY/MM/DD: 加權指數收盤}，同一個月份只查一次"""
    key = (year, month)
    if key not in _index_cache:
        j = _get(INDEX_URL, {"date": f"{year}{month:02d}01", "response": "json"})
        out = {}
        if j.get("stat") == "OK":
            fields = j.get("fields", [])
            idx = fields.index("發行量加權股價指數") if "發行量加權股價指數" in fields else 4
            for row in j.get("data", []):
                roc_y, m, d = str(row[0]).split("/")
                out[f"{int(roc_y) + 1911}/{m}/{d}"] = _num(row[idx])
        _index_cache[key] = out
        time.sleep(3)
    return _index_cache[key]


def fetch(date_str):
    dt = datetime.strptime(date_str, "%Y/%m/%d")
    taiex = index_month(dt.year, dt.month).get(date_str)
    if taiex is None:
        print(f"  {date_str}：證交所沒有當天的加權指數（非交易日或尚未公布）")
        return None
    j = _get(MARGIN_URL, {"date": dt.strftime("%Y%m%d"), "selectType": "MS", "response": "json"})
    if j.get("stat") != "OK" or j.get("date") != dt.strftime("%Y%m%d"):
        print(f"  {date_str}：融資資料尚未公布（{j.get('stat')}）")
        return None
    lots = amount = None
    for t in j.get("tables", []):
        fields = t.get("fields") or []
        if "今日餘額" not in fields:
            continue
        col = fields.index("今日餘額")
        for row in t.get("data", []):
            name = str(row[0])
            if name.startswith("融資(交易單位)"):
                lots = _num(row[col])
            elif name.startswith("融資金額"):
                amount = _num(row[col])
    if not lots or not amount:
        print(f"  ⚠️ {date_str}：找不到融資餘額欄位（格式可能改了）")
        return None
    return {"date": date_str, "taiex": f"{taiex:.2f}", "margin_lots": int(lots), "margin_amount_k": int(amount)}


def existing_dates():
    if not os.path.exists(CSV_PATH) or os.path.getsize(CSV_PATH) == 0:
        return set()
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        return {row["date"] for row in csv.DictReader(f)}


def append(rec):
    os.makedirs(DATA_DIR, exist_ok=True)
    new_file = not os.path.exists(CSV_PATH) or os.path.getsize(CSV_PATH) == 0
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_HEADER)
        if new_file:
            w.writeheader()
        w.writerow(rec)


def run_one(date_str, have):
    if date_str in have:
        print(f"{date_str} 已有融資資料，略過")
        return True
    rec = fetch(date_str)
    if not rec:
        return False
    append(rec)
    have.add(date_str)
    print(f"✅ {date_str} 加權 {rec['taiex']}　融資 {rec['margin_lots']:,} 張／{rec['margin_amount_k'] / 1e5:,.1f} 億")
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
            # 只查證交所指數表上有的交易日，避免假日白跑
            if ds not in have and ds in index_month(d.year, d.month):
                run_one(ds, have)
                time.sleep(3)  # 證交所有頻率限制
            d += timedelta(days=1)
        return
    date_str = a.date or datetime.now().strftime("%Y/%m/%d")
    if datetime.strptime(date_str, "%Y/%m/%d").weekday() >= 5:
        print(f"{date_str} 是週末，略過")
        return
    if not run_one(date_str, have):
        print("⚠️ 沒有寫入融資資料（是否異常由最後的資料檢查步驟判斷）")


if __name__ == "__main__":
    main()
