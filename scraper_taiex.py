"""
證交所：加權指數每日收盤（FMTQIK，一個月查一次），給「避險比例歷史統計」算長期報酬用
輸出：data/taiex.csv  date, taiex

用法：
    python scraper_taiex.py                              # 更新本月（每天盤後跑，約 14:00 後有當天收盤）
    python scraper_taiex.py --backfill 2021/01/01 2026/11/10
"""

import argparse
import csv
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scraper_margin import index_month  # noqa: E402

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
CSV_PATH = os.path.join(DATA_DIR, "taiex.csv")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", nargs=2)
    a = ap.parse_args()
    if a.backfill:
        s, e = a.backfill
    rows = {}
    if os.path.exists(CSV_PATH):
        with open(CSV_PATH, encoding="utf-8") as f:
            rows = {r["date"]: r["taiex"] for r in csv.DictReader(f)}
    if not a.backfill:  # 預設：本月 1 日～今天（月初前 5 天順便補上個月）；今天已有就不再查
        now = datetime.now(timezone(timedelta(hours=8)))
        e = now.strftime("%Y/%m/%d")
        if e in rows:
            print(f"{e} 加權指數已存在，略過")
            return
        s = ((now.replace(day=1) - timedelta(days=1)) if now.day <= 5 else now).strftime("%Y/%m/01")
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
