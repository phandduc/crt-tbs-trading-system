"""
bot.py — Bot live CRT + TBS (D → H1) trên MetaTrader 5, một tiến trình cho mọi mã trong SYMBOLS (.env).

    python bot.py          # cấu hình: .env cạnh file này (mẫu: .env.example)

⚠ Chiến lược KHÔNG ĐẠT tiêu chí backtest (RULES.md) — chỉ chạy tài khoản DEMO để thu dữ liệu mới.

Mỗi 30 giây: quản lý lệnh đang mở, rồi với từng mã có nến H1 mới đóng (giờ sàn) → quét tín hiệu của ĐÚNG nến đó
(crt_tbs.find_orders, cùng quy tắc với backtest). Nến bị lỡ khi bot tắt không quét bù; tín hiệu cũ hơn
MAX_SIGNAL_AGE bị bỏ.
  Mọi tín hiệu gửi Telegram kèm ảnh setup (plot_setup.py, lưu ở charts/); ảnh lỗi → gửi chữ.
  AUTO_TRADE=false (mặc định): chỉ báo Telegram (kèm lot gợi ý).
  AUTO_TRADE=true: 2 lệnh thị trường 50/50 cùng SL (TP1 / TP2); lệnh TP1 đóng ở TP → SL lệnh TP2 về giá vào.
  Bỏ tín hiệu nếu: mã đang có lệnh của bot, giá ngoài khoảng TP1–SL, SL ≤ spread + 5 point, lot không chia đôi được.
  Tài khoản thật: từ chối AUTO_TRADE trừ khi ALLOW_REAL_ACCOUNT=true.
"""

import json
import math
import os
import sys
import time
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

import MetaTrader5 as mt5
import pandas as pd

import crt_tbs
import plot_setup

BASE_DIR = Path(__file__).resolve().parent


def load_env(path: Path = BASE_DIR / ".env"):
    """Đọc .env (KEY=giá trị, bỏ dòng # và ngoặc quanh giá trị) vào biến môi trường."""
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip().strip("\"'")


load_env()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
MT5_LOGIN, MT5_PASSWORD, MT5_SERVER = (os.environ.get(k, "") for k in ("MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER"))
SYMBOLS = [s.strip() for s in os.environ.get("SYMBOLS", "EURUSD.s,GBPUSD.s,AUDUSD.s,XAUUSD.s").split(",")
           if s.strip()]                         # mặc định: tên mã trên BCR-MT5 (kiểm 2026-10-17)
AUTO_TRADE = os.environ.get("AUTO_TRADE", "false").strip().lower() == "true"
ALLOW_REAL_ACCOUNT = os.environ.get("ALLOW_REAL_ACCOUNT", "false").strip().lower() == "true"
try:
    RISK_PERCENT = float(os.environ.get("RISK_PERCENT", "1.0"))
    SERVER_UTC_OFFSET_HOURS = int(os.environ.get("SERVER_UTC_OFFSET_HOURS", "0"))
except ValueError as e:      # dừng thay vì đoán: rủi ro / giờ nến sai làm lệnh khác hẳn backtest
    sys.exit(f"✗ .env: RISK_PERCENT phải là số, SERVER_UTC_OFFSET_HOURS phải là số nguyên ({e}).")

MAGIC = 20261017
STATE_FILE = BASE_DIR / "state.json"
CHART_DIR = BASE_DIR / "charts"         # ảnh setup của từng tín hiệu (plot_setup.py)
H1_BARS = 100_000           # lấy tối đa lịch sử sàn có: đỉnh / đáy D cũ có thể xa > 3 năm
MIN_H1_BARS = 30_000        # 30 000 nến (~5 năm) ra cùng tín hiệu như lịch sử đầy đủ, 20 000 thì không
                            # (test_crt_tbs.py --window); ít hơn → cảnh báo
SLIPPAGE_POINTS = 5.0       # bỏ lệnh nếu SL ≤ (spread + 5) point, như backtest
MAX_SIGNAL_AGE = 15 * 60    # giây sau khi nến xác nhận đóng
POLL_SECONDS = 30
KEEP_DONE_DAYS = 3


# ─── Telegram, trạng thái ───────────────────────────────────────────────────────

def telegram(text: str) -> bool:
    print(f"[{datetime.now():%H:%M:%S}] {text}")
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    req = urllib.request.Request(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                                 data=json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": text,
                                                  "parse_mode": "HTML"}).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:      # có kiểm chứng chỉ SSL: token nằm trong URL
            return bool(json.loads(r.read().decode("utf-8")).get("ok"))
    except Exception as e:
        print(f"  Lỗi gửi Telegram: {e}")
        return False


def telegram_photo(path: Path, caption: str) -> bool:
    """Gửi ảnh kèm chú thích (sendPhoto, multipart). False nếu chưa cấu hình / lỗi → bên gọi gửi tin nhắn chữ."""
    print(f"[{datetime.now():%H:%M:%S}] {caption}\n  ảnh: {path}")
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    b = uuid.uuid4().hex
    fields = {"chat_id": TELEGRAM_CHAT_ID, "caption": caption[:1024], "parse_mode": "HTML"}
    body = b"".join(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode("utf-8")
                    for k, v in fields.items())
    body += (f'--{b}\r\nContent-Disposition: form-data; name="photo"; filename="{path.name}"\r\n'
             f"Content-Type: image/png\r\n\r\n").encode("utf-8") + path.read_bytes() + f"\r\n--{b}--\r\n".encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return bool(json.loads(r.read().decode("utf-8")).get("ok"))
    except Exception as e:
        print(f"  Lỗi gửi ảnh Telegram: {e}")
        return False


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(state.get("orders"), dict):
                return state
        except Exception as e:
            print(f"Lỗi đọc {STATE_FILE.name}: {e}")
    return {"orders": {}}


def save_state(state: dict):
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, STATE_FILE)          # thay file trong một bước → mất điện giữa lúc ghi không để lại file hỏng


# ─── MT5 ────────────────────────────────────────────────────────────────────────

def connect() -> bool:
    if not mt5.initialize():
        print(f"Khởi tạo MT5 thất bại: {mt5.last_error()}")
        return False
    if MT5_LOGIN and not mt5.login(login=int(MT5_LOGIN), password=MT5_PASSWORD, server=MT5_SERVER):
        print(f"Đăng nhập MT5 {MT5_LOGIN} thất bại: {mt5.last_error()}")
        return False
    return True


def last_closed_bar(symbol: str, count: int):
    """Nến H1 ĐÃ ĐÓNG (giờ sàn theo tick) gần nhất, count nến; cột time UTC. None nếu MT5 lỗi."""
    rates, tick = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, count), mt5.symbol_info_tick(symbol)
    if rates is None or len(rates) == 0 or tick is None:
        return None
    df = pd.DataFrame(rates)
    df = df[df["time"] + 3600 <= tick.time]
    df["time"] = pd.to_datetime(df["time"] - SERVER_UTC_OFFSET_HOURS * 3600, unit="s", utc=True)
    return df[["time", "open", "high", "low", "close"]].reset_index(drop=True)


def _decimals(step: float) -> int:
    s = f"{step:.10f}".rstrip("0")
    return len(s.split(".")[1]) if "." in s else 0


def split_lots(info, distance: float) -> list:
    """Lot theo RISK_PERCENT balance, làm tròn xuống volume_step, chia 2 lệnh (lệnh TP1 phần lớn hơn).
    [] nếu không đủ 2 lệnh ≥ volume_min (không tăng rủi ro để chia được)."""
    acct = mt5.account_info()
    if acct is None or info.trade_tick_size <= 0 or info.trade_tick_value <= 0 or distance <= 0:
        return []
    loss_per_lot = distance / info.trade_tick_size * info.trade_tick_value
    units = math.floor(min(acct.balance * RISK_PERCENT / 100 / loss_per_lot, info.volume_max) / info.volume_step + 1e-9)
    u1, dec = (units + 1) // 2, _decimals(info.volume_step)
    vols = [round(u1 * info.volume_step, dec), round((units - u1) * info.volume_step, dec)]
    return vols if min(vols) >= info.volume_min else []


def _filling(info):
    if info.filling_mode & mt5.SYMBOL_FILLING_FOK:
        return mt5.ORDER_FILLING_FOK
    if info.filling_mode & mt5.SYMBOL_FILLING_IOC:
        return mt5.ORDER_FILLING_IOC
    return mt5.ORDER_FILLING_RETURN


def send_market(symbol: str, info, side: str, volume: float, sl: float, tp: float, comment: str):
    """Trả (ticket, None) hoặc (None, lỗi)."""
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return None, "không lấy được tick"
    buy = side == "BUY"
    res = mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": volume,
                          "type": mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL,
                          "price": tick.ask if buy else tick.bid, "sl": round(sl, info.digits),
                          "tp": round(tp, info.digits), "deviation": 20, "magic": MAGIC, "comment": comment,
                          "type_time": mt5.ORDER_TIME_GTC, "type_filling": _filling(info)})
    if res is None:
        return None, f"order_send trả None ({mt5.last_error()})"
    if res.retcode != mt5.TRADE_RETCODE_DONE:
        return None, f"code {res.retcode}: {res.comment}"
    return int(res.order), None


# ─── Tín hiệu ───────────────────────────────────────────────────────────────────

def scan(symbol: str, state: dict):
    """Quét tín hiệu của nến H1 vừa đóng."""
    h1 = last_closed_bar(symbol, H1_BARS)
    if h1 is None or len(h1) < 500:
        print(f"  {symbol}: thiếu nến H1, bỏ qua lần quét này")
        return
    last_close_ns = int(crt_tbs.ns(h1["time"].iloc[-1:])[0] + crt_tbs.NS_HOUR)
    for o in crt_tbs.find_orders(h1, from_ns=last_close_ns):
        oid = f"{symbol}|{o['crt_day']}|{o['side']}"
        if oid not in state["orders"]:
            handle(symbol, oid, o, state, h1)


def handle(symbol: str, oid: str, o: dict, state: dict, h1: pd.DataFrame = None):
    """Xử lý một tín hiệu (bỏ / chỉ báo / vào lệnh) rồi báo Telegram kèm ảnh setup (vẽ SAU khi đặt lệnh)."""
    info, tick = mt5.symbol_info(symbol), mt5.symbol_info_tick(symbol)
    s = 1.0 if o["side"] == "SELL" else -1.0                     # không gian BÁN: s × giá
    rec = dict(symbol=symbol, side=o["side"], sl=o["sl"], tp1=o["tp1"], tp2=o["tp2"], crt_day=str(o["crt_day"]),
               created=int(o["created_ns"] // 1_000_000_000), tickets=[], status="signal", be_done=False)
    state["orders"][oid] = rec
    reason, vols, price = None, [], None
    positions = mt5.positions_get(symbol=symbol)
    if info is None or tick is None or positions is None:
        reason = "MT5 không trả thông tin mã / giá / lệnh"
    else:
        price = tick.bid if s > 0 else tick.ask
        age = tick.time - SERVER_UTC_OFFSET_HOURS * 3600 - rec["created"]
        if age > MAX_SIGNAL_AGE:
            reason = f"tín hiệu đã cũ {age // 60} phút"
        elif any(p.magic == MAGIC for p in positions):
            reason = "mã đang có lệnh của bot (một lệnh mỗi mã)"
        elif not (s * o["tp1"] < s * price < s * o["sl"]):
            reason = f"giá {price} ngoài khoảng TP1–SL"
        elif abs(o["sl"] - price) <= (info.spread + SLIPPAGE_POINTS) * info.point:
            reason = "SL không lớn hơn chi phí (spread + 5 point)"
        else:
            vols = split_lots(info, abs(o["sl"] - price))
            if not vols:
                reason = "lot theo rủi ro không chia được 2 lệnh ≥ lot tối thiểu"
    rr = abs(o["tp1"] - price) / abs(o["sl"] - price) if price is not None and reason is None else None
    px = lambda x: "?" if x is None else f"{x:.{info.digits}f}" if info is not None else f"{x:g}"
    head = (f"{'🔴 BÁN' if s > 0 else '🟢 MUA'} <b>{symbol}</b> — CRT + TBS (D → H1)\n"
            f"Nến CRT {rec['crt_day']} | giá {px(price)} | SL {px(o['sl'])} | TP1 {px(o['tp1'])} | TP2 {px(o['tp2'])}"
            + (f" | RR tới TP1 {rr:.2f}" if rr else ""))

    def notify(text):
        """Gửi kèm ảnh setup; vẽ / gửi ảnh lỗi → gửi chữ (không để lỗi vẽ ảnh chặn bot)."""
        try:
            png = CHART_DIR / f"{oid.replace('|', '_')}.png"
            plot_setup.plot_setup(h1, o, info.digits if info else 5, entry=price, out_png=png,
                                  title=f"CRT + TBS | {symbol} {o['side']} | nến CRT {o['crt_day']}")
            if telegram_photo(png, text):
                return
        except Exception as e:
            print(f"  Lỗi vẽ ảnh setup: {e!r}")
        telegram(text)

    if reason:
        rec.update(status="done", reason=reason, done_at=time.time())
        save_state(state)
        notify(f"{head}\n⏭️ Bỏ: {reason}")
        return
    if not AUTO_TRADE:
        rec.update(status="done", done_at=time.time())
        save_state(state)
        notify(f"{head}\n📣 Chỉ báo tín hiệu (AUTO_TRADE tắt) — lot gợi ý {vols[0]} (TP1) + {vols[1]} (TP2)")
        return
    errors = []
    for n, (vol, tp) in enumerate(zip(vols, (o["tp1"], o["tp2"])), 1):
        ticket, err = send_market(symbol, info, o["side"], vol, o["sl"], tp, f"CRT TBS {n}/2")
        rec["tickets"].append(ticket)
        if err:
            errors.append(f"lệnh {n}: {err}")
    placed = [t for t in rec["tickets"] if t is not None]
    rec.update(volumes=vols, status="open" if placed else "done", done_at=None if placed else time.time())
    save_state(state)
    notify(f"{head}\n✅ Đã vào {vols[0]} + {vols[1]} lot, ticket {placed}"
           + (f"\n⚠️ Lỗi: {'; '.join(errors)}" if errors else ""))


# ─── Quản lý lệnh ───────────────────────────────────────────────────────────────

def _closed_at_tp(ticket: int, rec: dict):
    """Lệnh TP1 đóng ở TP: True / False (SL, đóng tay…) / None nếu lịch sử deal chưa có."""
    out = [d for d in (mt5.history_deals_get(position=ticket) or []) if d.entry == mt5.DEAL_ENTRY_OUT]
    if not out:
        return None
    s = 1.0 if rec["side"] == "SELL" else -1.0
    return out[-1].reason == mt5.DEAL_REASON_TP or s * out[-1].price <= s * rec["tp1"]


def manage(state: dict):
    """Lệnh TP1 đóng ở TP → SL lệnh TP2 về giá vào; hết lệnh → done; xoá bản ghi cũ hơn KEEP_DONE_DAYS."""
    changed, now = False, time.time()
    for oid, rec in list(state["orders"].items()):
        if rec["status"] != "open":
            if now - (rec.get("done_at") or rec["created"]) > KEEP_DONE_DAYS * 86400:
                del state["orders"][oid]
                changed = True
            continue
        positions = mt5.positions_get(symbol=rec["symbol"])
        if positions is None:              # MT5 lỗi → không biết lệnh còn hay mất: xét lại lần sau
            continue
        live = {p.identifier: p for p in positions if p.magic == MAGIC}
        t1, t2 = rec["tickets"]
        if t1 not in live and t2 not in live:
            rec.update(status="done", done_at=now)
            changed = True
            continue
        if t1 is not None and t1 not in live and t2 in live and not rec["be_done"] and not rec.get("be_skip"):
            at_tp, pos = _closed_at_tp(t1, rec), live[t2]
            if at_tp:
                res = mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "symbol": pos.symbol, "position": pos.ticket,
                                      "sl": pos.price_open, "tp": pos.tp})
                if res is not None and res.retcode == mt5.TRADE_RETCODE_DONE:
                    rec["be_done"] = changed = True
                    telegram(f"🛡️ <b>{rec['symbol']}</b>: TP1 đã chốt → SL lệnh #{pos.ticket} về giá vào {pos.price_open}")
            elif at_tp is False:           # TP1 đóng vì SL / đóng tay → giữ SL như backtest
                rec["be_skip"] = changed = True
    if changed:
        save_state(state)


# ─── Vòng lặp ───────────────────────────────────────────────────────────────────

def check_setup():
    """Mã phải có đúng tên trên sàn; giờ sàn không được đi trước UTC + SERVER_UTC_OFFSET_HOURS; tài khoản thật
    không được AUTO_TRADE nếu chưa ALLOW_REAL_ACCOUNT. Sai → dừng. Lịch sử H1 ngắn → chỉ cảnh báo."""
    for sym in SYMBOLS:
        if mt5.symbol_info(sym) is None or not mt5.symbol_select(sym, True):
            near = [x.name for x in (mt5.symbols_get(group=f"*{sym}*") or [])]
            sys.exit(f"✗ Sàn không có mã '{sym}'. Tên gần giống: {near or 'không có'} — sửa SYMBOLS trong .env.")
        h1 = last_closed_bar(sym, H1_BARS)
        if h1 is None or len(h1) < MIN_H1_BARS:
            telegram(f"⚠️ {sym}: MT5 chỉ trả {0 if h1 is None else len(h1)} nến H1 (< {MIN_H1_BARS}) — có thể lỡ key level "
                     f"xa. Đặt Tools → Options → Charts → Max bars in chart = Unlimited rồi mở biểu đồ H1 cuộn về quá khứ.")
    tick = mt5.symbol_info_tick(SYMBOLS[0])
    ahead = (tick.time - SERVER_UTC_OFFSET_HOURS * 3600 - time.time()) if tick is not None else 0
    if ahead > 1800:                       # tick cũ chỉ lùi về quá khứ; đi trước = sai múi giờ sàn
        sys.exit(f"✗ Giờ sàn đi trước UTC {ahead / 3600:.1f} giờ — đặt SERVER_UTC_OFFSET_HOURS trong .env "
                 f"(nến D phải đóng lúc 17:00 New York như backtest).")
    acct = mt5.account_info()
    if AUTO_TRADE and acct is not None and acct.trade_mode == mt5.ACCOUNT_TRADE_MODE_REAL and not ALLOW_REAL_ACCOUNT:
        sys.exit("✗ AUTO_TRADE trên tài khoản THẬT bị chặn: chiến lược chưa đạt tiêu chí backtest. Dùng tài khoản Demo "
                 "(hoặc tự đặt ALLOW_REAL_ACCOUNT=true nếu chấp nhận rủi ro).")
    return acct


def main():
    if not connect():
        sys.exit(1)
    acct = check_setup()
    telegram(f"🟢 <b>Bot CRT + TBS (D → H1)</b> khởi chạy {datetime.now():%Y-%m-%d %H:%M}\n"
             f"Tài khoản {getattr(acct, 'login', '?')} ({'DEMO' if acct and acct.trade_mode != mt5.ACCOUNT_TRADE_MODE_REAL else 'THẬT'}) | "
             f"AUTO_TRADE {'BẬT' if AUTO_TRADE else 'TẮT'} | rủi ro {RISK_PERCENT}%/lệnh | magic {MAGIC}\n"
             f"Mã: {', '.join(SYMBOLS)}\n⚠️ Chiến lược KHÔNG ĐẠT tiêu chí backtest — chỉ dùng để chạy Demo.")
    state, last_bar, lost = load_state(), {}, False
    try:
        while True:
            try:
                if mt5.terminal_info() is None and not connect():
                    if not lost:
                        telegram("⚠️ Bot CRT + TBS: mất kết nối MT5, thử lại mỗi 30 giây.")
                    lost = True
                    time.sleep(POLL_SECONDS)
                    continue
                if lost:
                    telegram("✅ Bot CRT + TBS: đã kết nối lại MT5.")
                    lost = False
                manage(state)
                for sym in SYMBOLS:
                    bar = last_closed_bar(sym, 3)
                    if bar is not None and len(bar) and bar["time"].iat[-1] != last_bar.get(sym):
                        last_bar[sym] = bar["time"].iat[-1]
                        scan(sym, state)
            except Exception as e:
                print(f"[Lỗi vòng lặp] {e!r}")
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        print("Bot đã dừng.")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
