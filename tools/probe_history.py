import sys, os
sys.path.insert(0, os.getcwd())
import scraper_futures as F, scraper_foreign_hold as H
from scraper_margin import index_month
for d in ["2021/11/10", "2022/06/15", "2023/11/10", "2024/06/14"]:
    try:
        r = F.fetch(d); fx = [x for x in r if x["product"] == "TX" and x["investor_type"] == "foreign"]
        print("FUT", d, len(r), fx[:1])
    except Exception as e: print("FUT", d, "ERR", e)
    try: print("HOLD", d, H.fetch(d))
    except Exception as e: print("HOLD", d, "ERR", e)
    y, m = int(d[:4]), int(d[5:7]); print("IDX", d, index_month(y, m).get(d))
