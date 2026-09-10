"""
一次性診斷小工具：抓出 callsAndPutsDate 頁面表單裡真正的欄位名稱與 ASP.NET 隱藏欄位。

用法：
    python inspect_form.py

跑完後把印出來的全部內容複製貼給我，我再依據真實欄位名稱修正 scraper.py。
這支程式不會存任何資料，純粹只是偵查用途，用完可以刪掉。
"""

import requests
from bs4 import BeautifulSoup

TARGET_URL = "https://www.taifex.com.tw/cht/3/callsAndPutsDate"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}

resp = requests.get(TARGET_URL, headers=HEADERS, timeout=20)
resp.raise_for_status()
soup = BeautifulSoup(resp.text, "html.parser")

print("=" * 60)
print("找到的 <form> 數量：", len(soup.find_all("form")))
for i, form in enumerate(soup.find_all("form")):
    print(f"\n--- form[{i}] action={form.get('action')} method={form.get('method')} ---")

print("\n" + "=" * 60)
print("所有 <input> 欄位（name / type / value 前 50 字）：")
for inp in soup.find_all("input"):
    name = inp.get("name")
    itype = inp.get("type")
    value = (inp.get("value") or "")[:50]
    if name:
        print(f"  name={name!r:40} type={itype!r:10} value={value!r}")

print("\n" + "=" * 60)
print("所有 <select> 欄位（name 及選項 value）：")
for sel in soup.find_all("select"):
    name = sel.get("name")
    print(f"  name={name!r}")
    for opt in sel.find_all("option")[:10]:
        print(f"      option value={opt.get('value')!r} text={opt.get_text(strip=True)!r}")

print("\n" + "=" * 60)
print("頁面標題：", soup.title.get_text(strip=True) if soup.title else None)
