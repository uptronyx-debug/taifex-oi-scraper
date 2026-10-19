"""
證交所 三大法人買賣金額統計表（集中市場現貨買賣超）
來源：https://www.twse.com.tw/rwd/zh/fund/BFI82U
輸出：data/spot_net.csv（買賣差額，單位：元）

用法：
    python scraper_spot.py                          # 抓今天
    python scraper_spot.py --date 2026/10/16
    python scraper_spot.py --backfill 2025/10/01 2026/10/16
"""

import argparse
import csv
import os
import sys
import time
from datetime import datetime, timedelta

import requests

URL = "https://www.twse.com.tw/rwd/zh/fund/BFI82U"
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
CSV_PATH = os.path.join(DATA_DIR, "spot_net.csv")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}
CSV_HEADER = ["date", "dealer_self", "dealer_hedge", "trust", "foreign", "foreign_dealer", "total"]
# 證交所的列名稱 → CSV 欄位
ROW_MAP = [
    ("自營商(自行買賣)", "dealer_self"),
    ("自營商(避險)", "dealer_hedge"),
    ("投信", "trust"),
    ("外資及陸資(不含外資自營商)", "foreign"),
    ("外資自營商", "foreign_dealer"),
    ("合計", "total"),
]


def _num(t):
    t = str(t).strip().replace(",", "")
    try:
        return int(float(t))
    except ValueError:
        return 0


def _get(date_str, retries=4):
    ymd = date_str.replace("/", "")
    last = None
    for i in range(retries):
        try:
            r = requests.get(URL, params={"type": "day", "dayDate": ymd, "response": "json"}, headers=HEADERS, timeout=30)
            r.raise_for_status()
            return r.json()
        except (requests.exceptions.RequestException, ValueError) as e:
            last = e
            wait = 5 * 2 ** i
            print(f"  ⚠️ 第 {i + 1} 次抓取失敗（{e!r}），{wait} 秒後重試")
            time.sleep(wait)
    raise last


def fetch(date_str):
    j = _get(date_str)
    if j.get("stat") != "OK" or not j.get("data"):
        print(f"  {date_str}：證交所無資料（{j.get('stat')}），視為非交易日或尚未公布")
        return None
    if j.get("date") != date_str.replace("/", ""):
        print(f"  {date_str}：回傳日期 {j.get('date')} 不符，略過")
        return None
    rec = {"date": date_str}
    names = {str(row[0]).strip(): row for row in j["data"]}
    for name, key in ROW_MAP:
        row = names.get(name)
        if row is None:
            print(f"  ⚠️ {date_str}：找不到「{name}」這一列，實際列名：{list(names)}")
            return None
        rec[key] = _num(row[3])
    return rec


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
        print(f"{date_str} 已有現貨資料，略過")
        return True
    rec = fetch(date_str)
    if not rec:
        return False
    append(rec)
    yi = lambda v: f"{v / 1e8:+.2f}億"
    print(f"✅ {date_str} 外資 {yi(rec['foreign'] + rec['foreign_dealer'])}（不含外資自營 {yi(rec['foreign'])}）"
          f" 投信 {yi(rec['trust'])} 自營 {yi(rec['dealer_self'] + rec['dealer_hedge'])} 合計 {yi(rec['total'])}")
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
            if d.weekday() < 5:
                ds = d.strftime("%Y/%m/%d")
                if ds not in have:
                    run_one(ds, have)
                    time.sleep(3)  # 證交所有頻率限制
            d += timedelta(days=1)
        return
    date_str = a.date or datetime.now().strftime("%Y/%m/%d")
    if datetime.strptime(date_str, "%Y/%m/%d").weekday() >= 5:
        print(f"{date_str} 是週末，略過")
        return
    if not run_one(date_str, have):
        print("❌ 沒有寫入現貨資料")
        sys.exit(1)


if __name__ == "__main__":
    main()
