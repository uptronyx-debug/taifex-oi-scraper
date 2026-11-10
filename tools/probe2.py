import json, time, urllib.request
URLS = [
    "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date=20261106&selectType=ALL&response=json",
    "https://www.twse.com.tw/rwd/zh/fund/MI_QFIIS?date=20261106&selectType=ALLBUT0999&response=json",
    "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date=20261106&type=ALLBUT0999&response=json",
    "https://www.twse.com.tw/rwd/zh/fund/MI_QFIIS_cat?date=20261106&response=json",
]
for u in URLS:
    print("#####", u)
    try:
        b = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read()
        j = json.loads(b)
        print("bytes", len(b), {k: (v if not isinstance(v, list) else f"list[{len(v)}]") for k, v in j.items()})
        for t in j.get("tables", []):
            print("TABLE", t.get("title"), t.get("fields"), (t.get("data") or [])[:3], "rows", len(t.get("data") or []))
        if "fields" in j:
            print("FIELDS", j["fields"]); print((j.get("data") or [])[:3]); print("rows", len(j.get("data") or []))
    except Exception as e:
        print("ERR", e)
    time.sleep(4)
