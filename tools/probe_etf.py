import json, re, requests, time
from playwright.sync_api import sync_playwright
UA={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}

def cap(d):
    try:
        r=requests.post("https://www.capitalfund.com.tw/CFWeb/api/etf/buyback",json={"fundId":"094","date":d},headers={**UA,"Content-Type":"application/json"},timeout=30)
        js=r.json(); p=js["data"]["pcf"]
        lots=sum(int(round(f.get("lot") or 0)) for f in js["data"].get("futures") or [] if str(f.get("txEname","")).startswith("TX"))
        print("capital",d,"->",p.get("date2"),lots)
    except Exception as e: print("capital",d,"ERR",repr(e)[:200])
for d in ["2025-09-30","2024-11-01","2023-11-01","2022-11-01","2021-11-01","2021-10-01","2020-11-02"]:
    cap(d); time.sleep(1)

def sniff(url, wait=8000):
    print("\n#####", url)
    with sync_playwright() as p:
        b=p.chromium.launch(); pg=b.new_page(user_agent=UA["User-Agent"])
        seen=[]
        def on(resp):
            try:
                ct=resp.headers.get("content-type","")
                if resp.request.resource_type in("xhr","fetch") or "json" in ct:
                    body=""
                    try: body=resp.text()[:1500]
                    except Exception: pass
                    seen.append((resp.request.method,resp.url,resp.request.post_data,body))
            except Exception: pass
        pg.on("response",on)
        try: pg.goto(url,timeout=60000,wait_until="networkidle")
        except Exception as e: print("goto",e)
        pg.wait_for_timeout(wait)
        txt=pg.inner_text("body")
        for m in re.finditer(r"(期貨|TX|臺股|台股|日期)",txt):
            pass
        i=txt.find("期貨"); print("BODYTEXT around 期貨:", re.sub(r"\s+"," ",txt[max(0,i-600):i+900]))
        dates=set(re.findall(r"\d{4}/\d{1,2}/\d{1,2}",txt)); print("dates in text:",sorted(dates)[:20])
        # date pickers?
        print("inputs:",[ (e.get_attribute("type"),e.get_attribute("placeholder"),e.get_attribute("value")) for e in pg.query_selector_all("input")][:15])
        print("selects:",[ e.inner_text()[:200] for e in pg.query_selector_all("select")][:5])
        for m,u,pd,body in seen:
            print("\n--",m,u); 
            if pd: print("   POST:",pd[:300])
            print("   ",re.sub(r"\s+"," ",body)[:1200])
        b.close()

sniff("https://www.cathaysite.com.tw/ETF/detail/E87?tab=etf3")
sniff("https://www.yuantaetfs.com/product/detail/00631L/ratio")
sniff("https://websys.fsit.com.tw/FubonETF/Trade/ConstituentStock.aspx?lan=TW&stkId=00675L",3000)
