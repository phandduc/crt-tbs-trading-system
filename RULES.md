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
   Code: `crt_tbs.trading_day()`, `crt_tbs.daily()`.
2. **Nến CRT** = nến D c đã đóng, **dày**: |close − open| ≥ 50% × (high − low). CRTH = high, CRTL = low, 50% = giữa.
   Code: `crt_tbs.find_orders()` (biến `thick`).
3. **Key level (đỉnh cũ D):** đỉnh swing D (cao hơn hẳn 2 nến mỗi bên, đã xác nhận trước nến c) **chưa bị nến nào vượt**;
   nến CRT c có high ≥ đỉnh đó (chạm / quét đỉnh cũ). Không giới hạn độ xa, không dung sai.
   Code: `crt_tbs.key_highs()` (chiều MUA: gọi trên −low), gọi từ `crt_tbs.find_orders()`.
4. **Chỉ trong nến D kế tiếp (c + 1)**, trên H1:
   - **Quét:** nến H1 đầu tiên có high > CRTH.
   - **TBS:** nến H1 đầu tiên **đóng cửa > CRTH**. Chỉ râu vượt (TWS) không tính.
   - **Orderblock (Model #1):** nến H1 TĂNG (close > open) gần nhất, tính từ nến TBS trở đi.
   - **Xác nhận:** một nến H1 sau TBS **đóng cửa < giá mở của Orderblock** → tín hiệu lúc nến này đóng.
   - Nến c + 1 đóng mà chưa xác nhận → huỷ setup.
   Code: `crt_tbs.scan_candle2()` (quét, TBS — loại TWS vì chỉ xét giá đóng cửa —, Orderblock, xác nhận);
   `crt_tbs.find_orders()` giới hạn trong các nến H1 của nến c + 1.
5. **Vào lệnh thị trường** ngay khi nến xác nhận đóng (backtest: giá mở nến M1 đầu tiên từ lúc đó).
   Code: backtest `backtest.simulate()`; live `bot.handle()` → `bot.send_market()` (giá Bid / Ask lúc quét).
6. **SL** = high cao nhất từ nến quét tới nến xác nhận (đỉnh vùng quét). **TP1** = 50% nến CRT, **TP2** = CRTL.
   Code: đỉnh vùng quét trong `crt_tbs.scan_candle2()`; SL / TP1 / TP2 gán trong `crt_tbs.find_orders()`.
7. Bỏ lệnh nếu không có TP1 < giá vào < SL, hoặc khoảng SL ≤ chi phí (spread + 5 point).
   Code: backtest `backtest.simulate()` (trạng thái BO_GIA_VAO); live `bot.handle()`.
8. **Quản lý:** 50% khối lượng chốt ở TP1, 50% còn lại tới TP2; chạm TP1 → SL phần còn lại về giá khớp (từ nến M1 sau).
   Không giới hạn thời gian giữ lệnh.
   Code: backtest `backtest.simulate()` (trạng thái TP1_TP2 / TP1_BE / SL); live `bot.split_lots()` + `bot.handle()`
   (2 lệnh TP1 / TP2), `bot.manage()` + `bot._closed_at_tp()` (dời SL về giá vào).
9. Một nến CRT tối đa một lệnh (nếu cả hai chiều cùng có tín hiệu: lấy tín hiệu xác nhận trước; trùng giờ → bỏ).
   **Một lệnh mở mỗi mã** — tín hiệu đến khi mã đang có lệnh → bỏ.
   Code: một lệnh mỗi nến CRT trong `crt_tbs.find_orders()`; một lệnh mỗi mã: backtest `backtest.run_symbol()`
   (trạng thái BAN), live `bot.handle()`.

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

## 6. Lần chạy 3 — kiểm tra NGOÀI MẪU trên chỉ số Mỹ (US30, US100, US500) — ĐÃ XOÁ KHỎI CODE

> 2026-10-17, người dùng yêu cầu: xoá nhánh chỉ số (mã + quy tắc spread trong backtest, lựa chọn 6 của
> `run_backtest.bat`, `run3.log`). Mục này và dòng 3 của sổ chạy giữ làm lịch sử. Khôi phục code: commit c59e711.

Ghi 2026-10-17, TRƯỚC khi viết code và chạy. Người dùng yêu cầu.

- **Vì sao là ngoài mẫu:** dữ liệu 3 chỉ số chưa từng dùng cho CRT + TBS (lần chạy 1–2 chỉ dùng XAU + 4 FX). Quy tắc
  D → H1 giữ **nguyên như mục 2–3** (commit b76d187 + 7b2af94 / 1330ff7 chỉ thêm báo cáo), không chỉnh tham số nào.
  Lưu ý: tài liệu AR không nhắc tới chỉ số (chỉ ghi 6 cặp FX chính và "sub pairs" không định nghĩa) → đây là kiểm
  quy tắc trên thị trường khác, không phải kiểm đúng phạm vi tài liệu.
- Dữ liệu (BCR-MT5, mã sàn `#US30` / `#US100` / `#US500`, sha256 trong `<SYMBOL>_meta.json`): `data_2020`
  (2019-10 → 2021-12) + `data_2022` (2021-10 → 2025-10-16), nối như mục 3 (trùng giờ giữ bản `data_2020`); 30 ngày
  đầu khởi động. point 0,1 (như config repo cũ). Dữ liệu này đã dùng cho nghiên cứu S2-4 (MS-1, IDX-1) — không ảnh
  hưởng tính ngoài mẫu với CRT + TBS vì quy tắc không chọn dựa trên nó.
- **Spread (quy tắc của IDX-1, chốt trước):** với từng thư mục dữ liệu, trung vị spread M1 trong 06–16 UTC; nếu **= 0
  hoặc > 2 × spread tham chiếu** (US30 30, US100 18, US500 10 point) → thay cả cột spread của thư mục đó bằng tham chiếu.
  Biết trước: US100 / US500 trong `data_2020` có spread = 0 (sẽ bị thay).
- Chi phí, mô phỏng, quản lý lệnh, một lệnh mở mỗi mã: như mục 3.

**Tiêu chí đạt (phải đủ TẤT CẢ, cùng khuôn mục 4):**
1. E[R] gộp 3 chỉ số > 0 ở chi phí ×1 VÀ ×2.
2. CI95 bootstrap của E[R] gộp (×1) có cận dưới > 0.
3. E[R] > 0 trên CẢ 3 chỉ số (×1).
4. E[R] gộp > 0 ở cả lệnh MUA VÀ lệnh BÁN (×1).
5. E[R] gộp > 0 ở ≥ 2/3 số năm (theo năm khớp lệnh) có ≥ 20 lệnh (×1).

Ghi nhận trước: 3 chỉ số Mỹ đi rất sát nhau → lệnh trùng ngày, tương quan cao; CI95 bootstrap theo lệnh vì vậy hẹp hơn
thực tế (tiêu chí 2 dễ đạt hơn đáng có). Chạy đúng một lần. Không đạt → không tinh chỉnh trên dữ liệu này.
Đạt → vẫn chỉ là ứng viên trên chỉ số: cần Demo trước khi dùng tiền thật.

## 7. Lần chạy 4 — kiểm tra NGOÀI MẪU trên crypto (BTC, ETH) — ĐÃ XOÁ KHỎI CODE

> 2026-10-17, người dùng yêu cầu: xoá nhánh crypto (nến D UTC trong `crt_tbs.py`, BTCUSD / ETHUSD + điền spread trong
> backtest, test UTC, lựa chọn 6 của `run_backtest.bat`, `run4.log`, thư mục `data_crypto/`). Giữ `export_data.py`
> (công cụ xuất chung). Mục này và dòng 4 của sổ chạy giữ làm lịch sử. Khôi phục code: commit 56edbb6
> (dữ liệu: chạy lại `export_data.py`; sha256 cũ trong commit fc87396).

Ghi 2026-10-17, sau khi xuất và xem dữ liệu (spread, giờ giao dịch), TRƯỚC khi chạy chiến lược trên dữ liệu này.
Người dùng yêu cầu; người dùng chọn nến D crypto đóng **00:00 UTC** (chuẩn TradingView / sàn crypto).

- **Lưu ý thử nhiều thị trường:** đây là nhóm thị trường ngoài mẫu thứ 2 (sau chỉ số Mỹ — không đạt). Thử nhiều thị
  trường rồi chọn cái đạt cũng là "chọn theo may" → kể cả đạt cũng chỉ là ứng viên, phải qua Demo.
- **Dữ liệu** (`export_data.py`, BCR-MT5 Demo, mã sàn `Bitcoin.s` / `Ethereum.s`, sha256 trong
  `data_crypto/<NAME>_meta.json`, M1 gộp H1 khớp H1 của sàn 100%): BTCUSD 2024-05-13 → 2026-10-16 (sàn chỉ có từ
  đó); ETHUSD 2018-06-28 → 2026-10-16. 30 ngày đầu khởi động. point 0,01 cả hai.
- **Nến D 00:00 UTC; nến H1 từ 17:00 giờ New York ngày Chủ nhật trở đi tính vào nến thứ Hai.** Lý do: trên BCR crypto
  KHÔNG giao dịch cuối tuần (mở Chủ nhật 21–22 giờ UTC = 17:00 New York, đóng thứ Sáu 21 giờ UTC) → không gộp thì có
  nến D Chủ nhật chỉ 2–3 giờ. Riêng ETH 2021–2023 sàn mở cả cuối tuần (25% số nến) → các năm đó có nến Thứ Bảy /
  Chủ nhật đầy đủ, chỉ 2–3 giờ cuối Chủ nhật chuyển sang thứ Hai. Quy tắc chỉ dựa trên giờ của nến (không nhìn trước).
- **Spread:** BTC dùng nguyên. ETH: nến M1 có spread = 0 (điền sẵn, 2018 → 2023) được thay bằng
  trung vị (spread × point / giá) của các nến có spread > 0 × giá đóng nến đó / point (= 0,261% giá, áp cho 65,4% số
  nến M1 — chi phí thật của sàn này hiện nay, thận trọng cho các năm cũ).
- Mọi quy tắc khác giữ nguyên mục 2–3 (dày ≥ 50%, đỉnh / đáy D cũ, TBS, Model #1, SL đỉnh vùng quét, TP1 50%, TP2,
  50 / 50 + BE, một lệnh mỗi mã, chi phí spread + 5 point, ×2).

**Tiêu chí đạt (đủ TẤT CẢ, cùng khuôn mục 4):**
1. E[R] gộp 2 mã > 0 ở chi phí ×1 VÀ ×2.
2. CI95 bootstrap của E[R] gộp (×1) có cận dưới > 0.
3. E[R] > 0 trên CẢ 2 mã (×1).
4. E[R] gộp > 0 ở cả MUA VÀ BÁN (×1).
5. E[R] gộp > 0 ở ≥ 2/3 số năm (theo năm khớp lệnh) có ≥ 20 lệnh (×1).

Ghi nhận trước: BTC chỉ ~2,4 năm dữ liệu (ít lệnh); BTC và ETH tương quan cao (CI95 gộp hẹp hơn thực tế). Chạy đúng
một lần; không đạt → không tinh chỉnh trên dữ liệu này.

## 8. Sổ chạy

| # | Ngày | Commit | Kết quả | Quyết định |
|---|---|---|---|---|
| 1 | 2026-10-17 | b76d187, `python backtest.py` (log `run1.log`) | 311 lệnh (~1,5 lệnh/tháng/mã), win 35,7%, **E[R] gộp +0,064 (CI95 −0,15…+0,29), chi phí ×2 −0,050**; MUA −0,02 / BÁN +0,13; mã dương 4/5 (NZD −0,18); năm dương 3/7; max DD 24,5R. Lệnh SL trung bình −1,13R → chi phí ≈ 13% rủi ro (SL theo đỉnh vùng quét H1 khá hẹp). Leak test XAUUSD đạt (97 tín hiệu) | **KHÔNG ĐẠT** (tiêu chí 1, 2, 4, 5). Không tinh chỉnh trên dữ liệu này |
| 2 | 2026-10-17 | bb29202, `python backtest.py --tf H4-M5` (log `run2.log`) — **TRONG MẪU**, lần thử thứ 2 | 1674 lệnh (~6 lệnh/tháng/mã), win 25,5%, **E[R] gộp −0,261 (CI95 −0,37…−0,15), chi phí ×2 −0,325**; cả 5 mã âm (XAU −0,07, GBP −0,10, EUR −0,35, NZD −0,42, AUD −0,45); MUA −0,17 / BÁN −0,34; năm dương 1/8 (2022); max DD 461,6R. Khoảng SL trung vị chỉ 5–9 pip FX / $2,9 XAU → lệnh SL mất trung vị 1,17R (chi phí + trượt qua SL), 233 lệnh SL mất > 1,5R. EUR 2022–23 bị phóng đại bởi spread điền sẵn 50 point, nhưng AUD / NZD (spread thật) vẫn −0,4. Leak test XAUUSD đạt (mẫu 40 / 474) | **KHÔNG ĐẠT** cả 5 tiêu chí — âm có ý nghĩa thống kê. Không tinh chỉnh tiếp trên dữ liệu này |
| 3 | 2026-10-17 | 7cfe77d, `python backtest.py --symbols US30 US100 US500` (log `run3.log`) — **NGOÀI MẪU** (mục 6) | Spread: US100 / US500 `data_2020` = 0 → thay 18 / 10 (như ghi trước), còn lại giữ. 236 lệnh (~1,1 lệnh/tháng/mã), win 25,8%, **E[R] gộp −0,246 (CI95 −0,48…+0,02), chi phí ×2 −0,348**; cả 3 chỉ số âm (US30 −0,41, US100 −0,19, US500 −0,17); MUA −0,02 / **BÁN −0,39 (CI95 −0,71…−0,04)**; năm dương 1/6 (2021); max DD 81,6R; vốn 10 000 → 4 185 USD ở 1% / lệnh | **KHÔNG ĐẠT** cả 5 tiêu chí. Quy tắc D → H1 không có lợi thế trên chỉ số Mỹ; không tinh chỉnh trên dữ liệu này |
| 4 | 2026-10-17 | fc87396, `python backtest.py --symbols BTCUSD ETHUSD` (log `run4.log`) — **NGOÀI MẪU** (mục 7) | 171 lệnh, win 28,1%, **E[R] gộp −0,306 (CI95 −0,55…−0,05), chi phí ×2 −0,412**; BTC +0,464 (35 lệnh, CI95 −0,29…+1,28, ×2 +0,418) / **ETH −0,504 (136 lệnh, CI95 −0,72…−0,27)**; MUA −0,50 / BÁN −0,19; năm dương 2/4 (năm ≥ 20 lệnh); vốn 10 000 → 4 771 USD ở 1% (thấp nhất 3 211). ETH 2018–2022: 74 lệnh E[R] −0,89, win 15% — spread điền (0,26%) chỉ ≈ 12% rủi ro (SL trung vị 2,1% giá) → lỗ do chiến lược, không do chi phí; ETH 2023–2026: 62 lệnh −0,05. Leak test BTC 37 / ETH 142 đạt | **KHÔNG ĐẠT** cả 5 tiêu chí — gộp âm có ý nghĩa thống kê. BTC dương nhưng 1/2 mã, 35 lệnh, CI chứa 0 và là kết quả đẹp nhất sau 4 lần thử → KHÔNG được chọn riêng BTC. Không tinh chỉnh trên dữ liệu này |
