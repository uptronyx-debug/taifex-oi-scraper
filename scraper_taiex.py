"""
證交所：加權指數每日收盤（FMTQIK，一個月查一次），給「避險比例歷史統計」算長期報酬用
輸出：data/taiex.csv  date, taiex

用法：
    python scraper_taiex.py --backfill 2021/01/01 2026/11/10
"""

import argparse
import csv
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scraper_margin import index_month  # noqa: E402

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
CSV_PATH = os.path.join(DATA_DIR, "taiex.csv")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", nargs=2, required=True)
    a = ap.parse_args()
    s, e = a.backfill
    rows = {}
    if os.path.exists(CSV_PATH):
        with open(CSV_PATH, encoding="utf-8") as f:
            rows = {r["date"]: r["taiex"] for r in csv.DictReader(f)}
    y, m = int(s[:4]), int(s[5:7])
    while (y, m) <= (int(e[:4]), int(e[5:7])):
        for d, v in index_month(y, m).items():
            if s <= d <= e and v:
                rows[d] = f"{v:.2f}"
        print(f"{y}/{m:02d} 完成，累計 {len(rows)} 天")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "taiex"])
        for d in sorted(rows):
            w.writerow([d, rows[d]])


if __name__ == "__main__":
    main()
