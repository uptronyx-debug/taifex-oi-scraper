import re, html, requests, sys
sys.path.insert(0, ".")
import scraper_etf_fut as s
try: print("yuanta()", s.yuanta())
except Exception as e: print("yuanta ERR", repr(e))
t = s.get("https://www.yuantaetfs.com/product/detail/00631L/ratio").text
print("len", len(t))
txt = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))
for m in re.finditer(r"交易日期|臺股期貨|TX ", txt):
    print("TXT", txt[max(0, m.start()-150): m.start()+250]); 
for m in re.finditer(r"交易日期", t): print("RAW", t[m.start(): m.start()+300])
i = t.find("FutureWeights"); print("FW", t[i:i+1500])
