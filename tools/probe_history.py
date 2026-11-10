import requests, json
u = "https://api.finmindtrade.com/api/v4/data"
for s, e in [("2021/11/01", "2021/11/03"), ("2024-11-04", "2024-11-04")]:
    r = requests.get(u, params={"dataset": "TaiwanFuturesInstitutionalInvestors", "data_id": "TX", "start_date": s.replace("/", "-"), "end_date": e.replace("/", "-")}, timeout=60)
    print(r.status_code, r.text[:1500])
r = requests.get(u, params={"dataset": "TaiwanFuturesInstitutionalInvestors", "data_id": "TX", "start_date": "2021-11-01", "end_date": "2023-11-10"}, timeout=120)
j = r.json(); d = j.get("data", [])
print("RANGE", r.status_code, j.get("msg"), len(d), d[:1], d[-1:] if d else None)
