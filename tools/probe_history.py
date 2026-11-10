import sys, os, requests
sys.path.insert(0, os.getcwd())
import scraper_futures as F
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
for d in ["2023/10/02", "2023/11/01", "2023/11/09"]:
    try: print("FUT", d, len(F.fetch(d)))
    except Exception as e: print("FUT", d, "ERR", e)
for s, e in [("2021/11/01", "2021/11/05"), ("2019/01/02", "2019/01/04"), ("2023/11/06", "2023/11/08")]:
    for cid in ["TXF", ""]:
        try:
            r = requests.post("https://www.taifex.com.tw/cht/3/futContractsDateDown", data={"queryStartDate": s, "queryEndDate": e, "commodityId": cid}, headers=H, timeout=60)
            t = r.content.decode("big5", "replace") if b"<html" not in r.content[:200].lower() else r.text
            print("DOWN", s, e, repr(cid), r.status_code, r.headers.get("content-type"), len(r.content))
            print(t[:900])
        except Exception as ex: print("DOWN ERR", ex)
