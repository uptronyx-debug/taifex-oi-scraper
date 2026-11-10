import json, re
from playwright.sync_api import sync_playwright
def ctx(txt, w, n=3, a=300, b=700):
    out=[]; i=0
    for _ in range(n):
        i=txt.find(w,i)
        if i<0: break
        out.append(txt[max(0,i-a):i+b].replace("\n"," | ")); i+=len(w)
    return out
with sync_playwright() as p:
    br = p.chromium.launch()
    # ---- Yuanta
    for u in ["https://www.yuantaetfs.com/product/detail/00631L/ratio","https://www.yuantaetfs.com/product/detail/00631L/PCF"]:
        print("#"*30,u)
        pg=br.new_page(); hits=[]
        pg.on("response", lambda r: hits.append(r) if ("etfapi" in r.url or "yuantaetfs.com/api" in r.url) else None)
        try:
            pg.goto(u, wait_until="networkidle", timeout=60000)
            for _ in range(4):
                pg.mouse.wheel(0,3000); pg.wait_for_timeout(2500)
        except Exception as e: print("ERR",e)
        for r in hits:
            try: body=r.text()
            except Exception: body=""
            print("---",r.request.method,r.url[:400],"post=",str(r.request.post_data)[:200],"len",len(body))
            for s in ctx(body,"口數",1,300,600)+ctx(body,"TXF",1,300,600)+ctx(body,"臺股期",1,300,600)+ctx(body,"台指",1,300,600): print("   B:",s)
        txt=pg.inner_text("body")
        for w in ["口數","臺股期","台股期","台指","TXF"]:
            for s in ctx(txt,w,2): print("TXT",w,":",s)
        html=pg.content()
        for w in ["TXF","口數","FUT"]:
            for s in ctx(html,w,2,200,400): print("HTML",w,":",s)
        pg.close()
    # ---- Capital history test
    pg=br.new_page(); pg.goto("https://www.capitalfund.com.tw/etf/product/detail/094/portfolio", wait_until="networkidle", timeout=60000)
    for d in ["2026-11-03","2026/11/03","20261103","2026-10-01"]:
        r=pg.evaluate("""async d=>{const r=await fetch('/CFWeb/api/etf/buyback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({fundId:'094',date:d})});return await r.text()}""", d)
        m=re.findall(r'"(date1|date2)":"([^"]*)"',r); f=ctx(r,"futu",1,100,500)+ctx(r,"口",1,200,300)
        print("CAP",d,m,len(r),f[:1])
    r=pg.evaluate("""async()=>{const r=await fetch('/CFWeb/api/etf/buyback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({fundId:'094',date:null})});return await r.text()}""")
    print("CAPFULL", r[:6000])
    pg.close()
    # ---- Fubon form
    pg=br.new_page(); pg.goto("https://websys.fsit.com.tw/FubonETF/Trade/ConstituentStock.aspx?lan=TW&stkId=00675L", wait_until="networkidle", timeout=60000)
    for el in pg.query_selector_all("input,select"):
        print("FORM", el.evaluate("e=>e.tagName+' '+e.name+' '+e.id+' '+e.type+' '+(e.value||'').slice(0,40)"))
    for u in ["https://websys.fsit.com.tw/FubonETF/Trade/ConstituentStock.aspx?lan=TW&stkId=00675L&date=2026/11/03",
              "https://websys.fsit.com.tw/FubonETF/Trade/ConstituentStock.aspx?lan=TW&stkId=00675L&sDate=2026/11/03"]:
        pg.goto(u, wait_until="networkidle", timeout=60000); t=pg.inner_text("body")
        print("FUBQ",u, ctx(t,"資料日期",1,0,30), ctx(t,"WTX",1,0,60))
    br.close()
