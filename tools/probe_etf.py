import json, re, requests, time, html
from playwright.sync_api import sync_playwright
UA={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36","Accept-Language":"zh-TW,zh;q=0.9","Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
r=requests.post("https://www.capitalfund.com.tw/CFWeb/api/etf/buyback",json={"fundId":"094","date":"2024-11-01"},headers={**UA,"Content-Type":"application/json"},timeout=60)
js=r.json(); d=js["data"]; print("capital keys",list(d.keys())); print("pcf",json.dumps(d["pcf"],ensure_ascii=False)[:600]); print("futures",json.dumps(d.get("futures"),ensure_ascii=False)[:1500])
for k,v in d.items():
    s=json.dumps(v,ensure_ascii=False)
    if "期" in s: print("KEY with 期",k,s[:800])

for u in ["https://www.cathaysite.com.tw/ETF/detail/E87?tab=etf3","https://www.cathaysite.com.tw/ETF/detail/E87"]:
    try:
        r=requests.get(u,headers=UA,timeout=30); print("\nCATHAY requests",u,r.status_code,len(r.text)); t=r.text
        print(re.sub(r"\s+"," ",t[:1500]))
        print("api-like:",sorted(set(re.findall(r"[\"'](/?(?:api|API|Api)[^\"']{3,120})[\"']",t)))[:40])
        print("scripts:",re.findall(r"<script[^>]+src=[\"']([^\"']+)",t)[:30])
    except Exception as e: print("ERR",e)

def text(u):
    r=requests.get(u,headers=UA,timeout=30); r.encoding=r.apparent_encoding
    return r.status_code, re.sub(r"\s+"," ",html.unescape(re.sub(r"<[^>]+>"," ",r.text)))
for u in ["https://www.moneydj.com/ETF/X/Basic/Basic0007a.xdjhtm?etfid=00663L.TW","https://www.moneydj.com/ETF/X/Basic/Basic0007B.xdjhtm?etfid=00663L.TW","https://www.moneydj.com/ETF/X/Basic/Basic0007a.xdjhtm?etfid=00631L.TW"]:
    try:
        c,t=text(u); i=t.find("期貨"); print("\nMONEYDJ",u,c, t[max(0,i-800):i+1200])
    except Exception as e: print("ERR",u,e)

def sniff(url, wait=8000, click=None):
    print("\n#####", url)
    with sync_playwright() as p:
        b=p.chromium.launch(args=["--disable-blink-features=AutomationControlled"]); pg=b.new_page(user_agent=UA["User-Agent"],locale="zh-TW")
        seen=[]
        def on(resp):
            try:
                if resp.request.resource_type in("xhr","fetch") and "google" not in resp.url:
                    body=""
                    try: body=resp.text()[:1500]
                    except Exception: pass
                    seen.append((resp.request.method,resp.url,resp.request.post_data,body))
            except Exception: pass
        pg.on("response",on)
        try: pg.goto(url,timeout=60000,wait_until="networkidle")
        except Exception as e: print("goto",e)
        pg.wait_for_timeout(wait)
        txt=pg.inner_text("body"); i=txt.find("期貨"); print("BODY:", re.sub(r"\s+"," ",txt[max(0,i-400):i+1500]))
        print("inputs:",[ (e.get_attribute("type"),e.get_attribute("placeholder"),e.get_attribute("value"),e.get_attribute("class")) for e in pg.query_selector_all("input")][:15])
        for m,u,pd,body in seen:
            print("--",m,u[:300]); 
            if pd: print("   POST:",pd[:300])
            print("   ",re.sub(r"\s+"," ",body)[:600])
        b.close()
sniff("https://www.cathaysite.com.tw/ETF/detail/E87?tab=etf3")
sniff("https://www.yuantaetfs.com/product/detail/00631L/PCF")
