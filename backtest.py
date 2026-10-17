"""
backtest.py — Backtest CRT + TBS (D → H1) trên CSV của repo S2-4 cũ, mô phỏng lệnh trên nến M1. Không kết nối MT5.

    python backtest.py                         # 4 mã (XAU, EUR, GBP, AUD), chi phí ×1 và ×2
                                               # (tiêu chí + kết quả các lần chạy ghi trước: RULES.md)
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
            "GBPUSD": ["data_2020"], "AUDUSD": ["data_2020"]}     # NZDUSD đã loại (RULES.md mục 8)
POINT = {"XAUUSD": 0.01}                  # còn lại: FX 5 chữ số
SLIPPAGE_POINTS = 5.0
WARMUP_DAYS = 30
BOOTSTRAP_N, BOOTSTRAP_SEED = 10_000, 20261017
CLOSED = {"SL", "TP1_BE", "TP1_TP2"}


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


def print_box(headers: list, rows: list, aligns: str, total: list = None):
    """In bảng kẻ khung. aligns: mỗi cột 'l' hoặc 'r'. total: dòng tổng (ngăn bằng vạch kẻ)."""
    data = [headers] + rows + ([total] if total else [])
    w = [max(len(str(r[i])) for r in data) for i in range(len(headers))]
    cell = lambda v, i, al: f" {str(v):<{w[i]}} " if al == "l" else f" {str(v):>{w[i]}} "
    rule = lambda l, m, r: l + m.join("─" * (x + 2) for x in w) + r
    out = [rule("┌", "┬", "┐"), "│" + "│".join(cell(h, i, "l") for i, h in enumerate(headers)) + "│",
           rule("├", "┼", "┤")]
    out += ["│" + "│".join(cell(v, i, aligns[i]) for i, v in enumerate(r)) + "│" for r in rows]
    if total:
        out += [rule("├", "┼", "┤"), "│" + "│".join(cell(v, i, aligns[i]) for i, v in enumerate(total)) + "│"]
    out.append(rule("└", "┴", "┘"))
    print("\n".join("  " + x for x in out))


def account_tables(results: list, account: float, risk_pct: float):
    """
    Một tài khoản chung cho mọi mã, rủi ro cố định account × risk_pct mỗi lệnh (không tái đầu tư, không làm tròn lot).
    Balance = vốn + lãi/lỗ đã chốt (lệnh tính vào kỳ ĐÓNG lệnh). In tóm tắt + bảng theo năm + theo tháng (đủ mọi tháng).
    DD tích lũy = balance cuối kỳ dưới vốn ban đầu (%); dòng TỔNG = balance thấp nhất dưới vốn ban đầu.
    """
    closed = sorted([x for x in results if x["status"] in CLOSED], key=lambda x: x["exit_ns"])
    if not closed:
        return
    risk_usd = account * risk_pct / 100
    bal = account + np.cumsum([x["r"] * risk_usd for x in closed])
    peak = np.maximum.accumulate(np.concatenate([[account], bal]))[1:]
    i = int(np.argmax(peak - bal))
    live, mx = [], 0
    for x in sorted(closed, key=lambda x: x["fill_ns"]):
        live = [e for e in live if e > x["fill_ns"]] + [x["exit_ns"]]
        mx = max(mx, len(live))
    print(f"\n  Tài khoản chung mọi mã: vốn {account:,.0f} USD, rủi ro {risk_pct:g}% = {risk_usd:,.0f} USD / lệnh")
    print(f"  Balance đầu / cuối      : {account:,.0f} → {bal[-1]:,.0f} USD ({(bal[-1] - account) / account * 100:+.1f}%)")
    print(f"  Max DD balance          : {peak[i] - bal[i]:,.0f} USD ({(peak[i] - bal[i]) / peak[i] * 100:.1f}% từ đỉnh)"
          f" | balance thấp nhất {min(bal.min(), account):,.0f}")
    print(f"  Lệnh mở cùng lúc lớn nhất: {mx}")
    if bal.min() <= 0:
        k = int(np.argmax(bal <= 0))
        print(f"  ⚠ CHÁY TÀI KHOẢN: balance chạm 0 lúc {pd.Timestamp(closed[k]['exit_ns']):%Y-%m-%d} (lệnh thứ {k + 1}); "
              f"số sau đó chỉ để so sánh")

    cnt = lambda xs, s: sum(x["status"] == s for x in xs)
    for title, fmt, freq in (("năm", "%Y", "Y"), ("tháng", "%Y-%m", "M")):
        key = lambda x: pd.Timestamp(x["exit_ns"]).strftime(fmt)
        groups = {}
        for x in closed:
            groups.setdefault(key(x), []).append(x)
        rows, b = [], account

        def row(label, xs, b_end, dd):
            r = np.array([x["r"] for x in xs])
            return [label, len(xs), f"{(r > 0).mean() * 100:.1f}" if len(r) else "—",
                    f"{cnt(xs, 'TP1_TP2')}/{cnt(xs, 'SL')}/{cnt(xs, 'TP1_BE')}", f"{r.sum():+.2f}",
                    f"{r.sum() * risk_usd:+,.0f}", f"{b_end:,.0f}", f"{dd:.2f}%", f"{(b_end - account) / account * 100:+.2f}%"]

        for p in pd.period_range(key(closed[0]), key(closed[-1]), freq=freq).strftime(fmt):
            xs = groups.get(p, [])
            b += sum(x["r"] for x in xs) * risk_usd
            rows.append(row(p, xs, b, max(0.0, (account - b) / account * 100)))
        print(f"\n  Theo {title} (TP/SL/BE = TP1 + TP2 / dừng lỗ / TP1 rồi hoà vốn):")
        print_box([title.capitalize(), "Lệnh", "Win%", "TP/SL/BE", "PnL R", "PnL USD", "Balance", "DD tích lũy",
                   "Tăng trưởng"], rows, "lrrrrrrrr",
                  row("TỔNG", closed, bal[-1], max(0.0, (account - bal.min()) / account * 100)))


def main():
    ap = argparse.ArgumentParser(description="Backtest CRT + TBS (D → H1), không kết nối MT5")
    ap.add_argument("--symbols", nargs="+", type=str.upper, default=list(DATASETS), choices=list(DATASETS))
    ap.add_argument("--root", type=Path, default=OLD_REPO, help="repo chứa các thư mục data*/ (mặc định repo S2-4 cũ)")
    ap.add_argument("--csv", default=None, help="ghi danh sách lệnh (chi phí ×1) ra CSV")
    ap.add_argument("--account", type=float, default=10_000.0, help="vốn tài khoản chung (USD) cho bảng balance")
    ap.add_argument("--risk-percent", type=float, default=1.0, help="%% vốn rủi ro mỗi lệnh cho bảng balance")
    args = ap.parse_args()
    if not (0 < args.risk_percent <= 100 and args.account > 0):
        sys.exit(f"✗ --risk-percent phải trong (0, 100] và --account > 0 (nhận {args.risk_percent}, {args.account}).")

    res = {1.0: [], 2.0: []}
    for sym in args.symbols:
        h1, m1 = load(sym, args.root)
        from_ns = crt_tbs.ns(h1["time"].iloc[:1])[0] + WARMUP_DAYS * 24 * crt_tbs.NS_HOUR
        orders = crt_tbs.find_orders(h1, from_ns)
        arrays = {side: sim_arrays(m1, side) for side in ("SELL", "BUY")}
        for mult in res:
            res[mult] += run_symbol(sym, orders, arrays, mult)
        print(f"    {len(orders)} tín hiệu")

    r1, r2 = res[1.0], res[2.0]
    head = f"  {'':<10} {'Lệnh':>5}  {'Win':>6}  {'E[R]':>7}  {'CI95':^18}  {'Tổng':>9}  {'Max DD':>9}"
    print(f"\n{'=' * 96}\n KẾT QUẢ CRT + TBS (D → H1) — lệnh đã đóng, chi phí ×1 (cột cuối: E[R] chi phí ×2)\n{'=' * 96}")
    print(head)
    by = lambda xs, f: [x for x in xs if f(x)]
    for sym in args.symbols:
        print(line(sym, stats(by(r1, lambda x: x["symbol"] == sym)), stats(by(r2, lambda x: x["symbol"] == sym))))
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

    account_tables(r1, args.account, args.risk_percent)

    if args.csv:
        df = pd.DataFrame(r1)
        for k in ("created_ns", "fill_ns", "exit_ns"):
            df[k] = pd.to_datetime(df[k], utc=True)
        df.to_csv(args.csv, index=False)
        print(f"\n  Đã ghi {len(df)} tín hiệu → {args.csv}")


if __name__ == "__main__":
    main()
