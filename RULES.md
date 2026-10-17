# CRT + TBS (khung D → H1) — quy tắc và tiêu chí đánh giá

> Ghi 2026-10-17, TRƯỚC khi chạy backtest lần nào. Hệ thống tách biệt với bot S2-4 cũ
> (`C:\Users\Duc\.gemini\antigravity\scratch\xauusd_trading_bot`), chỉ đọc CSV dữ liệu của repo đó.

## 1. Nguồn quy tắc

| Quy tắc | Nguồn |
|---|---|
| Nến CRT, CRTH / CRTL / 50%, nến dày = A+ | Tài liệu AR ("Logic behind CRT + TBS", ảnh "CRT + TBS market algorithm") |
| TBS = nến LTF ĐẦU TIÊN quét mức cao / thấp cũ bằng **giá đóng cửa thân nến**; chỉ râu (TWS) = không vào | "Clarification of CRT entry method TBS", "Types of Turtle Soup", "Examples of TBS" |
| Model #1 = Orderblock, vào lệnh sau xác nhận | Ảnh "market algorithm" |
| TP1 = 50% nến CRT: chốt một phần + SL về hoà vốn; TP2 = CRTL / CRTH | Ảnh "market algorithm" |
| Khung D (CRT + key level) → H1 (TBS + Model #1) | "Timeframe alignment" (day trading), "Trading routine" |
| Không lọc giờ 1 / 5 / 9 AM | "Importance of timing", "Secrets behind 1AM, 5AM, 9AM" |
| Model #1, SL, key level, khung D → H1 | **Người dùng chốt 2026-10-17** (tài liệu không định nghĩa) |
| Mọi tham số số học ở mục 2 (50% thân, swing 2-2, chia 50/50, 1 lệnh / mã…) | **Mặc định do Claude đặt**, không tinh chỉnh |

## 2. Quy tắc (chiều BÁN; MUA đối xứng)

1. **Nến D** theo chuẩn FX (TradingView): đóng lúc **17:00 New York** (tự đổi giờ mùa hè). Dữ liệu nến là UTC.
   Dựng nến D từ nến H1.
2. **Nến CRT** = nến D c đã đóng, **dày**: |close − open| ≥ 50% × (high − low). CRTH = high, CRTL = low, 50% = giữa.
3. **Key level (đỉnh cũ D):** đỉnh swing D (cao hơn hẳn 2 nến mỗi bên, đã xác nhận trước nến c) **chưa bị nến nào vượt**;
   nến CRT c có high ≥ đỉnh đó (chạm / quét đỉnh cũ). Không giới hạn độ xa, không dung sai.
4. **Chỉ trong nến D kế tiếp (c + 1)**, trên H1:
   - **Quét:** nến H1 đầu tiên có high > CRTH.
   - **TBS:** nến H1 đầu tiên **đóng cửa > CRTH**. Chỉ râu vượt (TWS) không tính.
   - **Orderblock (Model #1):** nến H1 TĂNG (close > open) gần nhất, tính từ nến TBS trở đi.
   - **Xác nhận:** một nến H1 sau TBS **đóng cửa < giá mở của Orderblock** → tín hiệu lúc nến này đóng.
   - Nến c + 1 đóng mà chưa xác nhận → huỷ setup.
5. **Vào lệnh thị trường** ngay khi nến xác nhận đóng (backtest: giá mở nến M1 đầu tiên từ lúc đó).
6. **SL** = high cao nhất từ nến quét tới nến xác nhận (đỉnh vùng quét). **TP1** = 50% nến CRT, **TP2** = CRTL.
7. Bỏ lệnh nếu không có TP1 < giá vào < SL, hoặc khoảng SL ≤ chi phí (spread + 5 point).
8. **Quản lý:** 50% khối lượng chốt ở TP1, 50% còn lại tới TP2; chạm TP1 → SL phần còn lại về giá khớp (từ nến M1 sau).
   Không giới hạn thời gian giữ lệnh.
9. Một nến CRT tối đa một lệnh (nếu cả hai chiều cùng có tín hiệu: lấy tín hiệu xác nhận trước; trùng giờ → bỏ).
   **Một lệnh mở mỗi mã** — tín hiệu đến khi mã đang có lệnh → bỏ.

## 3. Mô phỏng (backtest)

- Trên nến M1, giá Bid. Chi phí lúc vào = (spread nến M1 khớp + 5 point) × hệ số chi phí, trừ vào giá khớp.
- Nến M1 chạm cả SL lẫn TP → SL trước. Giá mở nến đã vượt mức dừng (gap) → thoát ở giá mở.
- R = lãi / lỗ (gồm chi phí) ÷ (SL − giá vào danh nghĩa). Lệnh còn mở cuối dữ liệu → không tính.
- Dữ liệu (sha256 trong `<SYMBOL>_meta.json` của repo cũ; lệch hash → dừng). Các thư mục nối tiếp, trùng giờ giữ
  bản thư mục trước; 30 ngày đầu chỉ để dựng đỉnh / đáy cũ:

| Mã | Thư mục | Giai đoạn nến |
|---|---|---|
| XAUUSD | `data_2021` + `data` | 2021-08 → 2026-10 |
| EURUSD | `data_2020` + `data_2021` + `data` | 2019-10 → 2026-10 |
| GBPUSD, AUDUSD, NZDUSD | `data_2020` | 2019-10 → 2021-12 |

  Ghi nhận trước: spread EURUSD trong `data_2021` (2022 → 2023-10) là giá trị điền sẵn ≈ 50 point → chi phí bị tính
  cao hơn thực tế (thận trọng, không sửa). Thiếu USDCAD, USDCHF (cần xuất từ MT5).
- Dữ liệu này đã dùng để nghiên cứu S2-4 nhưng **chưa từng dùng cho CRT + TBS**; quy tắc trên chốt trước khi chạy,
  nên lần chạy đầu tiên là kiểm tra hợp lệ.

## 4. Tiêu chí đạt (ghi TRƯỚC khi chạy; phải đủ TẤT CẢ)

1. E[R] gộp mọi mã > 0 ở chi phí ×1 VÀ ×2.
2. CI95 bootstrap của E[R] gộp (×1) có cận dưới > 0.
3. E[R] > 0 trên ≥ 4/5 mã (×1).
4. E[R] gộp > 0 ở cả lệnh MUA VÀ lệnh BÁN (×1).
5. E[R] gộp > 0 ở ≥ 2/3 số năm (theo năm khớp lệnh) có ≥ 20 lệnh (×1).

Chạy đúng một lần. **Không đạt → không tinh chỉnh tham số trên dữ liệu này**; mọi biến thể sau đó phải ghi là
"trong mẫu" và chỉ được tin khi qua dữ liệu mới (Demo hoặc mã / giai đoạn chưa dùng).
Đạt → vẫn chỉ là ứng viên: chạy Demo trước khi dùng tiền thật.

## 5. Lần chạy 2 — H4 → M5 (TRONG MẪU) — ĐÃ XOÁ KHỎI CODE

> 2026-10-17, người dùng yêu cầu: xoá toàn bộ nhánh H4 → M5 (code, `run2.log`, báo cáo). Mục này và dòng 2 của sổ chạy
> giữ lại làm lịch sử: số lần thử trên dữ liệu này vẫn là **2**. Khôi phục code: commit bb29202.

Ghi 2026-10-17, TRƯỚC khi viết code và chạy. Người dùng yêu cầu sau khi lần chạy 1 (D → H1) không đạt.

- **Đây là kết quả TRONG MẪU:** lần thử thứ 2 trên cùng dữ liệu, chọn sau khi đã thấy lần 1 thất bại. Số lần thử trên
  dữ liệu này: **2**. Kể cả đạt mọi tiêu chí cũng chỉ là ứng viên yếu — phải qua Demo / dữ liệu mới mới được tin.
- Khác lần 1 **chỉ ở khung** (theo tài liệu "Timeframe alignment": CRT H4 → TBS + Model #1 trên M5, short-term trading):
  - Nến **H4** mở lúc 17:00 / 21:00 / 01:00 / 05:00 / 09:00 / 13:00 giờ New York (cùng gốc với nến D đóng 17:00 NY),
    dựng từ nến M5; nến M5 dựng từ M1 (nhãn = mốc đầu nến).
  - Key level = đỉnh / đáy swing **H4** (2 nến mỗi bên) chưa bị lấy. Nến 2 = nến H4 kế tiếp; quét, TBS, Orderblock,
    xác nhận đều trên **M5** trong nến H4 đó.
- Giữ nguyên mọi thứ khác ở mục 2–3: thân ≥ 50%, SL đỉnh vùng quét, TP1 50%, TP2 CRTL, chia 50/50 + BE, một lệnh mở
  mỗi mã, chi phí (spread + 5 point), cùng 5 mã và dữ liệu, 30 ngày đầu khởi động.
- Cùng 5 tiêu chí ở mục 4, chạy đúng một lần. Không đạt → không tinh chỉnh tiếp trên dữ liệu này.

## 6. Sổ chạy

| # | Ngày | Commit | Kết quả | Quyết định |
|---|---|---|---|---|
| 1 | 2026-10-17 | b76d187, `python backtest.py` (log `run1.log`) | 311 lệnh (~1,5 lệnh/tháng/mã), win 35,7%, **E[R] gộp +0,064 (CI95 −0,15…+0,29), chi phí ×2 −0,050**; MUA −0,02 / BÁN +0,13; mã dương 4/5 (NZD −0,18); năm dương 3/7; max DD 24,5R. Lệnh SL trung bình −1,13R → chi phí ≈ 13% rủi ro (SL theo đỉnh vùng quét H1 khá hẹp). Leak test XAUUSD đạt (97 tín hiệu) | **KHÔNG ĐẠT** (tiêu chí 1, 2, 4, 5). Không tinh chỉnh trên dữ liệu này |
| 2 | 2026-10-17 | bb29202, `python backtest.py --tf H4-M5` (log `run2.log`) — **TRONG MẪU**, lần thử thứ 2 | 1674 lệnh (~6 lệnh/tháng/mã), win 25,5%, **E[R] gộp −0,261 (CI95 −0,37…−0,15), chi phí ×2 −0,325**; cả 5 mã âm (XAU −0,07, GBP −0,10, EUR −0,35, NZD −0,42, AUD −0,45); MUA −0,17 / BÁN −0,34; năm dương 1/8 (2022); max DD 461,6R. Khoảng SL trung vị chỉ 5–9 pip FX / $2,9 XAU → lệnh SL mất trung vị 1,17R (chi phí + trượt qua SL), 233 lệnh SL mất > 1,5R. EUR 2022–23 bị phóng đại bởi spread điền sẵn 50 point, nhưng AUD / NZD (spread thật) vẫn −0,4. Leak test XAUUSD đạt (mẫu 40 / 474) | **KHÔNG ĐẠT** cả 5 tiêu chí — âm có ý nghĩa thống kê. Không tinh chỉnh tiếp trên dữ liệu này |
