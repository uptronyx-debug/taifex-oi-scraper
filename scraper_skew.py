"""
抓取期交所「臺指選擇權每日交易行情」並計算情緒刻度（恐慌／FOMO）。
資料來源：https://www.taifex.com.tw/cht/3/optDataDown
日檔輸出：data/txo_opt_daily/YYYY-MM-DD.csv.gz
計算輸出：data/txo_skew.csv、data/txo_skew.json

用法：
    python scraper_skew.py                    # 抓今天並視需要重算
    python scraper_skew.py --date 2026-11-27  # 指定日期（ISO YYYY-MM-DD）
    python scraper_skew.py --recalc           # 直接依現有資料重算 csv 與 json
"""

import argparse
import csv
import gzip
import io
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import skew_gauge  # noqa: E402

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(ROOT, "data"))
OPT_DIR = os.path.join(DATA_DIR, "txo_opt_daily")
TAIEX_CSV = os.path.join(DATA_DIR, "taiex.csv")
SKEW_CSV = os.path.join(DATA_DIR, "txo_skew.csv")
SKEW_JSON = os.path.join(DATA_DIR, "txo_skew.json")

TARGET_URL = "https://www.taifex.com.tw/cht/3/optDataDown"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}
MAX_RETRIES = 4
RETRY_BACKOFF_SECONDS = 5  # 第一次失敗等 5 秒，之後倍增：5, 10, 20...
TAIPEI = timezone(timedelta(hours=8))

OPT_FIELDS = ["d", "contract", "exp_date", "strike", "cp", "oi", "settle", "close", "bid", "ask"]


def now_taipei():
    fake = os.environ.get("FAKE_NOW")
    if fake:
        return datetime.strptime(fake, "%Y/%m/%d %H:%M").replace(tzinfo=TAIPEI)
    return datetime.now(TAIPEI)


def _clean_float_str(val):
    s = val.strip().replace(",", "")
    if s in ("", "-", "－"):
        return ""
    return str(float(s))


def _clean_int_str(val):
    s = val.strip().replace(",", "")
    if s in ("", "-", "－"):
        return ""
    return str(int(float(s)))


def _parse_exp_date(val):
    s = val.strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return ""


def _post_with_retry(payload, date_str):
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(TARGET_URL, data=payload, headers=HEADERS, timeout=30)
            resp.raise_for_status()
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
    raise last_exc


def fetch_opt_day(date_slash):
    """抓取指定日期（YYYY/MM/DD）臺指選擇權一般交易時段行情。未公布或休市回傳 []。"""
    target_iso = date_slash.replace("/", "-")
    payload = {
        "down_type": "1",
        "commodity_id": "TXO",
        "commodity_id2": "",
        "queryStartDate": date_slash,
        "queryEndDate": date_slash,
    }
    resp = _post_with_retry(payload, date_slash)
    text = resp.content.decode("cp950", errors="replace")
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header or header[0].lstrip("\ufeff").strip() != "交易日期":
        return []

    records = []
    for row in reader:
        if len(row) <= 17:
            continue
        if row[17].strip() != "一般":
            continue
        d_raw = row[0].strip().replace("/", "-")
        if d_raw != target_iso:
            continue
        cp_raw = row[4].strip()
        if "買" in cp_raw or cp_raw.upper() == "C":
            cp = "C"
        elif "賣" in cp_raw or cp_raw.upper() == "P":
            cp = "P"
        else:
            continue
        strike = _clean_float_str(row[3])
        if not strike:
            continue
        exp_date = _parse_exp_date(row[20]) if len(row) > 20 else ""
        records.append({
            "d": target_iso,
            "contract": row[2].strip(),
            "exp_date": exp_date,
            "strike": strike,
            "cp": cp,
            "oi": _clean_int_str(row[11]),
            "settle": _clean_float_str(row[10]),
            "close": _clean_float_str(row[8]),
            "bid": _clean_float_str(row[12]),
            "ask": _clean_float_str(row[13]),
        })

    if not records:
        return []
    cps = {r["cp"] for r in records}
    if len(records) < 500 or cps != {"C", "P"}:
        print(f"  ⚠️ {target_iso} 回應不完整，視為尚未公布（{len(records)} 筆，cp={sorted(cps)}）")
        return []
    if not any(r["settle"] or r["close"] or (r["oi"] not in ("", "0")) for r in records):
        return []
    return records


def write_daily_gz(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=OPT_FIELDS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    data = buf.getvalue().encode("utf-8")
    with open(path, "wb") as raw_f:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_f, mtime=0) as gz:
            gz.write(data)


def skew_last_date(csv_path):
    if not os.path.exists(csv_path):
        return None
    last = ""
    with open(csv_path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s:
                last = s
    if not last or last.startswith("d,"):
        return None
    return last.split(",", 1)[0]


def opt_has_date(opt_dir, target_iso):
    if not os.path.isdir(opt_dir):
        return False
    prefix = (target_iso + ",").encode("utf-8")
    for name in sorted(os.listdir(opt_dir)):
        if not name.endswith(".csv.gz"):
            continue
        p = os.path.join(opt_dir, name)
        with gzip.open(p, "rb") as f:
            for line in f:
                if line.startswith(prefix):
                    return True
    return False


def taiex_has_date(taiex_csv, target_slash):
    if not os.path.exists(taiex_csv):
        return False
    target_iso = target_slash.replace("/", "-")
    with open(taiex_csv, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            d = (r.get("date") or "").strip()
            if (d == target_slash or d == target_iso) and (r.get("taiex") or "").strip():
                return True
    return False


def run(target_iso=None, force_recalc=False):
    if target_iso is None:
        target_iso = now_taipei().strftime("%Y-%m-%d")
    target_slash = target_iso.replace("-", "/")

    if not force_recalc:
        if skew_last_date(SKEW_CSV) == target_iso and os.path.exists(SKEW_JSON):
            print(f"{target_iso} 情緒刻度已存在，略過")
            return True

        if not opt_has_date(OPT_DIR, target_iso):
            records = fetch_opt_day(target_slash)
            if not records:
                print(f"{target_iso} 期交所選擇權行情尚未公布或休市，略過")
                return False
            out_gz = os.path.join(OPT_DIR, f"{target_iso}.csv.gz")
            write_daily_gz(out_gz, records)
            print(f"{target_iso} 已寫入期權日檔（{len(records)} 筆）")

        if not taiex_has_date(TAIEX_CSV, target_slash):
            print(f"{target_iso} 期權行情已存，等待加權指數收盤，暫不重算")
            return False

    rows = skew_gauge.run_csv(OPT_DIR, TAIEX_CSV)
    skew_gauge.write_outputs(rows, SKEW_CSV, SKEW_JSON)
    last = rows[-1] if rows else {}
    print(
        f"情緒刻度已更新至 {last.get('d')}（共 {len(rows)} 天，"
        f"恐慌 {last.get('score')}／FOMO {last.get('fomo')}）"
    )
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="指定交易日 YYYY-MM-DD（預設台北今天）")
    ap.add_argument("--recalc", action="store_true", help="直接依現有資料重算 csv 與 json")
    args = ap.parse_args()
    run(target_iso=args.date, force_recalc=args.recalc)


if __name__ == "__main__":
    main()
