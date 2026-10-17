"""
test_crt_tbs.py — Kiểm logic CRT + TBS bằng dữ liệu tự dựng + kiểm chống rò rỉ tương lai trên dữ liệu thật.

    python test_crt_tbs.py                # test nhanh (vài giây)
    python test_crt_tbs.py --leak         # thêm: mọi tín hiệu D → H1 XAUUSD vẫn y hệt khi cắt dữ liệu tại lúc phát
    python test_crt_tbs.py --leak H4-M5   # như trên cho H4 → M5 (mẫu 40 tín hiệu)
"""

import sys

import numpy as np
import pandas as pd

import backtest
import crt_tbs

START = pd.Timestamp("2024-01-08 22:00", tz="UTC")       # 17:00 New York (giờ mùa đông) = đầu ngày giao dịch


def candle_bars(o, h, l, c, per):
    """`per` nến LTF của một nến HTF có OHLC (o, h, l, c)."""
    bars = [(o, o, o, o)] * per
    bars[3], bars[6] = (o, h, o, o), (o, o, l, o)
    bars[-1] = (o, max(o, c), min(o, c), c)
    return bars


def synthetic(tf: str = "D-H1", flip: bool = False) -> pd.DataFrame:
    htf_hours, step = backtest.TIMEFRAMES[tf]
    per = htf_hours * 60 // step
    days = [(95, 100, 90, 95), (95, 101, 91, 96), (96, 110, 95, 100),     # nến 2: đỉnh swing 110
            (100, 105, 96, 100), (100, 104, 97, 98),                    # nến 3, 4 xác nhận swing
            (98, 112, 97.5, 111.5)]                                     # nến 5: nến CRT dày, chạm 110
    bars = [b for d in days for b in candle_bars(*d, per)]
    bars += [(111, 111.5, 110.5, 111),            # nến c+1: chưa quét
             (111, 112.5, 110.8, 111.8),          # râu quét CRTH 112, đóng dưới → TWS, chưa phải TBS
             (111.8, 113, 111.5, 112.6),          # TBS: đóng > 112, nến tăng → OB mở 111.8
             (112.6, 113.5, 112.2, 113.2),        # nến tăng mới → OB mở 112.6
             (113.2, 113.4, 111.9, 112.0)]        # đóng 112.0 < 112.6 → xác nhận (nến LTF thứ 5 của nến c+1)
    bars += [(112, 112, 112, 112)] * (per - 5)
    df = pd.DataFrame(bars, columns=["open", "high", "low", "close"])
    if flip:
        df = pd.DataFrame({"open": -df["open"], "high": -df["low"], "low": -df["high"], "close": -df["close"]})
    df.insert(0, "time", START + pd.to_timedelta(np.arange(len(df)) * step, unit="min"))
    return df


def test_htf_bucket():
    t = pd.Series(pd.to_datetime(["2024-01-10 21:00", "2024-01-10 22:00", "2024-07-10 20:00", "2024-07-10 21:00"],
                                 utc=True))
    got = [x.strftime("%m-%d") for x in crt_tbs.htf_bucket(t, 24)]
    assert got == ["01-10", "01-11", "07-10", "07-11"], got
    # H4: 00:59 / 01:00 / 04:55 / 05:00 giờ NY (mùa đông, UTC−5) → nến 21:00, 01:00, 01:00, 05:00
    t = pd.Series(pd.to_datetime(["2024-01-10 05:59", "2024-01-10 06:00", "2024-01-10 09:55", "2024-01-10 10:00"],
                                 utc=True))
    b = crt_tbs.htf_bucket(t, 4).tolist()
    assert b[0] < b[1] == b[2] < b[3], b


def test_signal(tf: str, flip: bool):
    htf_hours, step = backtest.TIMEFRAMES[tf]
    orders = crt_tbs.find_orders(synthetic(tf, flip), 0, htf_hours, step)
    assert len(orders) == 1, orders
    o, s = orders[0], -1 if flip else 1
    assert o["side"] == ("BUY" if flip else "SELL"), o
    assert o["created_ns"] == (START + pd.Timedelta(minutes=(6 * htf_hours * 60 // step + 5) * step)).value, o
    assert (o["sl"], o["tp1"], o["tp2"]) == (s * 113.5, s * 104.75, s * 97.5), o


def test_no_signal_without_key_level():
    h1 = synthetic()
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


def test_leak(tf: str = "D-H1", symbol: str = "XAUUSD", sample: int = 40):
    """Cắt LTF tại lúc phát tín hiệu (bỏ mọi nến đóng sau đó) → tín hiệu phải giống hệt.
    D → H1: mọi tín hiệu; khung khác: mẫu `sample` tín hiệu (mỗi lần dựng lại toàn bộ lịch sử rất chậm)."""
    htf_hours, step = backtest.TIMEFRAMES[tf]
    h1, m1 = backtest.load(symbol, backtest.OLD_REPO)
    ltf = h1 if step == 60 else backtest.build_m5(m1)
    orders = crt_tbs.find_orders(ltf, 0, htf_hours, step)
    check = orders
    if tf != "D-H1" and len(orders) > sample:
        idx = np.random.default_rng(20261017).choice(len(orders), sample, replace=False)
        check = [orders[i] for i in sorted(idx)]
    close_ns = crt_tbs.ns(ltf["time"]) + step * crt_tbs.NS_MIN
    for o in check:
        cut = crt_tbs.find_orders(ltf[close_ns <= o["created_ns"]], 0, htf_hours, step)
        assert cut and cut[-1] == o, (o, cut[-1:] if cut else None)
    print(f"  leak test {tf} {symbol}: {len(orders)} tín hiệu, kiểm {len(check)}, 0 khác biệt")


if __name__ == "__main__":
    test_htf_bucket()
    for tf in backtest.TIMEFRAMES:
        test_signal(tf, flip=False)
        test_signal(tf, flip=True)
    test_no_signal_without_key_level()
    test_simulate()
    print("  test nhanh: đạt")
    if "--leak" in sys.argv:
        i = sys.argv.index("--leak")
        test_leak(sys.argv[i + 1] if i + 1 < len(sys.argv) else "D-H1")
