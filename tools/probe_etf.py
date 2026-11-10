import json, sys
from playwright.sync_api import sync_playwright
URLS = {
    "00631L": "https://www.yuantaetfs.com/product/detail/00631L/ratio",
    "00685L": "https://www.capitalfund.com.tw/etf/product/detail/094/portfolio",
    "00675L": "https://websys.fsit.com.tw/FubonETF/Trade/ConstituentStock.aspx?lan=TW&stkId=00675L",
}
with sync_playwright() as p:
    b = p.chromium.launch()
    for k, u in URLS.items():
        print("#" * 30, k, u)
        pg = b.new_page()
        hits = []
        def on_resp(r):
            try:
                ct = r.headers.get("content-type", "")
                if r.request.resource_type in ("xhr", "fetch") or "json" in ct:
                    body = r.text()
                    hits.append((r.request.method, r.url, r.request.post_data, body))
            except Exception as e:
                pass
        pg.on("response", on_resp)
        try:
            pg.goto(u, wait_until="networkidle", timeout=60000)
            pg.wait_for_timeout(3000)
        except Exception as e:
            print("GOTO ERR", e)
        for m, url, pdata, body in hits:
            flag = any(w in body for w in ["期貨", "TX", "臺股期", "台股期", "Futures", "FUT"])
            print(f"--- {m} {url} post={str(pdata)[:300]} len={len(body)} futflag={flag}")
            if flag:
                i = max(body.find("期貨"), body.find("臺股期"), 0)
                print("   SNIP:", body[max(0, i - 600): i + 900].replace("\n", " "))
        txt = pg.inner_text("body")
        i = txt.find("期貨")
        print("PAGE TEXT around 期貨:", txt[max(0, i - 400): i + 800].replace("\n", " | ") if i >= 0 else txt[:600].replace("\n", " | "))
        pg.close()
    b.close()
