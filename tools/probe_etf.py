import re, html, requests
UA={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
for e in ["00631L","00685L","00675L","00663L"]:
    r=requests.get(f"https://www.moneydj.com/ETF/X/Basic/Basic0007B.xdjhtm?etfid={e}.TW",headers=UA,timeout=30); r.encoding=r.apparent_encoding or "utf-8"
    t=re.sub(r"\s+"," ",html.unescape(re.sub(r"<[^>]+>"," ",r.text)))
    m=re.search(r"資料日期[:：]\s*(\d{4}/\d{1,2}/\d{1,2})",t)
    print(e, m and m.group(1)); print("   ", [t[max(0,x.start()-40):x.start()+80] for x in re.finditer(r"\(FI|期貨", t)][:6])
