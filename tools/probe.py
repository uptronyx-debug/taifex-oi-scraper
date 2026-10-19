"""一次性偵查：印出期貨三大法人頁面與證交所三大法人 API 的結構（不寫任何資料）"""
import io, json, re, sys
import pandas as pd, requests
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0 Safari/537.36"}
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)

def taifex(date, payload_extra):
    url = "https://www.taifex.com.tw/cht/3/futContractsDate"
    p = {"queryDate": date, **payload_extra}
    r = requests.post(url, data=p, headers={**H, "Referer": url}, timeout=30)
    m = re.search(r"日期\s*(\d{4}/\d{1,2}/\d{1,2})", r.text)
    print(f"\n=== TAIFEX POST {p} status={r.status_code} len={len(r.text)} 頁面日期={m.group(1) if m else None}")
    return r.text

html = taifex("2026/10/16", {"commodityId": ""})
tables = pd.read_html(io.StringIO(html))
print("tables:", len(tables))
for i, t in enumerate(tables):
    print(f"--- table[{i}] shape={t.shape}")
    print(t.head(12).to_string())
for d in ["2026/10/15", "2026/10/08"]:
    for extra in [{}, {"commodityId": ""}, {"queryStartDate": d, "queryEndDate": d}]:
        h = taifex(d, extra)
        idx = h.find("臺股期貨")
        print("  snippet:", re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h[idx:idx+1500]))[:400])

for d in ["20261016", "20261008"]:
    url = f"https://www.twse.com.tw/rwd/zh/fund/BFI82U?type=day&dayDate={d}&response=json"
    r = requests.get(url, headers=H, timeout=30)
    print(f"\n=== TWSE {d} status={r.status_code}")
    print(json.dumps(r.json(), ensure_ascii=False)[:1500])
