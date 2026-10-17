"""
backtest.py — Backtest CRT + TBS trên CSV của repo S2-4 cũ, mô phỏng lệnh trên nến M1. Không kết nối MT5.

    python backtest.py                         # D → H1, 5 mã, chi phí ×1 và ×2, chấm tiêu chí RULES.md mục 4
    python backtest.py --tf H4-M5              # lần chạy 2 (RULES.md mục 5, TRONG MẪU)
    python backtest.py --symbols XAUUSD --csv trades.csv

Mô phỏng (RULES.md mục 3): giá Bid; chi phí (spread nến M1 khớp + 5 point) × hệ số trừ vào giá khớp;
nến M1 chạm cả SL lẫn TP → SL trước; gap qua mức dừng → thoát ở giá mở; 50% chốt TP1, 50% tới TP2,
TP1 chạm → SL phần còn lại về giá khớp từ nến M1 sau. Một lệnh mở mỗi mã.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import crt_tbs

OLD_REPO = Path(r"C:\Users\Duc\.gemini\antigravity\scratch\xauusd_trading_bot")
DATASETS = {"XAUUSD": ["data_2021", "data"], "EURUSD": ["data_2020", "data_2021", "data"],
            "GBPUSD": ["data_2020"], "AUDUSD": ["data_2020"], "NZDUSD": ["data_2020"]}
POINT = {"XAUUSD": 0.01}                  # còn lại: FX 5 chữ số
SLIPPAGE_POINTS = 5.0
WARMUP_DAYS = 30
BOOTSTRAP_N, BOOTSTRAP_SEED = 10_000, 20261017
CLOSED = {"SL", "TP1_BE", "TP1_TP2"}
TIMEFRAMES = {"D-H1": (24, 60), "H4-M5": (4, 5)}    # (giờ / nến CRT, phút / nến vào lệnh)


# ─── Dữ liệu ─────────────────────────────────────────────────────────────────

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load(symbol: str, root: Path) -> tuple:
    """(h1, m1) nối các thư mục của DATASETS[symbol]; mỗi CSV phải khớp sha256 trong <symbol>_meta.json, lệch → dừng."""
    out = {}
    for key in ("H1", "M1"):
        parts = []
        for sub in DATASETS[symbol]:
            meta = root / sub / f"{symbol}_meta.json"
            path = root / sub / f"{symbol}_{key}.csv"
            if not meta.exists() or not path.exists():
                sys.exit(f"✗ Thiếu {path} hoặc {meta} — dừng.")
            expected = json.loads(meta.read_text(encoding="utf-8")).get("timeframes", {}).get(key, {}).get("sha256")
            actual = _sha256(path)
            if actual != expected:
                sys.exit(f"✗ Hash {sub}/{path.name} KHÔNG KHỚP meta ({actual[:12]}… ≠ {str(expected)[:12]}…) — dừng.")
            parts.append(pd.read_csv(path, parse_dates=["time"]))
        df = pd.concat(parts).drop_duplicates("time", keep="first").sort_values("time").reset_index(drop=True)
        out[key] = df
        print(f"  ✓ {symbol} {key}: {len(df):,} nến {df['time'].iat[0]:%Y-%m-%d} → {df['time'].iat[-1]:%Y-%m-%d} "
              f"({' + '.join(DATASETS[symbol])}, sha256 khớp)")
    return out["H1"], out["M1"]


def build_m5(m1: pd.DataFrame) -> pd.DataFrame:
    """M5 từ M1 (nhãn = mốc ĐẦU nến, như MT5)."""
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    return (m1.set_index("time")[list(agg)].resample("5min", label="left", closed="left").agg(agg)
              .dropna(subset=["open"]).reset_index())


# ─── Mô phỏng (không gian BÁN; MUA lật giá) ─────────────────────────────────

def sim_arrays(m1: pd.DataFrame, side: str) -> dict:
    s = 1.0 if side == "SELL" else -1.0
    hi, lo = (m1["high"], m1["low"]) if s > 0 else (-m1["low"], -m1["high"])
    return dict(s=s, t=crt_tbs.ns(m1["time"]), H=hi.to_numpy(float), L=lo.to_numpy(float),
                O=(s * m1["open"]).to_numpy(float), sp=m1["spread"].to_numpy(float))


def _next_event(H, L, b: int, stop: float, target: float) -> int:
    """Chỉ số nến M1 đầu tiên ≥ b có high ≥ stop hoặc low ≤ target; không có → −1."""
    n = len(H)
    while b < n:
        e = min(n, b + 50_000)
        hit = (H[b:e] >= stop) | (L[b:e] <= target)
        k = int(hit.argmax())
        if hit[k]:
            return b + k
        b = e
    return -1


def simulate(o: dict, A: dict, point: float, mult: float) -> dict:
    s, t, H, L, O = A["s"], A["t"], A["H"], A["L"], A["O"]
    sl, tp1, tp2 = s * o["sl"], s * o["tp1"], s * o["tp2"]
    res = dict(status=None, fill_ns=None, exit_ns=None, entry=None, r=0.0)
    b = int(np.searchsorted(t, o["created_ns"], "left"))
    if b >= len(t):
        res["status"] = "HET_DU_LIEU"; return res
    entry = O[b]
    cost = (A["sp"][b] + SLIPPAGE_POINTS) * point * mult
    res["entry"] = s * entry
    if not (tp1 < entry < sl) or sl - entry <= cost:
        res["status"] = "BO_GIA_VAO"; return res
    P, risk = entry - cost, sl - entry                       # giá khớp (bất lợi), rủi ro danh nghĩa
    res["fill_ns"] = int(t[b])
    j = _next_event(H, L, b, sl, tp1)
    if j < 0:
        res["status"] = "CON_MO"; return res
    if H[j] >= sl:                                           # SL trước (cả hai phần)
        x = max(sl, O[j])
        res.update(status="SL", exit_ns=int(t[j]), r=(P - x) / risk); return res
    if L[j] <= tp2:                                          # cùng nến chạm luôn TP2
        res.update(status="TP1_TP2", exit_ns=int(t[j]), r=0.5 * (P - tp1) / risk + 0.5 * (P - tp2) / risk)
        return res
    k = _next_event(H, L, j + 1, P, tp2)                     # phần 2: SL = giá khớp từ nến sau
    if k < 0:
        res["status"] = "CON_MO"; return res
    if H[k] >= P:
        x2, stt = max(P, O[k]), "TP1_BE"
    else:
        x2, stt = tp2, "TP1_TP2"
    res.update(status=stt, exit_ns=int(t[k]), r=0.5 * (P - tp1) / risk + 0.5 * (P - x2) / risk)
    return res


def run_symbol(symbol: str, orders: list, arrays: dict, mult: float) -> list:
    """Mô phỏng theo thời gian; tín hiệu tới khi mã còn lệnh mở → BAN (bỏ)."""
    point = POINT.get(symbol, 0.00001)
    busy_until, out = -1, []
    for o in orders:
        if o["created_ns"] < busy_until:
            x = dict(status="BAN", fill_ns=None, exit_ns=None, entry=None, r=0.0)
        else:
            x = simulate(o, arrays[o["side"]], point, mult)
            if x["fill_ns"] is not None:
                busy_until = x["exit_ns"] if x["exit_ns"] is not None else np.iinfo(np.int64).max
        out.append(dict(o, symbol=symbol, **x))
    return out


# ─── Thống kê ────────────────────────────────────────────────────────────────

def bootstrap_ci(r: np.ndarray, alpha: float = 0.05) -> tuple:
    if len(r) == 0:
        return float("nan"), float("nan")
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    means = r[rng.integers(0, len(r), size=(BOOTSTRAP_N, len(r)))].mean(axis=1)
    return float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))


def stats(xs: list) -> dict:
    c = sorted([x for x in xs if x["status"] in CLOSED], key=lambda x: x["exit_ns"])
    r = np.array([x["r"] for x in c])
    if not len(r):
        return dict(n=0, win=float("nan"), er=float("nan"), lo=float("nan"), hi=float("nan"), tot=0.0, dd=0.0)
    eq = np.concatenate([[0.0], np.cumsum(r)])
    lo, hi = bootstrap_ci(r)
    return dict(n=len(r), win=(r > 0).mean() * 100, er=r.mean(), lo=lo, hi=hi, tot=r.sum(),
                dd=(np.maximum.accumulate(eq) - eq).max())


def line(label: str, st: dict, st2: dict = None) -> str:
    s = (f"  {label:<10} {st['n']:>5}  {st['win']:5.1f}%  {st['er']:+.4f}  [{st['lo']:+.3f}, {st['hi']:+.3f}]  "
         f"{st['tot']:+8.2f}R  DD {st['dd']:6.2f}R")
    return s + (f"  | ×2 {st2['er']:+.4f}" if st2 else "")


def main():
    ap = argparse.ArgumentParser(description="Backtest CRT + TBS, không kết nối MT5")
    ap.add_argument("--tf", default="D-H1", choices=list(TIMEFRAMES), help="khung nến CRT → khung vào lệnh")
    ap.add_argument("--symbols", nargs="+", type=str.upper, default=list(DATASETS), choices=list(DATASETS))
    ap.add_argument("--root", type=Path, default=OLD_REPO, help="repo chứa các thư mục data*/ (mặc định repo S2-4 cũ)")
    ap.add_argument("--csv", default=None, help="ghi danh sách lệnh (chi phí ×1) ra CSV")
    args = ap.parse_args()
    htf_hours, ltf_minutes = TIMEFRAMES[args.tf]

    res = {1.0: [], 2.0: []}
    for sym in args.symbols:
        h1, m1 = load(sym, args.root)
        ltf = h1 if ltf_minutes == 60 else build_m5(m1)
        from_ns = crt_tbs.ns(h1["time"].iloc[:1])[0] + WARMUP_DAYS * 24 * crt_tbs.NS_HOUR
        orders = crt_tbs.find_orders(ltf, from_ns, htf_hours, ltf_minutes)
        arrays = {side: sim_arrays(m1, side) for side in ("SELL", "BUY")}
        for mult in res:
            res[mult] += run_symbol(sym, orders, arrays, mult)
        print(f"    {len(orders)} tín hiệu")

    r1, r2 = res[1.0], res[2.0]
    head = f"  {'':<10} {'Lệnh':>5}  {'Win':>6}  {'E[R]':>7}  {'CI95':^18}  {'Tổng':>9}  {'Max DD':>9}"
    print(f"\n{'=' * 96}\n KẾT QUẢ CRT + TBS ({args.tf.replace('-', ' → ')}) — lệnh đã đóng, chi phí ×1 (cột cuối: E[R] chi phí ×2)\n{'=' * 96}")
    print(head)
    by = lambda xs, f: [x for x in xs if f(x)]
    per_sym = {}
    for sym in args.symbols:
        per_sym[sym] = stats(by(r1, lambda x: x["symbol"] == sym))
        print(line(sym, per_sym[sym], stats(by(r2, lambda x: x["symbol"] == sym))))
    pool, pool2 = stats(r1), stats(r2)
    print(line("GỘP", pool, pool2))
    print("\n  Theo chiều:")
    side_st = {sd: stats(by(r1, lambda x: x["side"] == sd)) for sd in ("BUY", "SELL")}
    for sd, lab in (("BUY", "MUA"), ("SELL", "BÁN")):
        print(line(lab, side_st[sd], stats(by(r2, lambda x: x["side"] == sd))))
    print("\n  Theo năm khớp lệnh:")
    year = lambda x: pd.Timestamp(x["fill_ns"]).year if x["fill_ns"] is not None else None
    years = sorted({year(x) for x in r1 if x["status"] in CLOSED})
    year_st = {y: stats(by(r1, lambda x: year(x) == y)) for y in years}
    for y in years:
        print(line(str(y), year_st[y]))
    st = pd.Series([x["status"] for x in r1]).value_counts()
    print("\n  Trạng thái mọi tín hiệu (×1): " + ", ".join(f"{k} {v}" for k, v in st.items()))
    for stt in ("TP1_TP2", "TP1_BE", "SL"):
        rr = [x["r"] for x in r1 if x["status"] == stt]
        if rr:
            print(f"    {stt:<8} {len(rr):>4} lệnh  E[R] {np.mean(rr):+.4f}")

    if args.symbols == list(DATASETS):
        big = [y for y in years if year_st[y]["n"] >= 20]
        pos_years = sum(year_st[y]["er"] > 0 for y in big)
        pos_sym = sum(per_sym[s]["er"] > 0 for s in per_sym)
        crit = [("E[R] gộp > 0 ở ×1 và ×2", pool["er"] > 0 and pool2["er"] > 0),
                ("CI95 gộp cận dưới > 0", pool["lo"] > 0),
                (f"E[R] > 0 trên ≥ 4/5 mã ({pos_sym}/5)", pos_sym >= 4),
                ("E[R] gộp > 0 ở cả MUA và BÁN", side_st["BUY"]["er"] > 0 and side_st["SELL"]["er"] > 0),
                (f"E[R] > 0 ở ≥ 2/3 số năm có ≥ 20 lệnh ({pos_years}/{len(big)})",
                 len(big) > 0 and pos_years * 3 >= 2 * len(big))]
        print("\n  Tiêu chí (RULES.md mục 4):")
        for lab, ok in crit:
            print(f"    {'✓' if ok else '✗'} {lab}")
        print(f"  → {'ĐẠT (ứng viên, cần Demo)' if all(ok for _, ok in crit) else 'KHÔNG ĐẠT'}")
        if args.tf != "D-H1":
            print("  ⚠ Kết quả TRONG MẪU — lần thử thứ 2 trên cùng dữ liệu (RULES.md mục 5)")

    if args.csv:
        df = pd.DataFrame(r1)
        for k in ("created_ns", "fill_ns", "exit_ns"):
            df[k] = pd.to_datetime(df[k], utc=True)
        df.to_csv(args.csv, index=False)
        print(f"\n  Đã ghi {len(df)} tín hiệu → {args.csv}")


if __name__ == "__main__":
    main()
