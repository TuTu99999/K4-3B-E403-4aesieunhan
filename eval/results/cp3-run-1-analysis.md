# CP3 — Phân tích lượt chạy đầu

- Tổng số case: **22**
- Đạt: **21**
- Không đạt: **1**
- Tỷ lệ đạt: **95.5%**
- URGENT recall: **5/5**
- Provider/schema error: **0**
- Chế độ chạy: **AI thật, không cache**

## Các trường hợp sai lệch

- `CP3-004`: kỳ vọng `NEEDS_REVIEW`, nhận `IGNORE` — `overconfident_on_missing_context`.
  Model kết luận với confidence 0,96 khi câu hỏi thiếu đối tượng/ngữ cảnh thay vì chuyển người
  review. Nguy cơ là bỏ qua một yêu cầu thật. Hướng sửa sau run 1 là bổ sung context hoặc rule nhận
  diện câu tham chiếu mơ hồ; không sửa nhãn hay chạy lại để thay thế số lượt đầu.

## Giới hạn diễn giải

Đây là lượt đo trên golden set do nhóm tự xây và review, không phải blind benchmark. Case phát triển từ chatlog đã được diễn đạt lại để không công khai nội dung Discord gốc.
