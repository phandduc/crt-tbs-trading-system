"""
test_bot.py — Smoke test bot.py với MT5 GIẢ (không kết nối sàn, không gửi Telegram, file trạng thái tạm).

    python test_bot.py
"""

import sys
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pandas as pd

import test_crt_tbs


class FakeMT5(types.ModuleType):
    TIMEFRAME_H1, ORDER_TYPE_BUY, ORDER_TYPE_SELL = 16385, 0, 1
    TRADE_ACTION_DEAL, TRADE_ACTION_SLTP, ORDER_TIME_GTC = 1, 6, 0
    SYMBOL_FILLING_FOK, SYMBOL_FILLING_IOC = 1, 2
    ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 1, 2
    TRADE_RETCODE_DONE, DEAL_ENTRY_OUT, DEAL_REASON_TP = 10009, 1, 5
    ACCOUNT_TRADE_MODE_DEMO, ACCOUNT_TRADE_MODE_REAL = 0, 2

    def __init__(self):
        super().__init__("MetaTrader5")
        h1 = test_crt_tbs.synthetic_h1()
        flat = pd.DataFrame({"time": h1["time"].iat[0] - pd.to_timedelta(np.arange(504, 0, -1), unit="h"),
                             "open": 95.0, "high": 95.0, "low": 95.0, "close": 95.0})   # ≥ 500 nến như bot cần
        h1 = pd.concat([flat, h1], ignore_index=True)
        h1["time"] = test_crt_tbs.crt_tbs.ns(h1["time"]) // 10**9
        self.rates = h1.iloc[:504 + 150]            # nến cuối (504 + 149) đang chạy; nến 504 + 148 vừa xác nhận
        self.reset()

    def reset(self, bid=112.0, late=10, balance=10_000.0, real=False):
        self.tick = NS(time=int(self.rates["time"].iat[-1]) + late, bid=bid, ask=bid + 0.1)
        self.account = NS(login=1, balance=balance, trade_mode=2 if real else 0)
        self.positions, self.deals, self.sent, self.next_ticket = [], {}, [], 1001

    def initialize(self): return True
    def login(self, **kw): return True
    def last_error(self): return (0, "ok")
    def terminal_info(self): return NS()
    def shutdown(self): pass
    def symbol_select(self, s, on): return s == "XAUUSD"
    def symbols_get(self, group=""): return [NS(name="XAUUSD.mini")]
    def account_info(self): return self.account
    def symbol_info_tick(self, s): return self.tick
    def copy_rates_from_pos(self, s, tf, pos, count): return self.rates.iloc[-count:].copy()
    def positions_get(self, symbol=None): return list(self.positions)
    def history_deals_get(self, position=None): return self.deals.get(position, [])

    def symbol_info(self, s):
        if s != "XAUUSD":
            return None
        return NS(point=0.01, digits=2, spread=10, trade_tick_size=0.01, trade_tick_value=1.0, volume_step=0.01,
                  volume_min=0.01, volume_max=100.0, filling_mode=1)

    def order_send(self, req):
        self.sent.append(req)
        t = self.next_ticket
        self.next_ticket += 1
        return NS(retcode=self.TRADE_RETCODE_DONE, order=t, comment="ok")


mt5 = FakeMT5()
sys.modules["MetaTrader5"] = mt5
import bot  # noqa: E402  (sau khi thay MetaTrader5 bằng bản giả)

msgs = []
bot.telegram = msgs.append
bot.SYMBOLS = ["XAUUSD"]
bot.STATE_FILE = Path(tempfile.mkdtemp()) / "state.json"


def fresh(**kw):
    mt5.reset(**kw)
    msgs.clear()
    bot.STATE_FILE.unlink(missing_ok=True)
    return bot.load_state()


def test_alert_only():
    bot.AUTO_TRADE = False
    state = fresh()
    bot.scan("XAUUSD", state)
    assert len(msgs) == 1 and "Chỉ báo tín hiệu" in msgs[0] and "0.33 (TP1) + 0.33 (TP2)" in msgs[0], msgs
    assert mt5.sent == [] and len(state["orders"]) == 1
    bot.scan("XAUUSD", bot.load_state())                    # khởi động lại cùng giờ → không báo trùng
    assert len(msgs) == 1, msgs


def test_auto_trade_and_break_even():
    bot.AUTO_TRADE = True
    state = fresh()
    bot.scan("XAUUSD", state)
    a, b = mt5.sent
    assert (a["type"], a["volume"], a["sl"], a["tp"], a["price"], a["magic"]) == (1, 0.33, 113.5, 104.75, 112.0, bot.MAGIC), a
    assert (b["volume"], b["tp"]) == (0.33, 97.5), b
    rec = next(iter(state["orders"].values()))
    assert rec["status"] == "open" and rec["tickets"] == [1001, 1002], rec
    p2 = NS(identifier=1002, ticket=1002, magic=bot.MAGIC, symbol="XAUUSD", price_open=112.0, tp=97.5)
    mt5.positions = [NS(identifier=1001, ticket=1001, magic=bot.MAGIC, symbol="XAUUSD", price_open=112.0, tp=104.75), p2]
    bot.manage(state)
    assert len(mt5.sent) == 2                                # cả hai còn mở → không làm gì
    mt5.positions = [p2]
    mt5.deals[1001] = [NS(entry=mt5.DEAL_ENTRY_OUT, reason=mt5.DEAL_REASON_TP, price=104.75)]
    bot.manage(state)
    be = mt5.sent[-1]
    assert be["action"] == mt5.TRADE_ACTION_SLTP and be["position"] == 1002 and be["sl"] == 112.0, be
    assert rec["be_done"] and "về giá vào" in msgs[-1]
    mt5.positions = []
    bot.manage(state)
    assert rec["status"] == "done"
    assert bot.load_state()["orders"][next(iter(state["orders"]))]["status"] == "done"   # đã ghi file


def test_skip_reasons():
    bot.AUTO_TRADE = True
    cases = [(dict(bid=104.0), "ngoài khoảng TP1–SL"), (dict(late=20 * 60), "đã cũ"),
             (dict(balance=100.0), "không chia được"), (dict(), "đang có lệnh")]
    for kw, why in cases:
        state = fresh(**kw)
        if why == "đang có lệnh":
            mt5.positions = [NS(identifier=9, ticket=9, magic=bot.MAGIC, symbol="XAUUSD", price_open=1.0, tp=0.0)]
        bot.scan("XAUUSD", state)
        assert mt5.sent == [] and len(msgs) == 1 and why in msgs[0], (why, msgs)


def test_setup_guards():
    bot.AUTO_TRADE = True
    fresh(real=True)
    for change, why in ((lambda: None, "tài khoản THẬT"),
                        (lambda: setattr(mt5, "account", NS(login=1, balance=1.0, trade_mode=0)) or
                         setattr(mt5.tick, "time", int(pd.Timestamp.now().timestamp()) + 7200), "đi trước UTC"),
                        (lambda: setattr(bot, "SYMBOLS", ["XAUUSD."]), "XAUUSD.mini")):
        change()
        try:
            bot.check_setup()
            raise AssertionError(f"check_setup không dừng: {why}")
        except SystemExit as e:
            assert why in str(e), (why, e)
    bot.SYMBOLS = ["XAUUSD"]


if __name__ == "__main__":
    test_alert_only()
    test_auto_trade_and_break_even()
    test_skip_reasons()
    test_setup_guards()
    print("  smoke test bot (MT5 giả): đạt")
