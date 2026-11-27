"""台指選恐慌刻度（網站版計算模組，演算法與 docs/txo-skew-ref/skew_eod.py 一致）。

流程：
  day_metrics(d, chain)   某一天的全部選擇權 → 固定 14 天的 P10／P25／ATM／C25／C10 IV（含推估標記）
  realized_vol(closes, i) 加權指數 5 日 RV
  gauge(days)             逐日序列 → PR、中位數、恐慌刻度、FOMO 刻度、雙尾警示
  run_csv(目錄, 指數.csv)  txo_opt_daily/*.csv.gz ＋ data/taiex.csv
  write_outputs(...)      輸出 data/txo_skew.csv 與 data/txo_skew.json
"""
import csv
import glob
import gzip
import json
import math
import os
import statistics as st
import sys
from datetime import date, timedelta

R = 0.015
N = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))


def b76(F, K, T, v, cp):
    if v <= 0 or T <= 0:
        return max(0.0, (F - K) if cp == "C" else (K - F))
    d1 = (math.log(F / K) + 0.5 * v * v * T) / (v * math.sqrt(T)); d2 = d1 - v * math.sqrt(T)
    df = math.exp(-R * T)
    return df * (F * N(d1) - K * N(d2)) if cp == "C" else df * (K * N(-d2) - F * N(-d1))


def iv(px, F, K, T, cp):
    intr = max(0.0, (F - K) if cp == "C" else (K - F)) * math.exp(-R * T)
    if px <= intr + 1e-9:
        return None
    lo, hi = 0.01, 5.0
    if b76(F, K, T, hi, cp) < px:
        return None
    for _ in range(80):
        m = (lo + hi) / 2
        if b76(F, K, T, m, cp) > px: hi = m
        else: lo = m
    return (lo + hi) / 2


def cdelta(F, K, T, v):
    d1 = (math.log(F / K) + 0.5 * v * v * T) / (v * math.sqrt(T))
    return math.exp(-R * T) * N(d1)


def mid(bid, ask, settle):
    if bid and ask and bid > 0 and ask > bid and (ask - bid) <= max(0.25 * (bid + ask) / 2, 2):
        return (bid + ask) / 2
    return settle if settle and settle > 0 else None   # 盤後買賣價常缺，改用期交所結算價


def interp(xs, ys, x):
    pts = sorted(zip(xs, ys))
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0) if x1 > x0 else y0
    return None


def one_expiry(rows, T):
    """rows: [(K, cp, mid)] → {'F','atm','p10','p25','c25','c10'} IV（小數）"""
    C = {k: m for k, cp, m in rows if cp == "C" and m}
    P = {k: m for k, cp, m in rows if cp == "P" and m}
    both = sorted([k for k in C if k in P], key=lambda k: abs(C[k] - P[k]))[:3]
    if len(both) < 2:
        return None
    F = st.median(k + math.exp(R * T) * (C[k] - P[k]) for k in both)
    pts = []                                       # (call delta, iv) 只用價外
    for k, m in P.items():
        if k < F:
            v = iv(m, F, k, T, "P")
            if v: pts.append((cdelta(F, k, T, v), v, "P"))
    for k, m in C.items():
        if k >= F:
            v = iv(m, F, k, T, "C")
            if v: pts.append((cdelta(F, k, T, v), v, "C"))
    np_ = sum(1 for p in pts if p[2] == "P"); nc = sum(1 for p in pts if p[2] == "C")
    if np_ < 3 or nc < 3:
        return None
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    # put delta -0.10 ⇔ call delta 0.90（同一個 IV 曲面，Black-76 下 call δ ≈ 1 + put δ）
    df = math.exp(-R * T)
    out = {"F": F,
           "p10": interp(xs, ys, df * 0.90), "p25": interp(xs, ys, df * 0.75),
           "atm": interp(xs, ys, df * 0.50),
           "c25": interp(xs, ys, df * 0.25), "c10": interp(xs, ys, df * 0.10)}
    return out if out["atm"] else None             # 翼端算不到的位置留 None，由 fixed_tenor 推估


MAX_EST_DAYS = 45                                  # 推估最多借用剩餘 45 天以內的到期


def fixed_tenor(curves, days):
    """curves: [(T, dict)] → 固定天期：同一 delta 位置用總變異數 σ²T 線性內插。
    某個位置在 14 天前後找不到可內插的兩個到期（急跌時週選低履約價不夠深，P10 算不到），
    就用剩餘天數最接近、且算得到該位置的到期 IV 直接帶入，並記在 est（推估）。"""
    tgt = days / 365
    out, est = {}, []
    for key in ("p10", "p25", "atm", "c25", "c10"):
        cs = sorted([(T, c) for T, c in curves if c.get(key)], key=lambda x: x[0])
        lo = [c for c in cs if c[0] <= tgt]; hi = [c for c in cs if c[0] >= tgt]
        if lo and hi:
            (T0, a), (T1, b) = lo[-1], hi[0]
            if T1 == T0:
                out[key] = a[key]
            else:
                w = (tgt - T0) / (T1 - T0)
                var = a[key] ** 2 * T0 + w * (b[key] ** 2 * T1 - a[key] ** 2 * T0)
                out[key] = math.sqrt(max(var, 1e-8) / tgt)
        else:
            est.append(key)
    # 推估：借用最接近 14 天、且算得到該位置的到期，取它「相對內側位置」的斜率，接在 14 天的內側位置上
    # （保留 14 天的 IV 水位，只借形狀；P10 接 P25、P25 接價平，買權側同理）
    inner = {"p10": "p25", "p25": "atm", "c10": "c25", "c25": "atm"}
    if "atm" in est:
        return None
    for key in sorted(est, key=lambda k: k in ("p25", "c25"), reverse=True):
        anc = inner[key]
        cs = [(T, c) for T, c in curves if c.get(key) and c.get(anc) and abs(T - tgt) * 365 <= MAX_EST_DAYS]
        if out.get(anc) is None or not cs:
            out[key] = None                        # 連推估都做不到：履約價完全不夠（破表）
            continue
        T0, a = min(cs, key=lambda c: abs(c[0] - tgt))
        out[key] = out[anc] + (a[key] - a[anc])
    out["F"] = min(curves, key=lambda c: abs(c[0] - tgt))[1]["F"]
    out["est"] = est
    return out


def exp_from_code(code):
    """2025-12-05 以前期交所資料沒有到期日：由代碼推算（月選＝第 3 個週三、Wn＝第 n 個週三、Fn＝第 n 個週五；不含假日順延）。"""
    y, m = int(code[:4]), int(code[4:6])
    kind, n = (code[6], int(code[7:])) if len(code) > 6 else ("M", 3)
    wd = 4 if kind == "F" else 2
    d = date(y, m, 1)
    d += timedelta(days=(wd - d.weekday()) % 7)
    return (d + timedelta(days=7 * (n - 1))).isoformat()


TENOR = 14
WIN, MIN_WIN = 250, 60                             # PR／中位數：當日之前 250 個交易日，至少 60 天


def day_metrics(d, chain, tenor=TENOR):
    """chain: [(contract, exp_date, strike, cp, settle, bid, ask)] → {'atm','p10','p25','c25','c10'(%), 'est': [...]} 或 None"""
    by = {}
    for code, exd, k, cp, settle, bid, ask in chain:
        if not exd or not str(exd).startswith("20"):
            exd = exp_from_code(str(code).strip())
        by.setdefault(exd, []).append((float(k), cp, mid(bid, ask, settle)))
    curves = []
    for exd, rows in by.items():
        T = ((date.fromisoformat(exd) - date.fromisoformat(d)).days - 0.01) / 365
        if T * 365 < 1.5:                          # 剩不到 1.5 天的到期不用
            continue
        c = one_expiry(rows, T)
        if c:
            curves.append((T, c))
    f = fixed_tenor(curves, tenor)
    if not f:
        return None
    out = {k: (f[k] * 100 if f[k] is not None else None) for k in ("p10", "p25", "atm", "c25", "c10")}
    out["F"] = f["F"]; out["est"] = f["est"]
    return out


def realized_vol(closes, i, n=5):
    """closes: 加權指數收盤序列；第 i 天的 n 日 RV（年化 %）＝ 日對數報酬標準差（母體）× √252"""
    if i < n:
        return None
    rets = [math.log(closes[j] / closes[j - 1]) for j in range(i - n + 1, i + 1)]
    return st.pstdev(rets) * math.sqrt(252) * 100


def gauge(days):
    """days: 依日期排序的 [{'d','c','b5','atm','p10','p25','c25','c10','rv5','est'}]，就地補上指標與刻度。"""
    hist = []
    for r in days:
        if r.get("atm") is None:
            continue
        g = r.get
        r["rr"] = g("p25") - g("c25") if g("p25") is not None and g("c25") is not None else None
        r["psk"] = g("p10") - g("p25") if g("p10") is not None and g("p25") is not None else None
        r["csk"] = g("c10") - g("c25") if g("c10") is not None and g("c25") is not None else None
        r["ivrv"] = r["atm"] / r["rv5"] if g("rv5") else None
        r["over"] = r["rr"] is None or r["psk"] is None          # 破表：賣權翼端連推估都算不到
        r["rel"] = [r[k] - r["atm"] if r.get(k) is not None else None for k in ("p10", "p25", "atm", "c25", "c10")]
        win = hist[-WIN:]
        if len(win) >= MIN_WIN:
            for k in ("atm", "rr", "psk", "csk", "ivrv", "rv5"):
                vs = [x[k] for x in win if x.get(k) is not None]
                if r.get(k) is None:
                    r["pr_" + k] = 100 if k in ("rr", "psk") else None
                else:
                    r["pr_" + k] = round(100 * sum(1 for v in vs if v < r[k]) / len(vs))
                r["md_" + k] = st.median(vs) if vs else None
            r["md_rel"] = [st.median(x["rel"][i] for x in win if x["rel"][i] is not None) for i in range(5)]   # 微笑曲線灰線
            score = round((r["pr_rr"] + r["pr_psk"]) / 2)
            fomo = round(((r["pr_csk"] if r["pr_csk"] is not None else 50) + 100 - r["pr_rr"]) / 2)
            est = r.get("est") or []
            r["score_raw"], r["fomo_raw"] = score, fomo
            if r["over"] or any(k[0] == "p" for k in est):   # 賣權側推估／破表：履約價被跌穿 → 恐慌至少 80
                score = max(score, 80)
            if any(k[0] == "c" for k in est):                 # 買權側推估：履約價被漲穿 → FOMO 至少 80
                fomo = max(fomo, 80)
            r["score"], r["fomo"] = score, fomo
            r["two_tail"] = bool(r["csk"] is not None and r["csk"] > 0 and g("b5") is not None and r["b5"] <= 0)
        hist.append(r)
    return days


def _with_index(rows, closes_by_day):
    td = sorted(closes_by_day); tc = [closes_by_day[d] for d in td]; pos = {d: i for i, d in enumerate(td)}
    for r in rows:
        i = pos.get(r["d"])
        if i is not None:
            r["c"] = tc[i]
            r["rv5"] = realized_vol(tc, i)
            r["b5"] = (tc[i] / tc[i - 5] - 1) * 100 if i >= 5 else None
    return gauge(rows)


def run_csv(opt_dir, index_csv):
    """opt_dir/*.csv.gz 欄位：d,contract,exp_date,strike,cp,oi,settle,close,bid,ask；index_csv 欄位：date,taiex（YYYY/MM/DD）"""
    num = lambda x: float(x) if x not in ("", None) else None
    by = {}
    day_source = {}
    for p in sorted(glob.glob(os.path.join(opt_dir, "*.csv.gz"))):
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                d = r["d"]
                if d in day_source and day_source[d] != p:
                    raise ValueError(f"Duplicate date {d} in {day_source[d]} and {p}")
                day_source[d] = p
                by.setdefault(d, []).append((r["contract"], r["exp_date"], r["strike"], r["cp"],
                                             num(r["settle"]), num(r["bid"]), num(r["ask"])))
    rows = [dict(day_metrics(d, ch) or {}, d=d) for d, ch in sorted(by.items())]
    with open(index_csv, encoding="utf-8") as f:
        closes = {
            r["date"].strip().replace("/", "-"): float(r["taiex"])
            for r in csv.DictReader(f)
            if r.get("date") and r.get("taiex")
        }
    return _with_index(rows, closes)


CSV_FIELDS = [
    "d", "c", "b5", "atm", "p10", "p25", "c25", "c10",
    "rr", "psk", "csk", "rv5", "ivrv",
    "pr_rr", "pr_psk", "pr_csk",
    "score", "fomo", "score_raw", "fomo_raw",
    "two_tail", "over", "est",
]

JSON_FIELDS = [
    "d", "c", "b5", "F", "atm", "p10", "p25", "c25", "c10",
    "rr", "psk", "csk", "rv5", "ivrv", "rel", "md_rel",
    "score", "fomo", "score_raw", "fomo_raw",
    "pr_atm", "pr_rr", "pr_psk", "pr_csk", "pr_ivrv", "pr_rv5",
    "md_atm", "md_rr", "md_psk", "md_csk", "md_ivrv", "md_rv5",
    "two_tail", "over", "est",
]


def _csv_val(key, val):
    if key == "est":
        return "|".join(val) if val else ""
    if val is None:
        return ""
    if isinstance(val, bool):
        return "1" if val else "0"
    if isinstance(val, float):
        return round(val, 2)
    return val


def _json_val(val):
    if isinstance(val, bool):
        return val
    if isinstance(val, float):
        return round(val, 2)
    if isinstance(val, list):
        return [_json_val(x) for x in val]
    return val


def write_outputs(rows, csv_path, json_path):
    """輸出歷史 CSV 與前端頁面用 JSON（保留 0、false、null、[]）。"""
    for path in (csv_path, json_path):
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)

    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(CSV_FIELDS)
        for r in rows:
            w.writerow([_csv_val(k, r.get(k)) for k in CSV_FIELDS])

    jrows = [
        {k: _json_val(r.get(k, [] if k == "est" else None)) for k in JSON_FIELDS}
        for r in rows
    ]
    payload = {"asof": rows[-1]["d"] if rows else None, "rows": jrows}
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    opt_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join("data", "txo_opt_daily")
    index_csv = sys.argv[2] if len(sys.argv) > 2 else os.path.join("data", "taiex.csv")
    rows = run_csv(opt_dir, index_csv)
    if len(sys.argv) > 4:
        write_outputs(rows, sys.argv[3], sys.argv[4])
    print(json.dumps(rows[-1], ensure_ascii=False, default=str, indent=1))
