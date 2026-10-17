"""
crt_tbs.py — Chiến lược CRT + TBS (Candle Range Theory + Turtle Body Soup), khung D → H1. Quy tắc: RULES.md mục 2.

Chỉ dùng nến đã đóng. Tín hiệu phát ra lúc nến H1 xác nhận đóng (created_ns); giá vào do bên chạy lệnh lấy
(backtest: giá mở nến M1 đầu tiên từ created_ns; live: giá thị trường lúc đó).
Chiều MUA tính bằng cách lật giá (−x) rồi dùng đúng logic chiều BÁN.
"""

import numpy as np
import pandas as pd

NS_HOUR = 3_600_000_000_000
THICK_BODY = 0.5      # nến CRT dày: thân ≥ 50% biên độ
SWING_SIDE = 2        # đỉnh / đáy cũ D: cao / thấp hơn hẳn 2 nến mỗi bên


def ns(times) -> np.ndarray:
    """Mốc thời gian → int64 nanoseconds UTC (cột time có hoặc không có múi giờ)."""
    idx = pd.DatetimeIndex(times)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    return idx.as_unit("ns").asi8


def trading_day(times: pd.Series) -> pd.Series:
    """Ngày giao dịch của nến D chuẩn FX: đóng lúc 17:00 New York → giờ NY + 7 giờ rồi lấy ngày."""
    ny = times.dt.tz_convert("America/New_York").dt.tz_localize(None)
    return (ny + pd.Timedelta(hours=7)).dt.normalize()


def daily(h1: pd.DataFrame) -> pd.DataFrame:
    """Nến D từ H1 (h1 đã sắp theo thời gian): open/high/low/close + first/last = chỉ số nến H1 đầu / cuối của ngày."""
    g = h1.assign(day=trading_day(h1["time"]).to_numpy(), idx=np.arange(len(h1))).groupby("day", sort=True)
    return g.agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
                 first=("idx", "first"), last=("idx", "last")).reset_index()


def key_highs(hd: np.ndarray) -> np.ndarray:
    """key[c] = đỉnh swing D cũ chưa bị vượt (swing đã xác nhận trước nến c) mà nến D c có high ≥ nó — lấy đỉnh
    cao nhất nếu chạm nhiều đỉnh; NaN nếu không có (nến c không ở key level)."""
    n, s = len(hd), SWING_SIDE
    key, levels = np.full(n, np.nan), []
    for c in range(n):
        k = c - s - 1                     # swing k xác nhận khi nến k + s đóng = nến c − 1
        if k >= s and hd[k] > hd[k - s:k].max() and hd[k] > hd[k + 1:k + s + 1].max():
            levels.append(hd[k])
        taken = [x for x in levels if hd[c] >= x]
        if taken:
            key[c] = max(taken)
            levels = [x for x in levels if hd[c] < x]
    return key


def scan_candle2(O, H, C, i0: int, i1: int, crth: float):
    """
    Chiều BÁN, nến H1 i0..i1 của nến D c + 1: quét CRTH → TBS (đóng cửa > CRTH) → nến đóng dưới giá mở
    của Orderblock (nến tăng gần nhất từ TBS trở đi). Trả dict(i = nến xác nhận, top = đỉnh vùng quét,
    sweep / tbs / ob = chỉ số nến quét / TBS / Orderblock) hoặc None.
    """
    sweep, tbs, ob, top = None, None, None, -np.inf
    for i in range(i0, i1 + 1):
        if sweep is None and H[i] > crth:
            sweep = i
        if sweep is not None:
            top = max(top, H[i])
        if tbs is None:
            if C[i] > crth:
                tbs = i
                if C[i] > O[i]:
                    ob = i
            continue
        if ob is not None and C[i] < O[ob]:
            return dict(i=i, top=top, sweep=sweep, tbs=tbs, ob=ob)
        if C[i] > O[i]:
            ob = i
    return None


def find_orders(h1: pd.DataFrame, from_ns: int = 0) -> list:
    """Mọi tín hiệu CRT + TBS trên h1 (cột time UTC, open, high, low, close), created_ns ≥ from_ns, theo thời gian."""
    h1 = h1.sort_values("time").reset_index(drop=True)
    d = daily(h1)
    T = ns(h1["time"])
    O, H, L, C = (h1[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    do, dh, dl, dc = (d[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    rng = dh - dl
    thick = (rng > 0) & (np.abs(dc - do) >= THICK_BODY * rng)
    sides = {"SELL": (1.0, key_highs(dh)), "BUY": (-1.0, key_highs(-dl))}
    orders = []
    for c in range(len(d) - 1):
        if not thick[c]:
            continue
        i0, i1 = int(d["first"].iat[c + 1]), int(d["last"].iat[c + 1])
        cands = []
        for side, (s, key) in sides.items():
            if np.isnan(key[c]):
                continue
            crth, crtl = (dh[c], dl[c]) if s > 0 else (-dl[c], -dh[c])   # không gian BÁN
            hit = scan_candle2(s * O, H if s > 0 else -L, s * C, i0, i1, crth)
            if hit:
                cands.append(dict(side=side, crt_day=d["day"].iat[c].date(), created_ns=int(T[hit["i"]] + NS_HOUR),
                                  sl=s * hit["top"], tp1=s * (crth + crtl) / 2, tp2=s * crtl,
                                  # mốc để vẽ ảnh setup (plot_setup.py): mức key level, giờ mở nến quét / TBS / OB
                                  key_level=s * key[c], sweep_ns=int(T[hit["sweep"]]), tbs_ns=int(T[hit["tbs"]]),
                                  ob_ns=int(T[hit["ob"]])))
        cands.sort(key=lambda o: o["created_ns"])
        if len(cands) == 2 and cands[0]["created_ns"] == cands[1]["created_ns"]:
            continue                       # hai chiều xác nhận cùng nến → mơ hồ, bỏ
        if cands and cands[0]["created_ns"] >= from_ns:
            orders.append(cands[0])
    return orders
