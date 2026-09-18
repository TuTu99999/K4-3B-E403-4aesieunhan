# Reflection cá nhân — Đồng Mạnh Hùng

- **Mã học viên:** 2A202602412
- **Nhóm:** 4aesieunhan · Lớp 3B · Phòng E403
- **Dự án:** Trợ lý Discord — phát hiện câu hỏi và sự cố chưa được trả lời
- **Vai trò:** Data Lead — Evidence & Evaluation

---

## 1. Vai trò và phần việc tôi đảm nhiệm

Tôi phụ trách dữ liệu và đánh giá thực nghiệm cho hệ thống. Các đầu việc chính gồm:

- Khai thác `k4_messages.csv` để xác định những tin nhắn không có direct reply và các trường hợp câu hỏi có nguy cơ bị trôi.
- Rà soát dữ liệu theo ba nhãn `IGNORE`, `NORMAL`, `URGENT`, đồng thời kiểm tra những trường hợp dễ gán sai như câu trần thuật, lời cảm ơn có kèm câu hỏi và sự cố kỹ thuật không có dấu hỏi.
- Phân tích phân bố dữ liệu: trong 311 tin nhắn ứng viên có 273 tin `IGNORE`, 30 tin `NORMAL` và 8 tin `URGENT`. Kết quả này cho thấy dữ liệu mất cân bằng mạnh và không thể đánh giá mô hình chỉ bằng accuracy tổng thể.
- Tham gia xây dựng golden set, User Input Grid và các nhóm case khó để kiểm tra riêng khả năng bắt câu hỏi actionable và sự cố khẩn cấp.
- Tổng hợp kết quả đánh giá bằng các chỉ số như decision correctness, actionable recall, notification precision và URGENT recall.

## 2. Kết quả và bằng chứng công việc

- Bộ CP3 public golden set có 22 case, trong đó 16 case được phát triển từ chatlog thật và phủ đủ bốn lớp chỗ khó.
- Lượt chạy CP3 đầu tiên đạt **21/22 case (95,5%)**, actionable recall **14/14** và URGENT recall **5/5**.
- Tôi không chỉ nhìn vào accuracy. Với lớp `IGNORE` chiếm 87,8% dữ liệu, một hệ thống luôn dự đoán `IGNORE` vẫn có thể tạo ra con số bề ngoài cao nhưng bỏ sót toàn bộ câu hỏi thật.
- Tôi hỗ trợ giữ tập đánh giá tách biệt với dữ liệu dùng để phát triển prompt nhằm hạn chế data leakage và giúp kết quả có thể đối chiếu lại.

## 3. AI đã hỗ trợ tôi như thế nào

AI hỗ trợ tôi ở các công việc có tính lặp lại và cần rà soát nhanh:

- Gợi ý taxonomy ban đầu cho các nhóm lỗi và cách tổ chức User Input Grid.
- Hỗ trợ kiểm tra cấu trúc CSV/JSON, phát hiện trường thiếu và sinh báo cáo metric từ kết quả chạy.
- Gợi ý các case biên cần kiểm tra thêm, chẳng hạn câu trần thuật báo lỗi, câu hỏi thiếu chủ thể và nội dung có prompt injection.

Tôi không dùng AI làm nguồn sự thật cho nhãn dữ liệu. Các đề xuất của AI vẫn được đối chiếu với định nghĩa nhãn, nội dung chat gốc đã ẩn danh và quyết định của nhóm. Khi AI không đủ căn cứ, case phải được đưa về `NEEDS_REVIEW` thay vì tự động coi là `IGNORE`.

## 4. Bài học từ failure của nhóm

Failure đáng nhớ nhất là case `CP3-004`: câu *“Cái này em cần hỏi ai vậy ạ?”* thiếu đối tượng và ngữ cảnh. Kỳ vọng của nhóm là `NEEDS_REVIEW`, nhưng mô hình trả `IGNORE` với confidence cao. Đây là lỗi `overconfident_on_missing_context`.

Từ case này, tôi rút ra ba bài học:

1. Confidence do mô hình trả về không đồng nghĩa với xác suất mô hình đúng.
2. Accuracy tổng thể không đủ để đánh giá một hệ thống có dữ liệu mất cân bằng; phải theo dõi recall của từng nhóm rủi ro.
3. Với input thiếu ngữ cảnh, hệ thống cần chuyển cho con người kiểm tra thay vì âm thầm bỏ qua.

Failure này giúp nhóm bổ sung trạng thái `NEEDS_REVIEW`, kiểm tra JSON schema và báo cáo riêng các lỗi mơ hồ thay vì che chúng trong một con số accuracy đẹp.

## 5. Tự đánh giá cá nhân

| Tiêu chí | Bằng chứng | Tự đánh giá |
|---|---|---|
| Hiểu dữ liệu và bài toán | Phân tích 311 ứng viên và phân bố 273/30/8 | Hoàn thành |
| Xây dựng bộ đánh giá | Tham gia golden set, User Input Grid và taxonomy lỗi | Hoàn thành |
| Đo đúng rủi ro sản phẩm | Theo dõi actionable recall và URGENT recall, không chỉ accuracy | Hoàn thành |
| Hiểu failure của nhóm | Phân tích `CP3-004` và đề xuất `NEEDS_REVIEW` | Hoàn thành |
| Khả năng giải thích phần việc | Có thể trình bày cách gán nhãn, chia tập và tính các metric | Sẵn sàng trả lời CP6 |

## 6. Nếu có thêm một tuần

Tôi sẽ ưu tiên:

1. Mở rộng tập test mơ hồ và tiến hành double-label để đo mức đồng thuận giữa hai người chấm.
2. Theo dõi data drift theo tuần học, đặc biệt với từ viết tắt và loại sự cố mới.
3. Bổ sung error analysis theo từng channel và từng nhóm intent để biết lỗi tập trung ở đâu thay vì chỉ nhìn một chỉ số chung.

