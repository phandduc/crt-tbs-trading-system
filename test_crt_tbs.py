"""
test_crt_tbs.py — Kiểm logic CRT + TBS bằng dữ liệu tự dựng + kiểm chống rò rỉ tương lai trên dữ liệu thật.

    python test_crt_tbs.py            # test nhanh (vài giây)
    python test_crt_tbs.py --leak     # thêm: mọi tín hiệu XAUUSD vẫn xuất hiện khi cắt H1 tại lúc phát tín hiệu
    python test_crt_tbs.py --window [N]   # thêm: N nến H1 gần nhất (mặc định 30 000, như bot live tối thiểu)
                                          # ra cùng tín hiệu như lịch sử đầy đủ
"""

import sys

import numpy as np
import pandas as pd

import backtest
import crt_tbs

START = pd.Timestamp("2024-01-08 22:00", tz="UTC")       # 17:00 New York (giờ mùa đông) = đầu ngày giao dịch


def day_bars(o, h, l, c):
    """24 nến H1 của một ngày có OHLC (o, h, l, c)."""
    bars = [(o, o, o, o)] * 24
    bars[3], bars[6] = (o, h, o, o), (o, o, l, o)
    bars[23] = (o, max(o, c), min(o, c), c)
    return bars


def synthetic_h1(flip: bool = False) -> pd.DataFrame:
    days = [(95, 100, 90, 95), (95, 101, 91, 96), (96, 110, 95, 100),     # ngày 2: đỉnh swing 110
            (100, 105, 96, 100), (100, 104, 97, 98),                    # ngày 3, 4 xác nhận swing
            (98, 112, 97.5, 111.5)]                                     # ngày 5: nến CRT dày, chạm 110
    bars = [b for d in days for b in day_bars(*d)]
    bars += [(111, 111.5, 110.5, 111),            # nến c+1: chưa quét
             (111, 112.5, 110.8, 111.8),          # râu quét CRTH 112, đóng dưới → TWS, chưa phải TBS
             (111.8, 113, 111.5, 112.6),          # TBS: đóng > 112, nến tăng → OB mở 111.8
             (112.6, 113.5, 112.2, 113.2),        # nến tăng mới → OB mở 112.6
             (113.2, 113.4, 111.9, 112.0)]        # đóng 112.0 < 112.6 → xác nhận (nến thứ 5 của ngày)
    bars += [(112, 112, 112, 112)] * 19
    df = pd.DataFrame(bars, columns=["open", "high", "low", "close"])
    if flip:
        df = pd.DataFrame({"open": -df["open"], "high": -df["low"], "low": -df["high"], "close": -df["close"]})
    df.insert(0, "time", START + pd.to_timedelta(np.arange(len(df)), unit="h"))
    return df


def test_trading_day():
    t = pd.Series(pd.to_datetime(["2024-01-10 21:00", "2024-01-10 22:00", "2024-07-10 20:00", "2024-07-10 21:00"],
                                 utc=True))
    got = [x.strftime("%m-%d") for x in crt_tbs.trading_day(t)]
    assert got == ["01-10", "01-11", "07-10", "07-11"], got


def test_signal(flip: bool):
    orders = crt_tbs.find_orders(synthetic_h1(flip))
    assert len(orders) == 1, orders
    o, s = orders[0], -1 if flip else 1
    assert o["side"] == ("BUY" if flip else "SELL"), o
    assert o["created_ns"] == (START + pd.Timedelta(hours=6 * 24 + 5)).value, o
    assert (o["sl"], o["tp1"], o["tp2"]) == (s * 113.5, s * 104.75, s * 97.5), o


def test_no_signal_without_key_level():
    h1 = synthetic_h1()
    h1.loc[2 * 24 + 3, "high"] = 120             # đỉnh cũ 120 > high nến CRT 112 → không có key level
    assert crt_tbs.find_orders(h1) == []


def _m1(rows):
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df.insert(0, "time", pd.Timestamp("2024-01-01", tz="UTC") + pd.to_timedelta(np.arange(len(df)), unit="min"))
    df["spread"] = 0.0
    return df


def test_simulate():
    o = dict(side="SELL", created_ns=pd.Timestamp("2024-01-01", tz="UTC").value, sl=110.0, tp1=95.0, tp2=90.0)
    # TP1 rồi quay về giá khớp → BE: R = 0.5 × (P − 95) / 10, P = 100 − 5 × 0.01
    A = backtest.sim_arrays(_m1([(100, 101, 99, 100), (99, 99, 94, 95), (95, 101, 95, 100)]), "SELL")
    x = backtest.simulate(o, A, 0.01, 1.0)
    assert x["status"] == "TP1_BE" and abs(x["r"] - 0.5 * (99.95 - 95) / 10) < 1e-9, x
    # nến chạm cả SL lẫn TP1 → SL trước
    A = backtest.sim_arrays(_m1([(100, 111, 94, 100)]), "SELL")
    x = backtest.simulate(o, A, 0.01, 1.0)
    assert x["status"] == "SL" and abs(x["r"] - (99.95 - 110) / 10) < 1e-9, x
    # MUA (lật giá): TP1 + TP2
    ob = dict(side="BUY", created_ns=o["created_ns"], sl=90.0, tp1=105.0, tp2=110.0)
    A = backtest.sim_arrays(_m1([(100, 100, 99, 100), (100, 106, 100, 105), (105, 111, 105, 110)]), "BUY")
    x = backtest.simulate(ob, A, 0.01, 1.0)
    assert x["status"] == "TP1_TP2" and abs(x["r"] - (0.5 * 4.95 + 0.5 * 9.95) / 10) < 1e-9, x


def test_leak(symbol: str = "XAUUSD"):
    """Cắt H1 tại lúc phát tín hiệu (bỏ mọi nến đóng sau đó) → tín hiệu phải giống hệt."""
    h1, _ = backtest.load(symbol, backtest.OLD_REPO)
    orders = crt_tbs.find_orders(h1)
    close_ns = crt_tbs.ns(h1["time"]) + crt_tbs.NS_HOUR
    for o in orders:
        cut = crt_tbs.find_orders(h1[close_ns <= o["created_ns"]])
        assert cut and cut[-1] == o, (o, cut[-1:] if cut else None)
    print(f"  leak test {symbol}: {len(orders)} tín hiệu, 0 khác biệt")


def test_window(n: int, symbol: str, years: int = 2, random_bars: int = 300):
    """Bot live chỉ có n nến H1 gần nhất: tại lúc đóng mỗi nến kiểm (mọi nến phát tín hiệu trong `years` năm cuối
    + `random_bars` nến ngẫu nhiên) → tín hiệu từ n nến phải trùng tín hiệu từ toàn bộ lịch sử."""
    h1 = pd.concat([pd.read_csv(backtest.OLD_REPO / d / f"{symbol}_H1.csv", parse_dates=["time"])
                    for d in backtest.DATASETS[symbol]]).drop_duplicates("time").sort_values("time").reset_index(drop=True)
    close_ns = crt_tbs.ns(h1["time"]) + crt_tbs.NS_HOUR
    full = {o["created_ns"]: o for o in crt_tbs.find_orders(h1)}
    start = close_ns[-1] - years * 365 * 24 * crt_tbs.NS_HOUR
    rng = np.random.default_rng(20261017)
    ends = set(np.flatnonzero(np.isin(close_ns, [t for t in full if t >= start])))
    ends |= set(rng.choice(np.flatnonzero(close_ns >= start), random_bars, replace=False))
    for e in sorted(ends):
        got = crt_tbs.find_orders(h1.iloc[max(0, e + 1 - n):e + 1], from_ns=int(close_ns[e]))
        want = [full[close_ns[e]]] if close_ns[e] in full else []
        assert got == want, (symbol, h1["time"].iat[e], got, want)
    print(f"  window test {symbol} {n} nến H1: {len(ends)} thời điểm ({sum(close_ns[e] in full for e in ends)} "
          f"có tín hiệu), 0 khác biệt")


if __name__ == "__main__":
    test_trading_day()
    test_signal(flip=False)
    test_signal(flip=True)
    test_no_signal_without_key_level()
    test_simulate()
    print("  test nhanh: đạt")
    if "--leak" in sys.argv:
        test_leak()
    if "--window" in sys.argv:
        i = sys.argv.index("--window")
        n = int(sys.argv[i + 1]) if i + 1 < len(sys.argv) else 30_000
        for sym in ("XAUUSD", "EURUSD"):
            test_window(n, sym)
