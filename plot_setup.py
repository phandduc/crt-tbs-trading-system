"""
plot_setup.py — Vẽ ảnh setup vào lệnh CRT + TBS: khung D (nến CRT, key level) + khung H1 (quét, TBS, Orderblock,
xác nhận Model #1, Entry / SL / TP1 / TP2) + lý do vào lệnh. Dùng chung cho backtest và bot (gửi kèm Telegram).

    python plot_setup.py --symbol XAUUSD            # 10 lệnh backtest rải đều → reports/setups_xauusd.pdf + PNG
    python plot_setup.py --symbol EURUSD --n 20

Các mốc (key level, nến quét / TBS / Orderblock / xác nhận) lấy thẳng từ crt_tbs.find_orders → ảnh đúng với quyết
định của chiến lược, không tính lại.
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Rectangle

import crt_tbs

UP, DOWN = "#26a69a", "#ef5350"
C_ENTRY, C_SL, C_TP1, C_TP2 = "#1565c0", "#d32f2f", "#2e7d32", "#66bb6a"
C_CRT, C_KEY, C_OB, C_MARK = "#ef6c00", "#8e24aa", "#6d4c41", "#212121"
STATUS_VN = {"TP1_TP2": "Chạm TP1 rồi TP2", "TP1_BE": "Chạm TP1, phần còn lại về hoà vốn", "SL": "Dính SL"}
MAX_H1_BARS = 160


def _candles(ax, df):
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    for x in range(len(df)):
        col = UP if c[x] >= o[x] else DOWN
        ax.vlines(x, l[x], h[x], color=col, lw=0.8, zorder=2)
        ax.add_patch(Rectangle((x - 0.35, min(o[x], c[x])), 0.7, max(abs(c[x] - o[x]), 1e-9),
                               facecolor=col, edgecolor=col, lw=0.5, zorder=3))
    ax.set_xlim(-1, len(df) + 8)                               # chừa chỗ bên phải cho nhãn


def _hline(ax, x0, x1, y, color, label, dig, ls="-", lw=1.4, below=False, at_start=False):
    """Đoạn ngang x0 → x1, nhãn ở đầu phải (hoặc đầu trái nếu at_start)."""
    ax.hlines(y, x0, x1, colors=color, linestyles=ls, lw=lw, zorder=4)
    ax.annotate(f"{label} {y:.{dig}f}", (x0 if at_start else x1, y), xytext=(3, -9 if below else 2),
                textcoords="offset points", fontsize=7, color=color, fontweight="bold", zorder=6)


def _mark(ax, x, y, text, up):
    ax.annotate(text, (x, y), xytext=(0, 18 if up else -22), textcoords="offset points", ha="center", fontsize=7.5,
                color=C_MARK, fontweight="bold", zorder=7,
                arrowprops=dict(arrowstyle="->", color=C_MARK, lw=0.9))


def _ticks(ax, times, fmt):
    pos = np.linspace(0, len(times) - 1, min(8, len(times))).astype(int)
    ax.set_xticks(pos)
    ax.set_xticklabels([pd.Timestamp(times.iloc[p]).strftime(fmt) for p in pos], fontsize=7)


def _t(ns, vn=False):
    t = pd.Timestamp(ns, tz="UTC")
    return f"{t:%Y-%m-%d %H:%M} UTC" + (f" ({t + pd.Timedelta(hours=7):%H:%M} giờ VN)" if vn else "")


def plot_setup(h1: pd.DataFrame, o: dict, dig: int, entry: float = None, res: dict = None, title: str = "",
               out_png=None, pdf=None):
    """Vẽ một setup. o: lệnh của crt_tbs.find_orders; entry: giá vào (mặc định giá đóng nến xác nhận);
    res: kết quả mô phỏng (status, r, exit_ns) nếu có. Ghi PNG (out_png) và / hoặc thêm trang vào pdf."""
    h1 = h1.sort_values("time").reset_index(drop=True)
    d = crt_tbs.daily(h1)
    T = crt_tbs.ns(h1["time"])
    dO, dH, dL, dC = (d[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    first, last = d["first"].to_numpy(), d["last"].to_numpy()
    c = int(np.flatnonzero(d["day"].dt.date.to_numpy() == o["crt_day"])[0])
    sell = o["side"] == "SELL"
    crth, crtl, mid = dH[c], dL[c], (dH[c] + dL[c]) / 2
    bar = lambda ns: int(np.searchsorted(T, ns, "right")) - 1          # nến H1 chứa thời điểm ns
    i_conf = bar(o["created_ns"] - crt_tbs.NS_HOUR)
    i_sweep, i_tbs, i_ob = bar(o["sweep_ns"]), bar(o["tbs_ns"]), bar(o["ob_ns"])
    exit_ns = res.get("exit_ns") if res else None
    i_exit = bar(exit_ns) if exit_ns else None
    entry = entry if entry is not None else (res.get("entry") if res and res.get("entry") is not None
                                             else float(h1["close"].iat[i_conf]))
    side_vn = "BÁN" if sell else "MUA"

    fig, (axd, axh, axt) = plt.subplots(3, 1, figsize=(14, 11.5), gridspec_kw={"height_ratios": [4, 5, 1.7]})
    fig.suptitle(title or f"CRT + TBS | {side_vn} | nến CRT {o['crt_day']}", fontsize=12, fontweight="bold")

    # ── khung D: 30 nến trước nến CRT tới hết lệnh (tối đa 15 nến sau) ──
    day_of = lambda i: int(np.searchsorted(first, i, "right")) - 1
    d_lo = max(0, c - 30)
    d_hi = min(len(d) - 1, c + 15, max(c + 1, day_of(i_exit) if i_exit is not None else c + 1) + 1)
    _candles(axd, d.iloc[d_lo:d_hi + 1])
    xc = c - d_lo
    axd.add_patch(Rectangle((xc - 0.5, crtl), 1, crth - crtl, facecolor=C_CRT, alpha=0.12, edgecolor=C_CRT, zorder=1))
    axd.annotate("Nến CRT", (xc, crth if sell else crtl), xytext=(0, 8 if sell else -14), textcoords="offset points",
                 ha="center", fontsize=8, color=C_CRT, fontweight="bold")
    x_end = d_hi - d_lo
    _hline(axd, xc, x_end, crth, C_CRT, "CRTH", dig, ls=":")
    _hline(axd, xc, x_end, mid, C_TP1, "50%", dig, ls=":")
    _hline(axd, xc, x_end, crtl, C_CRT, "CRTL", dig, ls=":", below=True)
    arr = dH if sell else dL
    k = next((k for k in range(c - 1, d_lo - 1, -1) if np.isclose(arr[k], o["key_level"])), None)
    _hline(axd, 0 if k is None else k - d_lo, xc, o["key_level"], C_KEY,
           ("Đỉnh" if sell else "Đáy") + " D cũ (key level)", dig, ls="--", below=not sell, at_start=True)
    _ticks(axd, d["day"].iloc[d_lo:d_hi + 1], "%m-%d")
    axd.set_title("D — nến CRT (dày, chạm key level), CRTH / 50% / CRTL", fontsize=9, loc="left")

    # ── khung H1: từ đầu nến CRT tới sau xác nhận / tới nến đóng lệnh ──
    h_lo = int(first[c])
    h_hi = min(len(h1) - 1, h_lo + MAX_H1_BARS, max(i_conf + 12, (i_exit + 4) if i_exit is not None else 0))
    w = h1.iloc[h_lo:h_hi + 1].reset_index(drop=True)
    _candles(axh, w)
    x = lambda i: i - h_lo
    axh.axvspan(x(first[c]) - 0.5, x(last[c]) + 0.5, color=C_CRT, alpha=0.06, zorder=0)
    axh.text(x(first[c]), 0.01, "nến CRT (D)", transform=axh.get_xaxis_transform(), fontsize=7, color=C_CRT)
    if c + 1 < len(d):
        axh.text(x(first[c + 1]), 0.01, "nến D kế tiếp — tìm TBS + Model #1", transform=axh.get_xaxis_transform(),
                 fontsize=7, color=C_MARK)
    xs = x(h_lo)
    sweep_lvl = crth if sell else crtl
    _hline(axh, xs, x(i_conf), sweep_lvl, C_CRT, "CRTH" if sell else "CRTL", dig, ls=":", below=not sell,
           at_start=True)
    hi_w, lo_w, cl_w = h1["high"].to_numpy(float), h1["low"].to_numpy(float), h1["close"].to_numpy(float)
    ob_open = float(h1["open"].iat[i_ob])
    if i_tbs == i_sweep:
        _mark(axh, x(i_tbs), hi_w[i_tbs] if sell else lo_w[i_tbs], "Quét + TBS", sell)
    else:
        _mark(axh, x(i_sweep), hi_w[i_sweep] if sell else lo_w[i_sweep], "Quét", sell)
        _mark(axh, x(i_tbs), hi_w[i_tbs] if sell else lo_w[i_tbs], "TBS", sell)
    axh.add_patch(Rectangle((x(i_ob) - 0.45, min(ob_open, cl_w[i_ob])), 0.9, abs(cl_w[i_ob] - ob_open) or 1e-9,
                            fill=False, edgecolor=C_OB, lw=1.6, zorder=5))
    _hline(axh, x(i_ob), x(i_conf), ob_open, C_OB, "Giá mở OB", dig, ls="--", lw=1.0, below=sell)
    _mark(axh, x(i_conf), lo_w[i_conf] if sell else hi_w[i_conf], "Model #1", not sell)
    x1 = x(i_exit) if i_exit is not None else x(h_hi)
    # live (chưa có nến sau tín hiệu): kéo vào khoảng trống bên phải; lệnh dài hơn khung: cắt sát mép để còn nhãn
    x1 = min(max(x1, x(i_conf) + 5), len(w) + 3)
    if i_exit is not None and i_exit > h_hi:
        axh.text(0.99, 0.01, f"lệnh đóng sau khung hình: {_t(exit_ns)}", transform=axh.transAxes, ha="right",
                 fontsize=7, color=C_MARK)
    _hline(axh, x(i_conf), x1, entry, C_ENTRY, "Entry", dig, lw=2)
    _hline(axh, x(i_conf), x1, o["sl"], C_SL, "SL", dig, lw=2, below=not sell)
    _hline(axh, x(i_conf), x1, o["tp1"], C_TP1, "TP1", dig, lw=2)
    _hline(axh, x(i_conf), x1, o["tp2"], C_TP2, "TP2", dig, lw=2, below=sell)
    axh.plot(x(i_conf) + 0.5, entry, "o", color=C_ENTRY, ms=7, zorder=8)
    if i_exit is not None:
        axh.axvline(x(i_exit), color=C_MARK, lw=0.7, ls=":")
    lo_y = min(w["low"].min(), o["sl"], o["tp2"], entry)
    hi_y = max(w["high"].max(), o["sl"], o["tp2"], entry)
    pad = (hi_y - lo_y) * 0.06
    axh.set_ylim(lo_y - pad, hi_y + pad)
    _ticks(axh, w["time"], "%m-%d %Hh")
    axh.set_title("H1 — quét, TBS, Orderblock (khung nâu), nến xác nhận Model #1, Entry / SL / TP", fontsize=9,
                  loc="left", pad=14)

    # ── lý do vào lệnh ──
    body = abs(dC[c] - dO[c]) / (crth - crtl)
    rr = abs(o["tp1"] - entry) / abs(o["sl"] - entry) if o["sl"] != entry else float("nan")
    lines = [
        f"{side_vn} — tín hiệu lúc {_t(o['created_ns'], vn=True)}",
        f"1. Nến CRT {o['crt_day']}: thân {body:.0%} biên độ (≥ 50% → dày); CRTH {crth:.{dig}f}, CRTL {crtl:.{dig}f}, "
        f"50% {mid:.{dig}f}.",
        f"2. Key level: nến CRT chạm {'đỉnh' if sell else 'đáy'} D cũ chưa bị lấy {o['key_level']:.{dig}f}.",
        f"3. Nến D kế tiếp: quét {'CRTH' if sell else 'CRTL'} lúc {_t(o['sweep_ns'])}; TBS = nến H1 {_t(o['tbs_ns'])} "
        f"đóng cửa {cl_w[i_tbs]:.{dig}f} {'trên CRTH' if sell else 'dưới CRTL'} (thân nến, không chỉ râu).",
        f"4. Model #1: nến H1 {_t(T[i_conf])} đóng {cl_w[i_conf]:.{dig}f} {'dưới' if sell else 'trên'} giá mở "
        f"Orderblock {ob_open:.{dig}f} (nến {_t(o['ob_ns'])}).",
        f"5. Entry {entry:.{dig}f} | SL {o['sl']:.{dig}f} ({'đỉnh' if sell else 'đáy'} vùng quét) | TP1 {o['tp1']:.{dig}f} (50% CRT: chốt 50% "
        f"+ hoà vốn) | TP2 {o['tp2']:.{dig}f} | RR tới TP1 {rr:.2f}",
    ]
    if res and res.get("status") in STATUS_VN:
        lines.append(f"Kết quả mô phỏng: {STATUS_VN[res['status']]} | {res['r']:+.2f}R | đóng lúc {_t(exit_ns)}")
    axt.axis("off")
    axt.text(0, 1, "\n".join(lines), fontsize=9, va="top")
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    if out_png is not None:
        Path(out_png).parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_png, dpi=110)
    if pdf is not None:
        pdf.savefig(fig)
    plt.close(fig)
    return out_png


def main():
    import backtest
    ap = argparse.ArgumentParser(description="Vẽ ảnh setup các lệnh backtest CRT + TBS ra PDF + PNG")
    ap.add_argument("--symbol", required=True, type=str.upper, choices=list(backtest.DATASETS))
    ap.add_argument("--n", type=int, default=10, help="số lệnh đã đóng, rải đều theo thời gian (mặc định 10)")
    ap.add_argument("--root", type=Path, default=backtest.OLD_REPO)
    ap.add_argument("--out", default=None, help="mặc định reports/setups_<symbol>.pdf")
    args = ap.parse_args()
    if args.n < 1:
        raise SystemExit("✗ --n phải ≥ 1.")
    dig = round(-np.log10(backtest.POINT.get(args.symbol, 0.00001)))
    h1, m1 = backtest.load(args.symbol, args.root)
    from_ns = crt_tbs.ns(h1["time"].iloc[:1])[0] + backtest.WARMUP_DAYS * 24 * crt_tbs.NS_HOUR
    orders = crt_tbs.find_orders(h1, from_ns)
    arrays = {side: backtest.sim_arrays(m1, side) for side in ("SELL", "BUY")}
    closed = [x for x in backtest.run_symbol(args.symbol, orders, arrays, 1.0) if x["status"] in backtest.CLOSED]
    if not closed:
        raise SystemExit("✗ Không có lệnh đã đóng để vẽ.")
    pick = [closed[k] for k in np.unique(np.linspace(0, len(closed) - 1, min(args.n, len(closed))).astype(int))]
    out = Path(args.out or f"reports/setups_{args.symbol.lower()}.pdf")
    out.parent.mkdir(parents=True, exist_ok=True)
    png_dir = out.with_suffix("")
    with PdfPages(out) as pdf:
        for n, x in enumerate(pick, 1):
            plot_setup(h1, x, dig, res=x, pdf=pdf, out_png=png_dir / f"setup{n:02d}.png",
                       title=f"CRT + TBS | {args.symbol} {x['side']} | nến CRT {x['crt_day']} | {x['r']:+.2f}R")
            print(f"  {n:2d}. {x['side']:<4} nến CRT {x['crt_day']} → {x['status']:<7} {x['r']:+.2f}R")
    print(f"\n  Đã ghi {len(pick)} trang → {out}\n  Ảnh PNG → {png_dir}")


if __name__ == "__main__":
    main()
