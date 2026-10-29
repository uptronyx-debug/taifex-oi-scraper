"""
每日排程的「事前檢查」與「事後驗證」。

用法：
    python tools/check_today.py pre    # 決定這次要不要跑（輸出 skip=true/false 給 GitHub Actions）
    python tools/check_today.py post   # 跑完後確認今天的資料是否齊全，決定綠勾或紅叉

判斷規則：
  事前：週末、證交所公布的休市日 → 略過（綠勾）
        今天五份資料都已經有了 → 略過（綠勾）
  事後：五份都有 → 綠勾
        五份都沒有 → 代表今天沒有任何交易資料（例如颱風臨時休市，或盤後資料尚未公布）→ 綠勾
        只有部分有、部分沒有：
            17:00 前 → 綠勾並提示（之後的排程會再補抓）
            17:00 後 → 紅叉（代表真的有爬蟲壞掉，需要處理）

環境變數 JOB=margin 時改檢查晚上的融資資料（data/margin.csv）：
  當天有交易（現貨資料已寫入）但 23:00 後融資仍沒有 → 紅叉；其餘情況綠勾。

測試用：環境變數 FAKE_NOW="2026/10/26 15:30" 可以假裝成某個時間。
"""

import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(ROOT, "data"))
JOBS = {
    "daily": {"files": ["txo_oi.csv", "txo_strike_oi.csv", "fut_oi.csv", "tx_month_oi.csv", "spot_net.csv"], "late": 17},
    "margin": {"files": ["margin.csv"], "late": 23, "evidence": "spot_net.csv"},
}
JOB = JOBS[os.environ.get("JOB", "daily")]
FILES = JOB["files"]
TAIPEI = timezone(timedelta(hours=8))
LATE_HOUR = JOB["late"]


def now_taipei():
    fake = os.environ.get("FAKE_NOW")
    if fake:
        return datetime.strptime(fake, "%Y/%m/%d %H:%M").replace(tzinfo=TAIPEI)
    return datetime.now(TAIPEI)


def output(key, value):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            f.write(f"{key}={value}\n")
    print(f"→ {key}={value}")


def holiday_name(day):
    """回傳證交所休市日名稱；不是休市日回傳 None；查不到（網路問題）也回傳 None，照常執行"""
    url = f"https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule?response=json&queryYear={day.year}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            j = json.load(r)
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ 查不到證交所休市日（{e!r}），照常執行")
        return None
    target = day.strftime("%Y-%m-%d")
    for row in j.get("data", []):
        if row and row[0] == target:
            name = str(row[1])
            # 「開始交易日」「最後交易日」是有交易的日子，不算休市
            if "交易日" in name:
                return None
            return name
    return None


def has_date(name, day_str):
    path = os.path.join(DATA_DIR, name)
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as f:
        return any(line.startswith(day_str + ",") for line in f)


def have_today(day_str, files=None):
    present = {}
    for name in files or FILES:
        path = os.path.join(DATA_DIR, name)
        found = False
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                found = any(line.startswith(day_str + ",") for line in f)
        present[name] = found
    return present


def pre():
    now = now_taipei()
    day_str = now.strftime("%Y/%m/%d")
    print(f"現在時間（台北）：{now:%Y/%m/%d %H:%M}")
    if now.weekday() >= 5:
        print("今天是週末，不執行")
        return output("skip", "true")
    name = holiday_name(now)
    if name:
        print(f"今天是休市日：{name}，不執行")
        return output("skip", "true")
    present = have_today(day_str)
    if all(present.values()):
        print("今天的資料都已經有了，不需要再抓")
        return output("skip", "true")
    print("還沒抓到的資料：" + "、".join(k for k, v in present.items() if not v))
    output("skip", "false")


def post():
    now = now_taipei()
    day_str = now.strftime("%Y/%m/%d")
    present = have_today(day_str)
    missing = [k for k, v in present.items() if not v]
    if not missing:
        print(f"✅ {day_str} 資料都已更新")
        return
    if "evidence" in JOB:
        traded = has_date(JOB["evidence"], day_str)
        if traded and now.hour >= LATE_HOUR:
            print(f"❌ {day_str} 有交易，但 {LATE_HOUR}:00 後仍缺：{'、'.join(missing)}。請檢查爬蟲")
            sys.exit(1)
        print(f"ℹ️ {day_str} 尚缺：{'、'.join(missing)}（{'尚未公布，之後會再補抓' if traded else '今天沒有交易資料，視為休市或尚未公布'}）")
        return
    if len(missing) == len(FILES):
        print(f"ℹ️ {day_str} 所有來源都還沒有資料（盤後資料尚未公布，或臨時休市），不視為錯誤")
        return
    if now.hour < LATE_HOUR:
        print(f"ℹ️ {day_str} 尚缺：{'、'.join(missing)}。可能還沒公布，之後的排程會再補抓")
        return
    print(f"❌ {day_str} 已過 {LATE_HOUR}:00，其他資料都有，但仍缺：{'、'.join(missing)}。請檢查對應的爬蟲步驟")
    sys.exit(1)


if __name__ == "__main__":
    {"pre": pre, "post": post}[sys.argv[1]]()
