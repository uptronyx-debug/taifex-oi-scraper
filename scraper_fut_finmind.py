"""
期交所只提供近三年的「三大法人-區分各期貨契約」。更早的大台（TX）三大法人未平倉改用 FinMind 開放資料補
（與期交所重疊日期逐筆比對過，數字相同）。只補大台，小台、微台不補。
輸出：附加到 data/fut_oi.csv（已存在的日期略過）

用法：
    python scraper_fut_finmind.py --backfill 2021/10/01 2023/11/09
"""

import argparse
import csv
import os

import requests

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
CSV_PATH = os.path.join(DATA_DIR, "fut_oi.csv")
HEADER = ["date", "product", "investor_type", "oi_long_volume", "oi_long_value_k",
          "oi_short_volume", "oi_short_value_k", "oi_net_volume", "oi_net_value_k"]
INV = {"自營商": "dealer", "投信": "trust", "外資": "foreign", "外資及陸資": "foreign"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", nargs=2, required=True)
    s, e = ap.parse_args().backfill
    have = set()
    if os.path.exists(CSV_PATH):
        with open(CSV_PATH, encoding="utf-8") as f:
            have = {r["date"] for r in csv.DictReader(f)}
    r = requests.get("https://api.finmindtrade.com/api/v4/data", timeout=120, params={
        "dataset": "TaiwanFuturesInstitutionalInvestors", "data_id": "TX",
        "start_date": s.replace("/", "-"), "end_date": e.replace("/", "-")})
    r.raise_for_status()
    data = r.json().get("data", [])
    out = []
    for x in data:
        d = x["date"].replace("-", "/")
        inv = INV.get(x["institutional_investors"])
        if not inv or d in have:
            continue
        lv, la = int(x["long_open_interest_balance_volume"]), int(x["long_open_interest_balance_amount"])
        sv, sa = int(x["short_open_interest_balance_volume"]), int(x["short_open_interest_balance_amount"])
        out.append([d, "TX", inv, lv, la, sv, sa, lv - sv, la - sa])
    new_file = not os.path.exists(CSV_PATH) or os.path.getsize(CSV_PATH) == 0
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CSV_PATH, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(HEADER)
        w.writerows(out)
    print(f"FinMind 補了 {len({r[0] for r in out})} 天（{len(out)} 筆）")


if __name__ == "__main__":
    main()
