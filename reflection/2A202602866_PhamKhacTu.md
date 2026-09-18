# Reflection cá nhân — Phạm Khắc Tú

- **Mã học viên:** 2A202602866
- **Nhóm:** 4aesieunhan · Lớp 3B · Phòng E403
- **Dự án:** Trợ lý Discord — phát hiện câu hỏi và sự cố chưa được trả lời
- **Vai trò:** Đội trưởng · UI/Backend/Pipeline Engineer

---

## 1. Vai trò và phần việc tôi đảm nhiệm

Tôi chịu trách nhiệm điều phối tiến độ chung và triển khai luồng kỹ thuật end-to-end của prototype:

- Chia công việc theo bốn mảng: product/spec, data/evaluation, prompt/LLM và UI/backend/pipeline.
- Xây dựng pipeline đọc tin nhắn, chuẩn hóa thời gian, lọc bot/system message và đối chiếu `reply_to` với `msg_id` trước khi gọi mô hình.
- Tích hợp lời gọi LLM thật với JSON schema, kiểm tra output và chuyển input không chắc chắn sang `NEEDS_REVIEW`.
- Xây dựng API và giao diện hàng đợi nội bộ để TA xem `URGENT`, `NORMAL`, `NEEDS_REVIEW`, claim, snooze, dismiss và đánh dấu đã xử lý.
- Bổ sung final recheck và outbox để hạn chế gửi cảnh báo trùng hoặc gửi cảnh báo sau khi học viên đã được trả lời.
- Chuẩn bị dữ liệu demo tổng hợp, kịch bản quay video, health check và quy trình chạy prototype trên máy trình diễn.

## 2. Quyết định kỹ thuật quan trọng

Nhóm chọn kiến trúc batch định kỳ thay vì gọi model theo từng tin nhắn. Tầng rule-based xử lý các sự thật có thể xác định bằng code, sau đó chỉ chuyển ứng viên còn lại sang LLM.

Tôi đồng ý với quyết định này vì:

- Direct reply là nguồn sự thật rõ ràng, không cần LLM suy đoán.
- Batch giúp giảm số lần gọi API và tránh spam thông báo cho TA.
- Cost-of-error cao nhất là bỏ sót câu hỏi khẩn cấp, nên AI chỉ phân loại và ưu tiên; TA vẫn là người phản hồi học viên.

## 3. AI đã hỗ trợ tôi như thế nào

Tôi dùng AI như một công cụ hỗ trợ phát triển:

- Gợi ý cấu trúc module, schema API và các nhánh lỗi cần kiểm thử.
- Hỗ trợ viết bản nháp test, rà soát typing và phát hiện những trường hợp race condition hoặc retry dễ bị bỏ sót.
- Hỗ trợ soạn tài liệu triển khai, runbook và kịch bản demo.

Tôi vẫn chịu trách nhiệm kiểm tra đầu ra bằng code, test và log thực tế. Những đoạn AI sinh ra không được coi là đúng mặc định; tôi phải giải thích được state transition, idempotency key, final recheck và lý do từng safety boundary tồn tại.

## 4. Bài học từ failure của nhóm

Case `CP3-004` kỳ vọng `NEEDS_REVIEW` nhưng model trả `IGNORE` với confidence cao. Lỗi này cho thấy chỉ kiểm tra output có đúng JSON hay không là chưa đủ; output hợp lệ về cấu trúc vẫn có thể sai về quyết định.

Từ đó, tôi rút ra rằng safety phải được đặt ở nhiều tầng:

1. Rule-based xử lý các điều kiện chắc chắn như bot message và direct reply.
2. Schema validation chặn output sai cấu trúc.
3. Confidence và dấu hiệu thiếu ngữ cảnh đưa item sang human review.
4. Final recheck kiểm tra lại reply/edit/delete ngay trước khi gửi thông báo.
5. TA có quyền sửa, dismiss hoặc mở lại item; AI không tự trả lời học viên.

Bài học lớn nhất là một pipeline AI đáng tin cậy không chỉ nằm ở prompt tốt mà còn ở cách hệ thống bao quanh model bằng rule, trạng thái, audit log và cơ chế con người can thiệp.

## 5. Tự đánh giá cá nhân

| Tiêu chí | Bằng chứng | Tự đánh giá |
|---|---|---|
| Điều phối và hoàn thành lát cắt | Phân công bốn vai trò, theo dõi các phase và artifact checkpoint | Hoàn thành |
| Prototype end-to-end | Pipeline rule → LLM → queue → thao tác TA | Hoàn thành |
| Boundary và độ tin cậy | `NEEDS_REVIEW`, final recheck, outbox và audit action | Hoàn thành |
| Demo và vận hành | Seed demo, UI nội bộ, health page và runbook | Hoàn thành |
| Khả năng giải thích phần việc | Có thể trình bày luồng dữ liệu và các trạng thái từ message đến đóng item | Sẵn sàng trả lời CP6 |

## 6. Nếu có thêm một tuần

Tôi sẽ ưu tiên:

1. Kết nối Discord sandbox thật với quyền tối thiểu và kiểm thử permission loss/rate limit trong môi trường staging.
2. Chạy validation với TA/lab coach thật để điều chỉnh copy và thứ tự thao tác trong hàng đợi.
3. Thêm dashboard theo dõi SLA, false-positive rate và thời gian từ lúc cảnh báo đến khi TA phản hồi.

