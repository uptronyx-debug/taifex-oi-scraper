"""
TAIFEX 臺指選擇權 各履約價未平倉量 每日爬蟲
=============================================

抓取來源：https://www.taifex.com.tw/cht/3/optDailyMarketReport
（每日選擇權行情表，含每個履約價、買權/賣權的未沖銷契約量）

用途：算出當天未平倉量最大的履約價，作為支撐/壓力參考點位
（類似玩股網「台指選擇權支撐壓力表」的邏輯，但這裡是總市場未平倉量，
不是法人限定的資料——TAIFEX 沒有公開「法人別 x 履約價」的交叉資料）。

⚠️ 重要假設：
  1. POST 欄位名稱：queryDate / commodity_id / MarketCode
     （這組已經有其他開發者實測成功過，可信度較高，但仍建議跑一次確認）
  2. commodity_id 固定用 'TXO'（臺指選擇權），MarketCode 用 '0'（日盤）
  3. 「近月/當週」判斷：用 到期月份(週別) 欄位字串解析，挑最快到期的合約
     （例如 '202511W3' 代表 2025年11月第3週到期；純數字如 '202512' 代表月選）
     這個排序邏輯是我自己寫的簡化版，如果 TAIFEX 改變欄位格式，需要調整。

用法：
    python scraper_by_strike.py                    # 抓「今天」
    python scraper_by_strike.py --date 2026/09/09  # 抓指定日期
"""

import argparse
import csv
import os
import re
import sys
from datetime import datetime

import requests

TARGET_URL = "https://www.taifex.com.tw/cht/3/optDailyMarketReport"
CSV_PATH = os.path.join(os.path.dirname(__file__), "data", "txo_strike_oi.csv")

CSV_HEADER = ["date", "expiry", "strike", "option_type", "open_interest"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": TARGET_URL,
}


def _clean_number(value):
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        if value != value:  # NaN 檢查
            return 0
        return int(round(value))
    text = str(value).strip().replace(",", "")
    if text in ("", "-", "－", "nan"):
        return 0
    try:
        return int(float(text))
    except ValueError:
        cleaned = "".join(ch for ch in text if ch.isdigit())
        return int(cleaned) if cleaned else 0


def _expiry_sort_key(expiry_str):
    """把 '202511W3' / '202512' 轉成可排序的 (年月, 週別) tuple，週選在同月月選之前到期。"""
    m = re.match(r"(\d{6})(W(\d))?", (expiry_str or "").strip())
    if not m:
        return (999999, 99)
    yyyymm = int(m.group(1))
    week = int(m.group(3)) if m.group(3) else 99
    return (yyyymm, week)


def fetch_strike_oi(date_str, commodity_id="TXO", market_code="0"):
    """
    回傳 (records, nearest_expiry)。
    records: list[dict]，只包含「最近到期合約」的每個履約價 call/put 未平倉量。
    """
    payload = {
        "queryDate": date_str,
        "commodity_id": commodity_id,
        "MarketCode": market_code,
    }
    resp = requests.post(TARGET_URL, data=payload, headers=HEADERS, timeout=20)
    resp.raise_for_status()

    try:
        import pandas as pd
        import io
    except ImportError:
        print("需要安裝 pandas 與 lxml：pip install pandas lxml")
        raise

    tables = pd.read_html(io.StringIO(resp.text))
    if len(tables) == 0:
        print(f"  ⚠️ 頁面完全沒有回傳表格，可能是非交易日")
        return [], None

    # 🔶 已根據實測修正：資料表是回傳的第 1 個 <table>（index=0），
    # 欄位名稱裡可能夾雜空白字元（例如 '到期月份 (週別)'），統一先清除空白再比對。
    df = tables[0].copy()
    df.columns = [str(c).replace(" ", "").replace("\u3000", "") for c in df.columns]

    required_cols = ["契約到期日", "履約價", "買賣權", "*未沖銷契約量"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        print(f"  ⚠️ 缺少欄位：{missing}，目前欄位有：{list(df.columns)}")
        return [], None

    if "契約" in df.columns:
        df = df[df["契約"] == commodity_id]

    df = df[df["買賣權"].isin(["Call", "Put", "買權", "賣權"])]
    if df.empty:
        print(f"  ⚠️ {date_str} 沒有符合的資料列（可能是非交易日）")
        return [], None

    # 用「契約到期日」（YYYYMMDD 數字）找出最近到期的合約，比字串解析週別代碼更可靠
    df["契約到期日"] = pd.to_numeric(df["契約到期日"], errors="coerce")
    df = df.dropna(subset=["契約到期日"])
    nearest_expiry_date = int(df["契約到期日"].min())
    df = df[df["契約到期日"] == nearest_expiry_date]
    nearest_expiry = str(nearest_expiry_date)

    records = []
    for _, row in df.iterrows():
        strike = _clean_number(row["履約價"])
        if strike == 0:
            continue
        option_type = "call" if row["買賣權"] in ("Call", "買權") else "put"
        oi = _clean_number(row["*未沖銷契約量"])
        records.append({
            "date": date_str,
            "expiry": nearest_expiry,
            "strike": strike,
            "option_type": option_type,
            "open_interest": oi,
        })

    return records, nearest_expiry


def load_existing_dates():
    if not os.path.exists(CSV_PATH):
        return set()
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return {row["date"] for row in reader}


def append_records(records):
    if not records:
        return
    file_exists = os.path.exists(CSV_PATH)
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER)
        if not file_exists:
            writer.writeheader()
        for r in records:
            writer.writerow(r)


def is_weekend(dt):
    return dt.weekday() >= 5


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="抓取指定日期，格式 YYYY/MM/DD，預設為今天")
    args = parser.parse_args()

    target_date = args.date or datetime.now().strftime("%Y/%m/%d")
    target_dt = datetime.strptime(target_date, "%Y/%m/%d")
    if is_weekend(target_dt):
        print(f"{target_date} 是週末，略過。")
        sys.exit(0)

    existing_dates = load_existing_dates()
    if target_date in existing_dates:
        print(f"{target_date} 已經在 data/txo_strike_oi.csv 裡了，略過。")
        sys.exit(0)

    records, nearest_expiry = fetch_strike_oi(target_date)
    if records:
        print(f"  ✅ 成功抓到 {target_date}（合約 {nearest_expiry}）共 {len(records)} 筆履約價資料")
    append_records(records)
