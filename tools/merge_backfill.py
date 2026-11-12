"""把 newdata/<檔名> 裡、data/<檔名> 還沒有的日期併進去，並依日期排序（同一天內保留原順序）。
用法：python tools/merge_backfill.py spot_net.csv margin.csv ..."""
import csv, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for name in sys.argv[1:]:
    src, dst = os.path.join(ROOT, "newdata", name), os.path.join(ROOT, "data", name)
    if not os.path.exists(src):
        print(f"{name}：沒有補到資料"); continue
    with open(dst, encoding="utf-8") as f:
        r = list(csv.reader(f))
    head, rows = r[0], r[1:]
    have = {x[0] for x in rows}
    with open(src, encoding="utf-8") as f:
        new = [x for x in list(csv.reader(f))[1:] if x and x[0] not in have]
    rows += new
    rows.sort(key=lambda x: x[0])
    with open(dst, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n"); w.writerow(head); w.writerows(rows)
    print(f"{name}：新增 {len({x[0] for x in new})} 天，共 {len({x[0] for x in rows})} 天")
