# CRT + TBS (D → H1)

Hệ thống giao dịch theo tài liệu CRT (Candle Range Theory) + TBS (Turtle Body Soup) của AR, tách biệt bot S2-4 cũ.
Quy tắc, tiêu chí và sổ chạy: **[RULES.md](RULES.md)** — đọc trước khi sửa gì.

> ⚠ **Backtest KHÔNG ĐẠT tiêu chí ghi trước** (311 lệnh, E[R] +0,064R, CI95 chứa 0, âm khi chi phí ×2).
> Bot chỉ để chạy **Demo** thu dữ liệu mới; mặc định chỉ báo tín hiệu, chặn tự đặt lệnh trên tài khoản thật.

## Tóm tắt chiến lược (chiều BÁN, MUA đối xứng)

1. Nến D (đóng 17:00 New York) **dày** (thân ≥ 50%) có high chạm một **đỉnh D cũ chưa bị lấy** → nến CRT.
2. Trong nến D kế tiếp, trên H1: quét CRTH → **TBS** = nến đầu tiên đóng cửa trên CRTH →
   **Model #1** = nến đóng dưới giá mở của nến tăng gần nhất (Orderblock) → vào lệnh thị trường.
3. SL = đỉnh vùng quét; TP1 = 50% nến CRT (chốt 50% + SL về giá vào); TP2 = CRTL. Một lệnh mở mỗi mã.

## File

| File | Vai trò |
|---|---|
| `crt_tbs.py` | Chiến lược: dựng nến D từ H1, key level, quét TBS / Model #1 → tín hiệu (dùng chung backtest + bot) |
| `backtest.py` | Backtest trên CSV của repo cũ (kiểm sha256), mô phỏng M1, thống kê + tiêu chí + bảng balance năm / tháng. `--risk-percent` / `--account` chỉ đổi bảng USD (rủi ro cố định theo vốn ban đầu, không tái đầu tư); số liệu theo R không đổi |
| `run_backtest.bat` | Menu chạy backtest: chọn mã, % rủi ro, vốn |
| `bot.py` | Bot live MT5, một tiến trình cho mọi mã; Telegram |
| `test_crt_tbs.py` | Test chiến lược / mô phỏng; `--leak` chống nhìn trước tương lai; `--window` cửa sổ nến live |
| `test_bot.py` | Smoke test bot với MT5 giả |
| `reports/thong_ke_D-H1.txt` | Báo cáo backtest đầy đủ (bảng theo năm / tháng) |

## Chạy

```
pip install MetaTrader5 pandas numpy
python backtest.py                    # 5 mã, ~40 giây, vốn 10 000 USD, rủi ro 1% / lệnh
python backtest.py --symbols XAUUSD --risk-percent 2 --account 5000
run_backtest.bat                      # bấm đúp: hỏi mã, % rủi ro, vốn
python test_crt_tbs.py --leak --window
python test_bot.py
copy .env.example .env                # rồi điền .env
python bot.py
```

Bot: mỗi 30 giây quản lý lệnh (dời hoà vốn) và quét nến H1 vừa đóng của từng mã. Khởi động sẽ dừng nếu tên mã
không đúng chính xác tên trên sàn, giờ sàn đi trước UTC + `SERVER_UTC_OFFSET_HOURS`, hoặc `AUTO_TRADE` trên tài
khoản thật mà chưa bật `ALLOW_REAL_ACCOUNT`. Cần ≥ 30 000 nến H1 lịch sử (đặt MT5 *Max bars in chart* = Unlimited).

### Khác biệt live ↔ backtest (chấp nhận)

- Live không quét bù nến bị lỡ khi bot tắt; tín hiệu cũ hơn 15 phút bị bỏ (backtest: tín hiệu nến H1 cuối tuần vào
  lệnh ở giá mở tuần sau — live bỏ).
- Live vào ở giá Bid/Ask lúc quét (trễ tới ~30 giây + chờ tick đầu của nến mới); backtest: giá mở nến M1 + spread + 5 point.
- Lot làm tròn theo bước khối lượng, chia 2 lệnh; không chia được 2 lệnh ≥ lot tối thiểu → bỏ (không tăng rủi ro).
- Hoà vốn: live dời SL về giá vào của lệnh, backtest về giá khớp sau chi phí.
- Giờ sàn lệch UTC cố định (`SERVER_UTC_OFFSET_HOURS`); sàn đổi giờ theo mùa thì nến D sẽ lệch 1 giờ nửa năm.
