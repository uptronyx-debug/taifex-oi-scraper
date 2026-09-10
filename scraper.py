"""
TAIFEX 臺指選擇權 三大法人未平倉 每日爬蟲
=========================================

抓取來源：https://www.taifex.com.tw/cht/3/callsAndPutsDate
只保留：臺指選擇權 × (自營商, 外資) × 未平倉餘額（買方/賣方/買賣差額）

用法：
    python scraper.py                    # 抓「今天」的資料，寫入 data/txo_oi.csv
    python scraper.py --date 2026/09/09  # 抓指定日期
    python scraper.py --backfill 2025/09/10 2026/09/09
                                          # 回補一段區間內所有交易日（會逐日呼叫，速度較慢）

⚠️ 重要假設（第一次執行前請務必確認）：
  本程式假設查詢用的是 POST 表單欄位 "queryDate"（格式 YYYY/MM/DD）。
  這是根據 TAIFEX 同類型頁面（optDailyMarketReport）已知可行的欄位名稱推測的，
  但 callsAndPutsDate 頁面本身未實測驗證過。

  第一次執行時，請看終端機印出的「除錯資訊」：
    - 如果印出「✅ 成功抓到 YYYY/MM/DD 的資料」→ 沒問題，可以正常使用。
    - 如果印出「⚠️ 抓到的日期跟預期不符」或「找不到表格」→
      代表欄位名稱猜錯了，請照下面步驟手動確認正確欄位名稱：
        1. 用 Chrome 打開 https://www.taifex.com.tw/cht/3/callsAndPutsDate
        2. 按 F12 打開開發者工具，切到 Network 分頁
        3. 在網頁上選一個日期、按查詢
        4. 在 Network 分頁找到 callsAndPutsDate 這筆請求，點開看 Payload/Form Data
        5. 把正確的欄位名稱貼給負責的工程師（或直接回來問我），
           修改本檔案最下方 PAYLOAD_FIELD_CANDIDATES 即可。
"""

import argparse
import csv
import os
import sys
import time
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

TARGET_URL = "https://www.taifex.com.tw/cht/3/callsAndPutsDate"
CSV_PATH = os.path.join(os.path.dirname(__file__), "data", "txo_oi.csv")

CSV_HEADER = [
    "date", "option_type", "investor_type",
    "oi_buy_volume", "oi_buy_value_k",
    "oi_sell_volume", "oi_sell_value_k",
    "oi_net_volume", "oi_net_value_k",
]

# 只保留這個商品、這些身份別
TARGET_PRODUCT = "臺指選擇權"
TARGET_INVESTORS = {"自營商": "dealer", "外資": "foreign"}
OPTION_TYPE_MAP = {"買權": "call", "賣權": "put"}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": TARGET_URL,
}

# 🔶 假設的表單欄位名稱。若第一個候選失敗，會依序嘗試下一個。
PAYLOAD_FIELD_CANDIDATES = [
    {"queryDate": "{date}", "commodity_id": ""},
    {"queryStartDate": "{date}", "commodity_id": ""},
    {"queryDate": "{date}"},
]


def _clean_number(text):
    """把 '1,395,631' / '-2,980' / '0' 轉成 int；空字串或 '-' 視為 0。"""
    text = (text or "").strip().replace(",", "")
    if text in ("", "-", "－"):
        return 0
    try:
        return int(text)
    except ValueError:
        # 有些欄位可能含全形符號或其他雜訊，最後手段：只留數字與負號
        cleaned = "".join(ch for ch in text if ch.isdigit() or ch == "-")
        return int(cleaned) if cleaned not in ("", "-") else 0


def _parse_table(html, expected_date):
    """
    手動解析 TAIFEX 的合併儲存格表格（比 pandas.read_html 更可控）。
    回傳 list[dict]，每筆是一列（商品+權別+身份別）的資料。
    """
    soup = BeautifulSoup(html, "html.parser")

    # 找出含有「身份別」字樣的表格（這是該頁面唯一符合的資料表）
    target_table = None
    for table in soup.find_all("table"):
        if "身份別" in table.get_text():
            target_table = table
            break
    if target_table is None:
        return None, None

    # 頁面上會顯示查詢到的日期，例如「日期2026/09/09」，抓出來做核對
    page_text = soup.get_text()
    displayed_date = None
    import re
    m = re.search(r"日期\s*(\d{4}/\d{1,2}/\d{1,2})", page_text)
    if m:
        displayed_date = m.group(1)

    rows = target_table.find_all("tr")
    records = []
    current_product = None
    current_option = None

    for tr in rows:
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if not cells:
            continue  # 表頭列或空列

        # 依照「這一列實際出現幾個 <td>」判斷哪些欄位被合併儲存格省略了
        if len(cells) >= 16:
            # 全新一列：序號, 商品名稱, 權別, 身份別, ...12個數字
            current_product = cells[1]
            current_option = cells[2]
            investor = cells[3]
            nums = cells[4:16]
        elif len(cells) == 14:
            # 商品名稱延續，權別是新的：權別, 身份別, ...12個數字
            current_option = cells[0]
            investor = cells[1]
            nums = cells[2:14]
        elif len(cells) == 13:
            # 商品名稱與權別都延續：身份別, ...12個數字
            investor = cells[0]
            nums = cells[1:13]
        else:
            continue  # 不符合預期格式的列，跳過（可能是頁尾備註列）

        if current_product != TARGET_PRODUCT:
            continue
        if investor not in TARGET_INVESTORS:
            continue
        if len(nums) != 12:
            continue

        nums = [_clean_number(x) for x in nums]
        # nums 順序：[交易買方口數,交易買方金額,交易賣方口數,交易賣方金額,
        #            交易差額口數,交易差額金額,
        #            未平倉買方口數,未平倉買方金額,未平倉賣方口數,未平倉賣方金額,
        #            未平倉差額口數,未平倉差額金額]
        oi_buy_volume, oi_buy_value = nums[6], nums[7]
        oi_sell_volume, oi_sell_value = nums[8], nums[9]
        oi_net_volume, oi_net_value = nums[10], nums[11]

        records.append({
            "date": expected_date,
            "option_type": OPTION_TYPE_MAP.get(current_option, current_option),
            "investor_type": TARGET_INVESTORS[investor],
            "oi_buy_volume": oi_buy_volume,
            "oi_buy_value_k": oi_buy_value,
            "oi_sell_volume": oi_sell_volume,
            "oi_sell_value_k": oi_sell_value,
            "oi_net_volume": oi_net_volume,
            "oi_net_value_k": oi_net_value,
        })

    return records, displayed_date


def fetch_one_day(date_str, session=None):
    """
    抓單一日期的資料。date_str 格式 'YYYY/MM/DD'。
    回傳 list[dict]（可能是空 list，代表當天非交易日或抓不到資料）。
    """
    sess = session or requests.Session()

    last_error = None
    for candidate in PAYLOAD_FIELD_CANDIDATES:
        payload = {k: (v.format(date=date_str) if isinstance(v, str) else v)
                   for k, v in candidate.items()}
        try:
            resp = sess.post(TARGET_URL, data=payload, headers=HEADERS, timeout=20)
            resp.raise_for_status()
        except requests.RequestException as e:
            last_error = e
            continue

        records, displayed_date = _parse_table(resp.text, date_str)

        if records is None:
            # 這個 payload 格式完全抓不到表格，換下一個候選欄位名稱
            continue

        if displayed_date and displayed_date != date_str:
            print(f"  ⚠️  要求日期 {date_str}，但頁面顯示日期是 {displayed_date}"
                  f"（可能是非交易日，TAIFEX 自動回傳最近一個交易日的資料，將略過此日）")
            return []

        if records:
            print(f"  ✅ 成功抓到 {date_str} 的資料（{len(records)} 筆）")
            return records
        else:
            print(f"  ⚠️  {date_str} 頁面有回應但沒有符合條件的資料列（可能是非交易日）")
            return []

    print(f"  ❌ {date_str} 所有候選欄位名稱都失敗了。"
          f"請依照檔案開頭的說明，用瀏覽器開發者工具確認正確的表單欄位名稱。"
          f"最後錯誤：{last_error}")
    return []


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
    return dt.weekday() >= 5  # 5=Sat, 6=Sun


def run_single(date_str):
    existing_dates = load_existing_dates()
    if date_str in existing_dates:
        print(f"{date_str} 已經在 data/txo_oi.csv 裡了，略過。")
        return
    records = fetch_one_day(date_str)
    append_records(records)


def run_backfill(start_str, end_str):
    start = datetime.strptime(start_str, "%Y/%m/%d")
    end = datetime.strptime(end_str, "%Y/%m/%d")
    existing_dates = load_existing_dates()

    session = requests.Session()
    d = start
    while d <= end:
        date_str = d.strftime("%Y/%m/%d")
        if is_weekend(d):
            d += timedelta(days=1)
            continue
        if date_str in existing_dates:
            d += timedelta(days=1)
            continue
        print(f"抓取 {date_str} ...")
        records = fetch_one_day(date_str, session=session)
        append_records(records)
        time.sleep(1.5)  # 禮貌性延遲，避免對期交所伺服器造成負擔
        d += timedelta(days=1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="抓取指定日期，格式 YYYY/MM/DD，預設為今天")
    parser.add_argument("--backfill", nargs=2, metavar=("START", "END"),
                         help="回補區間，例如 --backfill 2025/09/10 2026/09/09")
    args = parser.parse_args()

    if args.backfill:
        run_backfill(args.backfill[0], args.backfill[1])
    else:
        target_date = args.date or datetime.now().strftime("%Y/%m/%d")
        target_dt = datetime.strptime(target_date, "%Y/%m/%d")
        if is_weekend(target_dt):
            print(f"{target_date} 是週末，不是交易日，略過。")
            sys.exit(0)
        run_single(target_date)
