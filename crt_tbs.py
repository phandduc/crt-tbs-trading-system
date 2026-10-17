"""
crt_tbs.py — Chiến lược CRT + TBS (Candle Range Theory + Turtle Body Soup). Quy tắc: RULES.md mục 2 (D → H1),
mục 5 (H4 → M5).

Chỉ dùng nến đã đóng. Tín hiệu phát ra lúc nến LTF xác nhận đóng (created_ns); giá vào do bên chạy lệnh lấy
(backtest: giá mở nến M1 đầu tiên từ created_ns; live: giá thị trường lúc đó).
Chiều MUA tính bằng cách lật giá (−x) rồi dùng đúng logic chiều BÁN.
"""

import numpy as np
import pandas as pd

NS_MIN = 60_000_000_000
NS_HOUR = 60 * NS_MIN
THICK_BODY = 0.5      # nến CRT dày: thân ≥ 50% biên độ
SWING_SIDE = 2        # đỉnh / đáy cũ D: cao / thấp hơn hẳn 2 nến mỗi bên


def ns(times) -> np.ndarray:
    """Mốc thời gian → int64 nanoseconds UTC (cột time có hoặc không có múi giờ)."""
    idx = pd.DatetimeIndex(times)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    return idx.as_unit("ns").asi8


def htf_bucket(times: pd.Series, hours: int) -> pd.Series:
    """Nến HTF chứa mỗi mốc: giờ New York + 7 giờ (nến D đóng 17:00 NY) rồi làm tròn xuống bội số `hours` giờ.
    hours = 24 → nến D chuẩn FX; hours = 4 → nến H4 mở 17 / 21 / 01 / 05 / 09 / 13 giờ NY."""
    ny = times.dt.tz_convert("America/New_York").dt.tz_localize(None)
    return (ny + pd.Timedelta(hours=7)).dt.floor(f"{hours}h")


def htf_candles(ltf: pd.DataFrame, hours: int) -> pd.DataFrame:
    """Nến HTF từ LTF (đã sắp theo thời gian): open/high/low/close + first/last = chỉ số nến LTF đầu / cuối."""
    g = ltf.assign(bucket=htf_bucket(ltf["time"], hours).to_numpy(), idx=np.arange(len(ltf))).groupby("bucket", sort=True)
    return g.agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
                 first=("idx", "first"), last=("idx", "last")).reset_index()


def key_highs(hd: np.ndarray) -> np.ndarray:
    """key[c] = nến HTF c có high ≥ một đỉnh swing HTF cũ chưa bị vượt (swing đã xác nhận trước nến c)."""
    n, s = len(hd), SWING_SIDE
    key, levels = np.zeros(n, bool), []
    for c in range(n):
        k = c - s - 1                     # swing k xác nhận khi nến k + s đóng = nến c − 1
        if k >= s and hd[k] > hd[k - s:k].max() and hd[k] > hd[k + 1:k + s + 1].max():
            levels.append(hd[k])
        if any(hd[c] >= x for x in levels):
            key[c] = True
            levels = [x for x in levels if hd[c] < x]
    return key


def scan_candle2(O, H, C, i0: int, i1: int, crth: float):
    """
    Chiều BÁN, nến LTF i0..i1 của nến HTF c + 1: quét CRTH → TBS (đóng cửa > CRTH) → nến đóng dưới giá mở
    của Orderblock (nến tăng gần nhất từ TBS trở đi). Trả (chỉ số nến xác nhận, đỉnh vùng quét) hoặc None.
    """
    purged, tbs, ob, top = False, False, None, -np.inf
    for i in range(i0, i1 + 1):
        if H[i] > crth:
            purged = True
        if purged:
            top = max(top, H[i])
        if not tbs:
            if C[i] > crth:
                tbs = True
                if C[i] > O[i]:
                    ob = O[i]
            continue
        if ob is not None and C[i] < ob:
            return i, top
        if C[i] > O[i]:
            ob = O[i]
    return None


def find_orders(ltf: pd.DataFrame, from_ns: int = 0, htf_hours: int = 24, ltf_minutes: int = 60) -> list:
    """Mọi tín hiệu CRT + TBS trên nến LTF (cột time UTC, open, high, low, close), nến CRT khung `htf_hours` giờ dựng
    từ chính LTF; created_ns ≥ from_ns, theo thời gian. Mặc định D → H1 (lần chạy 1)."""
    ltf = ltf.sort_values("time").reset_index(drop=True)
    d = htf_candles(ltf, htf_hours)
    T = ns(ltf["time"])
    O, H, L, C = (ltf[k].to_numpy(float) for k in ("open", "high", "low", "close"))
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
            if not key[c]:
                continue
            crth, crtl = (dh[c], dl[c]) if s > 0 else (-dl[c], -dh[c])   # không gian BÁN
            hit = scan_candle2(s * O, H if s > 0 else -L, s * C, i0, i1, crth)
            if hit:
                i, top = hit
                cands.append(dict(side=side, crt_start=ltf["time"].iat[int(d["first"].iat[c])],
                                  created_ns=int(T[i] + ltf_minutes * NS_MIN),
                                  sl=s * top, tp1=s * (crth + crtl) / 2, tp2=s * crtl))
        cands.sort(key=lambda o: o["created_ns"])
        if len(cands) == 2 and cands[0]["created_ns"] == cands[1]["created_ns"]:
            continue                       # hai chiều xác nhận cùng nến → mơ hồ, bỏ
        if cands and cands[0]["created_ns"] >= from_ns:
            orders.append(cands[0])
    return orders
