import re, requests
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
s = requests.Session(); s.headers.update(H)
v = s.get("https://www.taifex.com.tw/cht/3/futContractsDateView", timeout=60).text
for f in re.findall(r"<form[^>]*>.*?</form>", v, re.S):
    print("FORM", re.findall(r"<form[^>]*>", f), re.findall(r'<input[^>]*>', f)[:30])
for m in re.finditer(r"(firstDate|lastDate|DateDown|三年|3年|1998|2007)", v):
    print("CTX", v[max(0, m.start()-200):m.end()+200].replace("\n", " "))
for (a, b) in [("2021/11/01", "2021/11/05"), ("2024/11/04", "2024/11/06")]:
    for extra in [{}, {"firstDate": "2007/07/02 00:00", "lastDate": "2026/11/10 00:00"}]:
        d = {"down_type": "1", "queryStartDate": a, "queryEndDate": b, "commodityId": "TXF", **extra}
        r = s.post("https://www.taifex.com.tw/cht/3/futContractsDateDown", data=d, timeout=60)
        t = r.content.decode("big5", "replace") if "csv" in r.headers.get("content-type", "") or "octet" in r.headers.get("content-type", "") else r.text
        print("DOWN", a, b, extra, r.headers.get("content-type"), len(r.content)); print(t[:700])
