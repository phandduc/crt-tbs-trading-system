"""
export_data.py — Xuất nến H1 + M1 từ terminal MT5 đang đăng nhập ra CSV + <NAME>_meta.json (sha256). Chỉ ĐỌC nến.

    python export_data.py --symbol Bitcoin.s --name BTCUSD --out data_crypto
    python export_data.py --symbol Ethereum.s --name ETHUSD --out data_crypto --start 2018-01-01

Lấy từ --start (mặc định 2015-01-01, sàn chỉ trả phần có) tới 00:00 UTC hôm nay (bỏ nến đang chạy). Giờ nến MT5 = giờ sàn;
BCR-MT5 là UTC — sàn đi trước UTC > 30 phút (theo tick) → dừng. Kiểm: M1 gộp thành H1 phải khớp H1 của sàn.
"""

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import MetaTrader5 as mt5
import pandas as pd

COLUMNS = ["time", "open", "high", "low", "close", "tick_volume", "spread"]
TFS = {"H1": mt5.TIMEFRAME_H1, "M1": mt5.TIMEFRAME_M1}


def fetch(symbol: str, tf: int, start: datetime, end: datetime) -> pd.DataFrame:
    """Nến [start, end) theo từng năm (copy_rates_range giới hạn số nến mỗi lần)."""
    parts, a = [], start
    while a < end:
        b = min(end, a.replace(year=a.year + 1))
        r = mt5.copy_rates_range(symbol, tf, a, b)
        if r is not None and len(r):
            parts.append(pd.DataFrame(r))
        a = b
    if not parts:
        return pd.DataFrame(columns=COLUMNS)
    df = pd.concat(parts).drop_duplicates("time").sort_values("time")
    df = df[df["time"] < int(end.timestamp())]
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    return df[COLUMNS].reset_index(drop=True)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description="Xuất nến H1 + M1 từ MT5 (chỉ đọc)")
    ap.add_argument("--symbol", required=True, help="tên mã CHÍNH XÁC trên sàn, vd Bitcoin.s")
    ap.add_argument("--name", required=True, help="tên file, vd BTCUSD")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--start", default="2015-01-01")
    args = ap.parse_args()
    if not mt5.initialize():
        sys.exit(f"✗ Khởi tạo MT5 lỗi: {mt5.last_error()}")
    try:
        info = mt5.symbol_info(args.symbol)
        if info is None or not mt5.symbol_select(args.symbol, True):
            sys.exit(f"✗ Sàn không có mã '{args.symbol}'.")
        tick = mt5.symbol_info_tick(args.symbol)
        if tick is not None and tick.time - time.time() > 1800:
            sys.exit("✗ Giờ sàn đi trước UTC > 30 phút — dữ liệu sẽ lệch mốc nến D, dừng.")
        start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
        end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        acct = mt5.account_info()
        args.out.mkdir(parents=True, exist_ok=True)
        meta = dict(symbol=args.symbol, name=args.name, broker=acct.company if acct else None,
                    server=acct.server if acct else None, exported_at=datetime.now(timezone.utc).isoformat(),
                    point=info.point, digits=info.digits, contract=info.trade_contract_size,
                    server_timezone="UTC (BCR-MT5)", timeframes={})
        dfs = {}
        for key, tf in TFS.items():
            df = fetch(args.symbol, tf, start, end)
            if df.empty:
                sys.exit(f"✗ {args.symbol} {key}: không có nến.")
            path = args.out / f"{args.name}_{key}.csv"
            df.to_csv(path, index=False)
            dfs[key] = df
            meta["timeframes"][key] = dict(file=path.name, sha256=sha256(path), bars=len(df),
                                           first_time=df["time"].iat[0].isoformat(),
                                           last_time=df["time"].iat[-1].isoformat())
            print(f"  ✓ {args.name} {key}: {len(df):,} nến {df['time'].iat[0]} → {df['time'].iat[-1]}")
        # M1 gộp H1 so với H1 của sàn (chỉ giờ có cả hai; M1 thiếu vài phút → high/low có thể lệch)
        m1 = dfs["M1"].set_index("time")
        agg = m1.resample("1h").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
        h1 = dfs["H1"].set_index("time").loc[lambda d: d.index >= m1.index[0]]
        both = agg.join(h1[["open", "high", "low", "close"]], rsuffix="_h1", how="inner")
        bad = sum((both[c] - both[f"{c}_h1"]).abs() > info.point / 2 for c in ("open", "high", "low", "close"))
        meta["verify"] = dict(h1_hours_compared=len(both), m1_to_h1_ohlc_mismatch_hours=int((bad > 0).sum()))
        print(f"  Kiểm M1 → H1: {len(both):,} giờ, lệch {int((bad > 0).sum())}")
        (args.out / f"{args.name}_meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
