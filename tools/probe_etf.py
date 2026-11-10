import re, requests, subprocess, sys
UA={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
print(subprocess.run([sys.executable,"scraper_etf_fut.py","--test"],capture_output=True,text=True).stdout)
t=requests.get("https://www.yuantaetfs.com/product/detail/00631L/ratio",headers=UA,timeout=30).text
print("YLEN",len(t))
i=t.find("FutureWeights")
print("Y_AROUND_FW:", t[max(0,i-2500):i+400])
for m in re.finditer(r'\d{4}(\\u002F|/|-)\d{2}(\\u002F|/|-)\d{2}', t):
    print("YDATE", t[max(0,m.start()-80):m.end()+20].replace("\n"," "))
