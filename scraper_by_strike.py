"""
抓取 TAIFEX 每日行情報表（依商品別，臺指選擇權 TXO），
取得「最快到期合約」（不限月選或週選，純粹以契約到期日排序）
的各履約價未平倉量（Call / Put），累積寫入 data/txo_strike_oi.csv。

資料來源：https://www.taifex.com.tw/cht/3/optDailyMarketReport
"""

import csv
import io
import os
import sys
import time
from datetime import datetime

import pandas as pd
import requests

TARGET_URL = "https://www.taifex.com.tw/cht/3/optDailyMarketReport"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}

CSV_PATH = os.path.join("data", "txo_strike_oi.csv")
CSV_HEADER = ["date", "expiry", "expiry_code", "strike", "option_type", "open_interest"]

MAX_RETRIES = 4
RETRY_BACKOFF_SECONDS = 5  # 第一次失敗等 5 秒，之後倍增：5, 10, 20...


def _clean_number(value):
    """把 pandas 讀進來的欄位值（可能是字串、float、NaN）轉成乾淨的 int。"""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        if value != value:  # NaN 判斷
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


def _post_with_retry(payload, date_str):
    """
    對 TAIFEX 送出 POST 請求，失敗時自動重試。
    這份報表回傳的 HTML 頗大（約 4MB），偶爾會在傳輸中被截斷
    （requests.exceptions.ChunkedEncodingError / urllib3 ProtocolError:
    Response ended prematurely）。這通常是暫時性的網路問題，
    重試幾次通常就會成功，所以這裡做「失敗就等一下再試」的機制，
    試滿 MAX_RETRIES 次都還是失敗才真的放棄、把例外往外丟。
    """
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(
                TARGET_URL, data=payload, headers=HEADERS, timeout=30
            )
            resp.raise_for_status()
            # 有時候回應會被截斷成不完整的 HTML，但不一定會被 requests
            # 判定為例外，這裡額外檢查一下內容是否明顯不完整。
            if "</html>" not in resp.text.lower():
                raise requests.exceptions.ChunkedEncodingError(
                    "回應內容似乎被截斷（找不到結尾的 </html>）"
                )
            return resp
        except (
            requests.exceptions.ChunkedEncodingError,
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
        ) as exc:
            last_exc = exc
            wait = RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
            print(
                f"  ⚠️ 第 {attempt} 次嘗試抓取 {date_str} 失敗（{exc!r}），"
                f"{wait} 秒後重試..."
            )
            if attempt < MAX_RETRIES:
                time.sleep(wait)
    # 全部重試都失敗，把最後一次的例外往外丟出去
    raise last_exc


def fetch_strike_oi(date_str):
    """
    date_str 格式：YYYY/MM/DD
    回傳 (records, nearest_expiry_code)
    records 為 list[dict]，欄位對應 CSV_HEADER（不含 date，date 由呼叫端補上）
    """
    payload = {
        "queryDate": date_str,
        "commodity_id": "TXO",
        "MarketCode": "0",
    }

    resp = _post_with_retry(payload, date_str)

    tables = pd.read_html(io.StringIO(resp.text))
    if not tables:
        print(f"  ⚠️ {date_str} 找不到任何表格")
        return [], None

    df = tables[0]
    df.columns = [
        str(c).replace(" ", "").replace("　", "") for c in df.columns
    ]

    required_cols = {"到期月份(週別)", "履約價", "契約到期日"}
    missing = required_cols - set(df.columns)
    if missing:
        print(f"  ⚠️ {date_str} 缺少欄位：{missing}，實際欄位：{list(df.columns)}")
        return [], None

    # 只保留契約到期日「晚於」查詢日當天的合約（當天或已過期的合約不算
    # 是「最快到期」要觀察的對象）
    df["契約到期日"] = df["契約到期日"].apply(_clean_number)
    query_date_num = int(date_str.replace("/", ""))
    df = df[df["契約到期日"] > query_date_num]

    if df.empty:
        print(f"  ⚠️ 找不到到期日晚於 {date_str} 的合約（可能所有合約當天都已結算）")
        return [], None

    nearest_expiry_date = int(df["契約到期日"].min())
    nearest_expiry_code = df.loc[
        df["契約到期日"] == nearest_expiry_date, "到期月份(週別)"
    ].iloc[0]
    df = df[df["契約到期日"] == nearest_expiry_date]

    oi_col_candidates = [c for c in df.columns if "未沖銷" in c and "契約量" in c]
    if not oi_col_candidates:
        print(f"  ⚠️ {date_str} 找不到未沖銷契約量欄位，實際欄位：{list(df.columns)}")
        return [], None
    oi_col = oi_col_candidates[0]

    records = []
    for _, row in df.iterrows():
        strike = _clean_number(row.get("履約價"))
        option_type_raw = str(row.get("買賣權", "")).strip()
        if "買權" in option_type_raw or option_type_raw.upper() == "C":
            option_type = "call"
        elif "賣權" in option_type_raw or option_type_raw.upper() == "P":
            option_type = "put"
        else:
            # 有些列可能是合計列或非選擇權列，跳過
            continue
        oi = _clean_number(row.get(oi_col))
        records.append(
            {
                "expiry": nearest_expiry_date,
                "expiry_code": nearest_expiry_code,
                "strike": strike,
                "option_type": option_type,
                "open_interest": oi,
            }
        )

    return records, nearest_expiry_code


def append_records(date_str, records):
    if not records:
        print(f"  {date_str} 沒有資料可寫入")
        return

    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    file_exists = os.path.exists(CSV_PATH) and os.path.getsize(CSV_PATH) > 0

    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER)
        if not file_exists:
            writer.writeheader()
        for rec in records:
            writer.writerow(
                {
                    "date": date_str,
                    "expiry": rec["expiry"],
                    "expiry_code": rec["expiry_code"],
                    "strike": rec["strike"],
                    "option_type": rec["option_type"],
                    "open_interest": rec["open_interest"],
                }
            )
    print(f"  已寫入 {len(records)} 筆資料到 {CSV_PATH}")


def main():
    if len(sys.argv) > 1:
        target_date = sys.argv[1]
    else:
        target_date = datetime.now().strftime("%Y/%m/%d")

    print(f"抓取日期：{target_date}")
    records, nearest_expiry_code = fetch_strike_oi(target_date)
    if nearest_expiry_code is not None:
        print(f"最快到期合約代碼：{nearest_expiry_code}")
    append_records(target_date, records)


if __name__ == "__main__":
    main()
