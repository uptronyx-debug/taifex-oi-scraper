"""
盤後輪詢：每分鐘跑一次全部爬蟲，只要有新資料就立刻 commit + push，
直到今天五份資料都到齊，或超過截止時間（預設台北 15:40）為止。

每支爬蟲都會自己略過已經有的日期，且資料尚未公布（全為 0、頁面日期不對）時不寫入，
所以重複跑是安全的，只會補上缺的部分。

環境變數：
    POLL_FROM    輪詢開始時間 HH:MM（台北），預設 14:00；不在 POLL_FROM～POLL_UNTIL 之間只跑一輪
    POLL_UNTIL   截止時間 HH:MM（台北），預設 15:40
    POLL_EVERY   間隔秒數，預設 60
"""

import os
import subprocess
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_today import FILES, have_today, now_taipei  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRAPERS = [
    ("選擇權三大法人", ["scraper.py"]),
    ("選擇權各履約價", ["scraper_by_strike.py"]),
    ("期貨三大法人", ["scraper_futures.py"]),
    ("大台各月份", ["scraper_tx_months.py"]),
    ("現貨買賣超", ["scraper_spot.py"]),
]


def sh(*args, check=True):
    return subprocess.run(list(args), cwd=ROOT, check=check, text=True, capture_output=True)


def commit_and_push(day_str):
    if not sh("git", "status", "--porcelain", "data", check=False).stdout.strip():
        return False
    sh("git", "add", "data")
    sh("git", "commit", "-q", "-m", f"auto: 更新 TAIFEX 資料 {day_str.replace('/', '-')}")
    err = ""
    for attempt in range(3):
        r = sh("git", "push", "-q", "origin", "HEAD:main", check=False)
        if r.returncode == 0:
            return True
        err = (r.stderr or r.stdout).strip()
        sh("git", "pull", "-q", "--rebase", "origin", "main", check=False)
        time.sleep(3)
    print(f"❌ push 失敗：{err}")
    return False


def main():
    start = os.environ.get("POLL_FROM", "14:00")
    until = os.environ.get("POLL_UNTIL", "15:40")
    every = int(os.environ.get("POLL_EVERY", "60"))
    sh("git", "config", "user.name", "github-actions[bot]")
    sh("git", "config", "user.email", "github-actions[bot]@users.noreply.github.com")

    rnd = 0
    while True:
        rnd += 1
        now = now_taipei()
        day_str = now.strftime("%Y/%m/%d")
        present = have_today(day_str)
        missing = [k for k, v in present.items() if not v]
        print(f"\n===== 第 {rnd} 輪 {now:%H:%M:%S}，尚缺：{'、'.join(missing) or '無'}")
        if not missing:
            print("✅ 今天五份資料都到齊了")
            break
        for label, cmd in SCRAPERS:
            r = subprocess.run([sys.executable, *cmd], cwd=ROOT, text=True, capture_output=True)
            out = (r.stdout + r.stderr).strip().splitlines()
            tail = out[-1] if out else ""
            mark = "✖" if r.returncode != 0 else "·"
            print(f"  {mark} {label}：{tail}")
            if r.returncode != 0:
                print("\n".join("      " + l for l in out[-8:]))
        if commit_and_push(day_str):
            print(f"  ⬆ 已推送新資料（{now_taipei():%H:%M:%S}）")
        if all(have_today(day_str).values()):
            print("✅ 今天五份資料都到齊了")
            break
        hm = now_taipei().strftime("%H:%M")
        if not (start <= hm < until):
            print(f"⏹ 現在 {hm} 不在輪詢時段 {start}～{until}，結束（缺的部分交給之後的觸發或 17:30 備援）")
            break
        time.sleep(every)


if __name__ == "__main__":
    main()
