"""
三檔台股正 2 ETF 的「臺股期貨（大台）」多單口數
  00631L 元大台灣50正2   https://www.yuantaetfs.com/product/detail/00631L/ratio （頁面內嵌資料，只有最新一天）
  00685L 群益臺灣加權正2 https://www.capitalfund.com.tw/CFWeb/api/etf/buyback （可查歷史）
  00675L 富邦臺灣加權正2 https://websys.fsit.com.tw/FubonETF/Trade/ConstituentStock.aspx （只有最新一天）
只計大台（元大另有台灣50ETF股票期貨，不算）；跨月轉倉期間同時持有兩個月份時會加總。
資料日期＝持倉所屬交易日（收盤後的部位）。
輸出：data/etf_fut.csv  date, etf, lots

用法：
    python scraper_etf_fut.py                # 抓最新，只寫入「資料日期＝今天」的
    python scraper_etf_fut.py --test         # 只印出，不寫檔
    python scraper_etf_fut.py --backfill-capital 2025/10/01 2026/11/10   # 群益歷史
"""

import argparse
import csv
import html as htmlmod
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "data", "etf_fut.csv")
HEADER = ["date", "etf", "lots"]
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
TPE = timezone(timedelta(hours=8))


def get(url, **kw):
    for i in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=30, **kw)
            r.raise_for_status()
            return r
        except Exception as e:
            err = e
            time.sleep(3)
    raise err


def norm_date(s):
    m = re.search(r"(\d{4})\D(\d{1,2})\D(\d{1,2})", s)
    return f"{m.group(1)}/{int(m.group(2)):02d}/{int(m.group(3)):02d}" if m else None


def yuanta():
    """00631L：頁面 HTML 內嵌 FutureWeights；日期取頁面上的「交易日期」。"""
    t = get("https://www.yuantaetfs.com/product/detail/00631L/ratio").text
    # 主要：伺服器端渲染的表格文字「TX 臺股期貨 55300 158.49 202611」，依契約月份去重（手機/桌機版各一份）
    txt = re.sub(r"\s+", " ", htmlmod.unescape(re.sub(r"<[^>]+>", " ", t)))
    by_ym = {ym: int(q.replace(",", "")) for q, ym in
             re.findall(r"\bTX 臺股期貨 ([\d,]+) [\d.]+ (\d{6})", txt)}
    if not by_ym:
        # 備用：內嵌資料 FutureWeights（臺股期貨字樣可能被壓縮成變數，所以也認 TAIEX FUTURE）
        i = t.find("FutureWeights:[")
        seg = t[i: t.find("]", i)] if i >= 0 else ""
        for k, obj in enumerate(re.findall(r"\{[^{}]*\}", seg)):
            if "臺股期貨" in obj or "TAIEX FUTURE" in obj:
                q = re.search(r"qty:(\d+)", obj)
                if q:
                    by_ym[k] = int(q.group(1))
    lots = sum(by_ym.values())
    if not lots:
        raise RuntimeError("元大找不到臺股期貨口數")
    # 日期：頁面上的「交易日期: 2026/11/10」（伺服器端已渲染）
    m = re.search(r"交易日期[:：](?:\s|<[^>]+>)*(\d{4}/\d{1,2}/\d{1,2})", t)
    d = norm_date(m.group(1)) if m else None
    return d, lots


def capital(query_date=None):
    """00685L：回傳 (資料日期, 口數)。query_date 為申購買回清單日期（下一交易日），date2 才是持倉日。"""
    body = {"fundId": "094", "date": query_date}
    for k in range(3):
        try:
            r = requests.post("https://www.capitalfund.com.tw/CFWeb/api/etf/buyback", json=body,
                              headers={**UA, "Content-Type": "application/json"}, timeout=30)
            r.raise_for_status()
            js = r.json()
            break
        except Exception as e:
            err = e
            time.sleep(3)
    else:
        raise err
    pcf = js["data"]["pcf"]
    lots = sum(int(round(f.get("lot") or 0)) for f in js["data"].get("futures") or []
               if str(f.get("txEname", "")).startswith("TX"))
    return norm_date(pcf.get("date2") or ""), lots


def fubon():
    t = get("https://websys.fsit.com.tw/FubonETF/Trade/ConstituentStock.aspx?lan=TW&stkId=00675L").text
    txt = htmlmod.unescape(re.sub(r"<[^>]+>", " ", t))
    txt = re.sub(r"\s+", " ", txt)
    m = re.search(r"資料日期[:：]\s*(\d{4}/\d{1,2}/\d{1,2})", txt)
    d = norm_date(m.group(1)) if m else None
    by_ym = {ym: int(n.replace(",", "")) for ym, n in
             re.findall(r"(\d{4}/\d{1,2})\s*台股指數期貨\s+([\d,]+)", txt)}
    lots = sum(by_ym.values())
    if not lots:
        raise RuntimeError("富邦找不到台股指數期貨口數")
    return d, lots


SOURCES = [("00631L", yuanta), ("00685L", capital), ("00675L", fubon)]


def load():
    rows = {}
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rows[(r["date"], r["etf"])] = int(r["lots"])
    return rows


def save(rows):
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    order = {k: i for i, (k, _) in enumerate(SOURCES)}
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for (d, e) in sorted(rows, key=lambda k: (k[0], order.get(k[1], 9))):
            w.writerow([d, e, rows[(d, e)]])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--backfill-capital", nargs=2)
    a = ap.parse_args()
    rows = load()

    if a.backfill_capital:
        start, end = [datetime.strptime(x, "%Y/%m/%d") for x in a.backfill_capital]
        d = start + timedelta(days=1)
        added = 0
        while d <= end + timedelta(days=7):
            if d.weekday() < 5:
                try:
                    dd, lots = capital(d.strftime("%Y-%m-%d"))
                    if dd and lots and start.strftime("%Y/%m/%d") <= dd <= end.strftime("%Y/%m/%d") \
                            and (dd, "00685L") not in rows:
                        rows[(dd, "00685L")] = lots
                        added += 1
                        print(dd, lots)
                except Exception as e:
                    print("跳過", d.date(), e)
                time.sleep(0.5)
            d += timedelta(days=1)
        save(rows)
        print(f"群益補了 {added} 天")
        return

    today = datetime.now(TPE).strftime("%Y/%m/%d")
    changed = False
    for etf, fn in SOURCES:
        try:
            d, lots = fn()
        except Exception as e:
            print(f"{etf} 失敗：{e}")
            continue
        print(f"{etf} 資料日期 {d} 大台多單 {lots} 口")
        if a.test:
            continue
        if d != today:
            print(f"  → 不是今天（{today}），不寫入")
            continue
        if (d, etf) in rows:
            continue
        rows[(d, etf)] = lots
        changed = True
    if changed:
        save(rows)
        print("已寫入", OUT)
    elif not a.test:
        print("沒有新資料可寫入")


if __name__ == "__main__":
    main()
