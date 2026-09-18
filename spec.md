# Template AI Spec *(spec.md — commit trước hạn chốt spec: 21:00 18/9, tại CP4 · quality bar chốt từ thời điểm nộp)*

> Cấu trúc phủ đúng "SPEC 8 phần" của chương trình: Bằng chứng (§1-§2) · Lát cắt (§4) · Canvas (đính kèm CP1) · Augment/Automate (§4) · 4 đường đi của trải nghiệm (§6) · Kiểu lỗi (§5) · Kiểm thử (§7) · Phân công (§8). Hướng dẫn viết từng mục: `02-guide.md`.

```markdown
# AI SPEC — Unanswered Question & Blocker Tracker trên Discord · Nhóm 4aesieunhan · Zone C1
Hướng: [x] B — Trợ lý Học viên / Vận hành  [ ] A — VLearn  [ ] C — Làn mở
Loại: [x] Tính năng mới  [ ] Tối ưu tính năng có sẵn

---

## §1. User & Job
- **Job executor + workflow:** 
  - *User:* Teaching Assistant (TA / Lab Coach) trực ca và Điều phối viên học tập.
  - *Workflow hiện tại:* TA mở Discord rồi lướt thủ công qua hàng chục tin nhắn ở các channel thảo luận, từ đó dò xem ai hỏi gì chưa được giải đáp. Điều này dễ bỏ sót các câu hỏi bị trôi hoặc nhầm rằng câu hỏi đó đã có người trả lời.
- **Core JTBD:** Giúp đội ngũ trợ giảng phát hiện và xử lý kịp thời tất cả các câu hỏi, sự cố kỹ thuật của học viên bị bỏ quên mà không phải lướt đọc thủ công toàn bộ đoạn hội thoại hàng ngày.
- **Problem statement:** Trong các kênh Discord đông học viên, tin nhắn hỏi bài và báo lỗi thường xuyên bị trôi nhanh do học viên chat chèn hoặc cảm ơn; TA mất nhiều thời gian rà soát thủ công nhưng vẫn bỏ sót câu hỏi khẩn cấp, dẫn đến việc học viên bị gián đoạn học tập hoặc trễ hạn nộp bài.
- **Evidence:**
  - *Số liệu mining từ log thực tế `k4_messages.csv`:*
    - Tổng cộng 311 tin nhắn không có nút reply kỹ thuật (`reply_to == NaN`).
    - Dữ liệu bị mất cân bằng trầm trọng (Class Imbalance): ~87.8% (273 tin) là tin chào hỏi, cảm ơn, thông báo hoặc đã được giải đáp ngầm; ~9.6% (30 tin) là câu hỏi thông thường; chỉ ~2.6% (8 tin) là sự cố khẩn cấp/blocker.
    - Nếu không có bộ lọc thông minh, TA sẽ đối mặt với tỷ lệ báo động giả (False Alarm) lên tới gần 90%.
  - *≥5 quote nguyên văn từ chatlog thật:*
    1. `M44084`: *"Workshop bắt đầu chưa ạ, em vẫn chưa được duyệt"* (Kẹt cửa phòng học trực tuyến).
    2. `M88027`: *"cho em hỏi Lab2 có được extend thời gian submit thêm không v ạ? Em lỡ nộp muộn 1 phút không submit bài được ạ"* (Quá hạn nộp bài, cần cứu trợ khẩn cấp).
    3. `M33885`: *"vào mà cứ bị out ra thì phải làm sao ạ :v"* (Lỗi kỹ thuật nghiêm trọng nhưng ngụy trang bằng icon cợt nhả).
    4. `M01360`: *"Cho em hỏi ạ: Cửa sổ lập đội đã đóng thì btc có thể hỗ trợ gia hạn thời gian đến hết ngày hôm nay được không ạ"* (Hết hạn lập nhóm, nguy cơ bị loại).
    5. `M80884`: *"[@D9617] rep tin nhắn e với ạ"* (Ping đích danh giục phản hồi do bị tắc nghẽn giao tiếp).
    6. `M87936`: *"mình quét QR điền form như mn ạ, nhưng mà nay mình lên app check thử xem log điểm danh như nào thì thấy không có dữ liệu, cho mình hỏi nếu không phải check điểm danh trên app my vinuni thì check ở đâu ạ? cảm ơn bạn"* (Bẫy cảm ơn lịch sự che khuất câu hỏi thật).

---

## §2. Impact & quyết định chọn
- **Bảng impact ≥3 ứng viên:**

| Ứng viên giải pháp | Đối tượng & Quy mô | Tần suất | Tốn kém/Tổn thất mỗi lần gặp | Tính khả thi kỹ thuật |
| :--- | :--- | :--- | :--- | :--- |
| **1. Unanswered Question Tracker theo lô (Batch)** | Toàn bộ TA & học viên (~300-500 người/cohort) | 15–30 phút/lần | Bỏ sót sự cố phòng học, trễ hạn nộp bài; TA tốn 1–2h/ngày lướt chat | **Rất cao** (Rule-based + Batch LLM Prompting, chi phí API cực rẻ) |
| **2. Realtime Auto-Responder (Bot tự trả lời ngay)** | Toàn bộ học viên | Tức thì theo từng tin | Trả lời sai kiến thức (ảo giác), chi phí API cao do gọi per-message, dễ spam kênh | **Trung bình** (Dễ gây phiền hà và rủi ro factuality cao) |
| **3. Summarizer tóm tắt toàn bộ kênh chat ngày** | Học viên & TA | 1 lần/cuối ngày | Không giải quyết được sự cố khẩn cấp theo thời gian thực; học viên vẫn bị kẹt | **Cao** nhưng không giải quyết được tính cấp bách |

- **Ứng viên ĐÃ LOẠI + vì sao:** 
  - *Loại Ứng viên 2 (Auto-Responder):* Chi phí token gọi lẻ per-message quá tốn kém, rủi ro sinh ảo giác khi giải đáp bài tập kỹ thuật sâu.
  - *Loại Ứng viên 3 (Daily Summarizer):* Độ trễ quá lớn (24h), không đạt SLA cứu trợ học viên (15–60 phút).
- **Ứng viên CHỌN + vì sao (bằng số):**
  - Chọn **Ứng viên 1 (Unanswered Question & Blocker Tracker)**:
  - Giảm **100% công sức lướt tay** đọc ~300 tin rác mỗi ngày của TA.
  - Đảm bảo **100% Recall đối với sự cố khẩn cấp (Nhãn 2)** trong vòng 15–20 phút.
  - Tiết kiệm hơn **90% chi phí API** nhờ kiến trúc 3 tầng: Lọc cứng mã nguồn $\rightarrow$ Gom 5-10 câu tồn đọng vào 1 prompt duy nhất gọi LLM.

---

## §3. Giải pháp tương tự đã nghiên cứu
- **Discord Forum Threads & Support Bot có sẵn (Ticket Tool):**
  - *Flow:* Bắt học viên chủ động gõ lệnh `/ticket create` để tạo phòng riêng hỏi đáp.
  - *Đáng học:* Dễ quản lý trạng thái Đã xong / Chưa xong.
  - *Đáng né:* Rào cản hành vi lớn; học viên có xu hướng chat tự do ở kênh text chung chứ lười gõ lệnh tạo ticket.
  - *Mình khác gì:* Hệ thống tự động lắng nghe kênh chat chung tự nhiên, chủ động truy vết và gom câu hỏi bị bỏ rơi cho TA mà không ép học viên thay đổi thói quen.
- **Slack Catch Up / Recap AI:**
  - *Flow:* Tóm tắt tất cả các tin nhắn chưa đọc thành đoạn văn ngắn.
  - *Đáng học:* Trích xuất ý chính nhanh.
  - *Đáng né:* Trộn lẫn câu hỏi đã giải quyết và chưa giải quyết, không phân loại được độ ưu tiên cấp bách (SLA).
  - *Mình khác gì:* Phân loại cứng cáp 3 mức độ: `0: IGNORE`, `1: NORMAL`, `2: URGENT`, chỉ đưa ra hành động cần làm ngay.

---

## §4. Thiết kế
- **Lát cắt MỘT CÂU:** 
  > Hệ thống hỗ trợ **Teaching Assistant** tự động quét các tin nhắn tồn đọng trên Discord theo chu kỳ 15 phút, dùng **bộ lọc quy tắc kết hợp LLM** để phân loại ý định và độ cấp bách, trả về **danh sách câu hỏi chưa được giải đáp kèm đường dẫn trực tiếp** để TA can thiệp ngay.

- **Non-goals (Những thứ KHÔNG build):**
  1. *Không tự động sinh câu trả lời thay TA (No Auto-reply):* Hệ thống chỉ làm nhiệm vụ cảnh báo và gửi lại cho TA, quyền trả lời thuộc về con người.
  2. *Không xây dựng luồng xử lý real-time tốn kém per-message:* Không gọi API LLM cho từng tin nhắn đơn lẻ; chỉ dùng kiến trúc gom lô (Batch Cron-job).
  3. *Không can thiệp vào các tin nhắn riêng tư (DM):* Chỉ quét trên các kênh thảo luận chung được cấp quyền.

- **Mức prototype nhắm tới:** `[x] Working`
  - *Phần thật:* Pipeline nạp dữ liệu Discord, Tầng 1 lọc Rule-based bằng code Python, Tầng 2 phân loại bằng LLM API (Gemini/GPT), Tầng 3 logic đo thời gian/độ trôi và xuất cảnh báo ra Markdown/Discord Webhook.
  - *Phần mock:* Giả lập luồng cron định kỳ chạy qua các khoảng thời gian bằng script kiểm thử trên tập dữ liệu lịch sử.

- **Automation:** `[x] Conditional`
  - *Lý do:* Chi phí sai sót (Cost-of-error) đối với tin khẩn cấp là rất đắt (học viên lỡ buổi học hoặc deadline). Hệ thống hoạt động theo mô hình *Human-in-the-loop*: AI lọc và cảnh báo, con người (TA) bấm vào link xác nhận và trực tiếp trả lời.

- **§4b. Nguyên tắc đã áp dụng (HAX / PAIR):**

| Nguyên tắc | Áp cụ thể vào đâu trong prototype |
| :--- | :--- |
| **HAX G1: Make clear what the system can do** | Bản tin cảnh báo gửi TA nêu rõ lý do phân loại (`URGENT` do kẹt phòng học / nộp muộn, `NORMAL` do hỏi thủ tục) kèm đoạn trích dẫn. |
| **HAX G2: Make clear how well the system can do what it does** | Cung cấp link gốc kèm nhãn độ tin cậy để TA nhanh chóng click kiểm tra lại ngữ cảnh nếu nghi ngờ. |
| **HAX G9: Support efficient correction** | Nếu bot cảnh báo nhầm câu đùa giỡn, TA có nút bấm/reaction đánh dấu "Đã giải quyết" hoặc "Bỏ qua" để bot cập nhật bộ nhớ tạm, không ping lại. |
| **HAX G10: Scope services when in doubt** | Khi không chắc chắn giữa nhãn 1 và nhãn 2, hệ thống tự động chọn phương án an toàn hơn là nâng lên mức ưu tiên cao hơn để tránh bỏ sót. |
| **PAIR: Contextual Resolution** | Tích hợp cơ chế kiểm tra đối soát ngữ cảnh (quét tin nhắn liền kề của Coach hoặc tag tên) trước khi quyết định ping cảnh báo. |

---

## §5. Kiểu lỗi — Bốn lớp chỗ khó + Kịch bản rủi ro (≥8 kịch bản)

### 5.1. Tự cụ thể hoá 4 lớp chỗ khó cho lát cắt sản phẩm (PAIR §6.2)

* **① Nguồn sự thật (Dự đoán sai trạng thái / Bịa đặt trạng thái giải quyết):**
  * *Chỗ nào AI dễ "bịa" nhất?* AI tự suy diễn rằng câu hỏi đã được giải quyết hoặc tự bịa ra lý do không hợp lý để gạt tin nhắn vào nhóm bỏ qua (`0: IGNORE`). Nguy hiểm nhất là khi TA gõ một câu chat ngắn hoặc tin nhắn không liên quan ngay bên dưới, AI vội vã kết luận "đã được giải đáp" dù học viên vẫn đang bị kẹt.
  * *Không có căn cứ thì làm gì?* Nguyên tắc an toàn: Khi không tìm thấy bằng chứng xác thực (tin nhắn giải quyết cụ thể hoặc nút Reply trực tiếp), hệ thống **mặc định coi là CHƯA GIẢI QUYẾT** để đưa ra hàng đợi kiểm tra.

* **② Mơ hồ / Thiếu thông tin (Input cộc lốc, bẫy cảm xúc hoặc câu trần thuật):**
  * *Input không đủ chắc:* Học viên nhắn cộc lốc ("Hạn nộp Lab02"), dùng icon cợt nhả giấu lỗi ("vào mà cứ bị out :v"), hoặc nói câu trần thuật không dấu hỏi ("Workshop bắt đầu chưa ạ, em vẫn chưa được duyệt").
  * *Hành vi xử lý:* **Đoán có báo (Scope when in doubt).** Hệ thống không tự ý từ chối hay nuốt mất câu hỏi; thay vào đó, nó tự động nâng mức cảnh báo lên ngưỡng an toàn cao hơn (`1` lên `2`), hiển thị rõ nhãn cảnh báo kèm trích dẫn nguyên văn để TA tự phán đoán nhanh trong 3 giây.

* **③ Ngoài phạm vi / Vượt thẩm quyền (Kỳ vọng AI tự trả lời hoặc can thiệp DM riêng tư):**
  * *User đòi hỏi gì vượt thẩm quyền?* Học viên nhắn tin riêng (DM) đòi bot giải bài tập, hoặc TA kỳ vọng bot tự động thay mặt mình trả lời chuyên môn trên kênh Discord.
  * *Giới hạn ranh giới:* Hệ thống kiên quyết giữ đúng vai trò **Tracker & Triaging (Truy vết & Định tuyến cảnh báo)**. Tuyệt đối không can thiệp sinh nội dung kiến thức thay con người (No Auto-Responder) và từ chối xử lý tin nhắn riêng tư nằm ngoài phạm vi kênh chung.

* **④ Đặc thù domain học tập Cohort (SLA cháy giờ, Blocker cửa phòng & Deadline):**
  * *Sai cái gì thì học viên mất điểm / mất niềm tin ngay?* Bỏ sót tin nhắn kẹt duyệt phòng học Workshop khi buổi học đang diễn ra, hoặc bỏ lọt sự cố học viên không submit được bài Lab lúc 23h59. Một tin nhắn khẩn cấp bị phân loại nhầm thành rác (`0`) sẽ khiến học viên lỡ buổi học hoặc nhận điểm 0 oan uổng.

---

### 5.2. Bảng ma trận ≥8 kịch bản rủi ro (HAX Playbook & PAIR Guidelines)

> **Kịch bản làm nhóm sợ nhất khi demo (Worst Nightmare):** **Kịch bản KB-01 & KB-03.** Học viên thông báo bằng câu trần thuật không có dấu hỏi *"Em vào 15p rồi nhưng chưa được duyệt ạ"*, hoặc *"Em lỡ nộp muộn 1p ko submit được"* nhưng mô hình thấy không có dấu `?` và không có từ "lỗi" nên tự động gán nhãn `0` (Bỏ qua) -> Câu hỏi chìm lún vĩnh viễn, học viên đứng ngoài cửa phòng học hoặc trượt bài Lab.

| Mã KB | Tình huống cụ thể (Input thực tế từ log `k4`) | Lớp khó | Hành vi mong muốn của hệ thống (Hiển thị / Xử lý / Cho user làm gì tiếp) | Nguyên tắc áp dụng | Mã case Golden Set |
| :---: | :--- | :---: | :--- | :---: | :---: |
| **KB-01** | **Trần thuật kẹt ngoài workshop:** Học viên nhắn trần thuật không có dấu `?`: *"Em vào dc 15p rồi nhưng chưa được duyệt ạ"* | **④** Domain | Nhận diện đây là Blocker phòng học khẩn cấp. Bắn ngay ping đỏ nhãn `2: URGENT` lên kênh điều phối TA kèm link nhảy thẳng tới tin nhắn. | **HAX G1** (Rõ năng lực)<br>**PAIR Sensitivity** | `M44084`<br>`M60776`<br>`M06758` |
| **KB-02** | **Icon cợt nhả giấu lỗi nghiêm trọng:** Học viên nhắn: *"vào mà cứ bị out ra thì phải làm sao ạ :v"* | **②** Mơ hồ | Bóc tách hành vi kỹ thuật ("bị out ra") thay vì bị đánh lừa bởi cảm xúc icon `:v`. Gán chuẩn nhãn `2: URGENT`, không hạ cấp xuống chat phiếm. | **HAX G10** (Thận trọng khi mơ hồ) | `M33885` |
| **KB-03** | **Kẹt nộp bài sát nút:** *"Lab2 extend được ko, em lỡ nộp muộn 1 phút không submit bài được ạ"* | **④** Domain | Phát hiện từ khóa xung yếu ("không submit được", "muộn"). Định tuyến ngay vào nhóm `2: URGENT`, hiển thị nút bấm để TA xác nhận gia hạn. | **HAX G2** (Minh bạch độ chắc chắn) | `M88027`<br>`M72484` |
| **KB-04** | **Ping đích danh giục hỗ trợ:** *"[@D9617] rep tin nhắn e với ạ"* | **①** Truth | Nhận diện học viên đang bị bế tắc giao tiếp (communication bottleneck). Gán nhãn `2: URGENT` và thông báo cho người trực ca hiện tại thay vì bỏ qua do câu quá ngắn. | **HAX G9** (Hỗ trợ sửa lỗi kịp thời) | `M80884`<br>`M01360` |
| **KB-05** | **Bẫy cảm ơn che khuất thắc mắc:** *"mình quét QR rồi... nhưng app ko có log điểm danh thì check ở đâu? cảm ơn bạn"* | **②** Mơ hồ | Bộ lọc Tầng 1 không được nuốt chửng tin nhắn vì có từ "cảm ơn". Gán đúng nhãn `1: NORMAL` và trích xuất câu hỏi trọng tâm cho TA. | **HAX G10** (Không phán đoán vội vã) | `M87936`<br>`P_SYNTH_01` |
| **KB-06** | **Đùa giỡn đội lốt câu hỏi:** Học viên hỏi trêu: *"Kiểu em ko có câu hỏi nào hỏi , có ổn ko ạ :))"* | **②** Mơ hồ | Phân loại chính xác vào nhãn `0: IGNORE` (Không cảnh báo). Tuyệt đối không ping làm phiền TA chỉ vì tin nhắn kết thúc bằng dấu `?`. | **PAIR Relevance** (Chống báo động giả) | `M49586`<br>`M67785`<br>`M56285` |
| **KB-07** | **Giải đáp ngầm không bấm Reply:** Học viên hỏi ghép đội, Coach gõ lời giải đáp ngay bên dưới nhưng không ấn nút Reply. | **①** Truth | Quét cửa sổ ngữ cảnh 5 tin kế tiếp. Nhận diện tin nhắn kế tiếp đến từ vai trò Hỗ trợ/Admin $\rightarrow$ Gán nhãn `0: IGNORE`, tự động giải phóng hàng đợi tồn đọng. | **HAX G11** (Học hỏi từ ngữ cảnh) | `M54235`<br>`M81676` |
| **KB-08** | **Học viên tự khắc phục sự cố:** *"[@D9617] à được rồi anh ạ discord em chặn lệnh... em vừa enable lại rồi"* | **①** Truth | Nhận diện mẫu câu đóng sự cố ("được rồi", "enable lại rồi"). Tự động chuyển nhãn `0: IGNORE`, đánh dấu resolved mà không làm phiền TA. | **HAX G8** (Tôn trọng thói quen người dùng) | `M83821` |
| **KB-09** | **Đòi hỏi ngoài thẩm quyền (Scope Creep):** Học viên gửi tin nhắn DM cho Bot yêu cầu sửa bài tập Python/SQL. | **③** Ngoài quyền | Bot không tự bịa giải pháp. Phản hồi template lịch sự: *"Hệ thống chỉ hỗ trợ ghi nhận thắc mắc tồn đọng tại kênh chung. Vui lòng đặt câu hỏi tại #channel_lab để TA hỗ trợ."* | **HAX G1** (Nêu rõ phạm vi)<br>**HAX G10** | `M27566` (Ủy quyền) |

---

### 5.3. Đối soát độ phủ của Bốn lớp chỗ khó trong Golden Set (§2.6)

Để đảm bảo không có lỗ hổng kiểm thử (zero coverage gap), toàn bộ 4 lớp chỗ khó đều được phân bổ tối thiểu $\ge 2$ case thực tế trong bộ `golden_test_30.csv`:

* **Lớp ① (Nguồn sự thật / Ngữ cảnh ẩn):** 6 case (`M80884`, `M01360`, `M54235`, `M81676`, `M83821`, `M97172`) $\rightarrow$ *Đo khả năng phát hiện tin đã xử lý ngầm và tin tag đích danh.*
* **Lớp ② (Mơ hồ / Ngôn từ gián tiếp):** 6 case (`M33885`, `M87936`, `P_SYNTH_01`, `M49586`, `M67785`, `M56285`) $\rightarrow$ *Đo khả năng xuyên qua icon `:v`, câu đùa giỡn, và bẫy cảm ơn.*
* **Lớp ③ (Ngoài phạm vi / Giới hạn vai trò):** 2 case (`M27566` xin miễn NVQS, `M04392` hỏi áo/thẻ) $\rightarrow$ *Đo tính chuẩn mực định tuyến hành chính.*
* **Lớp ④ (Đặc thù domain học tập Cohort):** 6 case (`M44084`, `M60776`, `M06758`, `M88027`, `M53281`, `M12158`) $\rightarrow$ *Đo độ nhạy 100% với các blocker khóa nhóm, kẹt phòng Zoom và nộp muộn.*

## §6. Bốn đường đi của trải nghiệm
- **1. Happy path:** 
  - Học viên gửi câu hỏi thắc mắc hoặc báo lỗi phòng học. Sau 15 phút không ai bấm reply và không có tin nhắn giải đáp liền kề, hệ thống quét trúng, từ đó LLM gán nhãn chính xác (`1: NORMAL` hoặc `2: URGENT`). Bot gửi thông báo lên kênh điều phối của TA kèm trích dẫn và link dẫn thẳng tới tin nhắn.
- **2. Low-confidence:** 
  - Tin nhắn viết tắt nhiều hoặc quá ngắn (ví dụ: *"Hạn nộp Lab02"* - `M72484`). AI phân vân giữa `1` và `2`. Cơ chế an toàn tự động nâng lên mức ưu tiên cao hơn (`URGENT`) để TA chủ động kiểm tra, kèm ghi chú: *"[Cần xác thực ngữ cảnh]"*.
- **3. Failure / Không căn cứ (Báo động nhầm câu đùa):** 
  - Học viên chat đùa giỡn kèm câu hỏi tu từ -> AI phân loại nhầm thành câu hỏi -> TA nhận cảnh báo nhưng nhận ra là tin đùa -> TA thả reaction biểu tượng ❌ -> Bot tự xóa thông báo và ghi nhận log để tinh chỉnh prompt.
- **4. Correction (User sửa):** 
  - Nếu học viên tự sửa được lỗi và nhắn *"em làm được rồi ạ"*, hoặc Coach gõ câu trả lời trễ hơn -> Ở chu kỳ quét 15 phút tiếp theo, hệ thống tự động gạch bỏ `msg_id` đó khỏi hàng đợi cần xử lý.
- **Khi bị đòi ngoài phạm vi:** 
  - Học viên gửi tin nhắn trực tiếp (DM) cho bot yêu cầu giải bài -> Bot từ chối và phản hồi: *"Hệ thống chỉ hỗ trợ ghi nhận câu hỏi tồn đọng tại các kênh thảo luận chung của khóa học"*.
- **Case đặc thù domain:** 
  - Vào khoảng thời gian đầu của khóa học, số lượng hỏi đáp tăng cao, chu kì quét có thể giảm xuống để phù hợp.

---

## §7. Kiểm thử
- **Chiều chất lượng & Định nghĩa kiểm chứng:**
  - *Sensitivity (Độ nhạy phân cấp SLA - Nhãn 2):* Phát hiện chính xác 100% các tin blocker và deadline sát nút. Fail nếu gán nhãn `0` hoặc `1`.
  - *Relevance / Noise Filtering (Độ sạch - Nhãn 0):* Lọc sạch toàn bộ cảm ơn ngắn, thông báo và chat phiếm. Fail nếu gán nhãn `1` hoặc `2` (báo động giả).
  - *Coverage / Question Detection (Bảo toàn câu hỏi thật):* Đảm bảo mọi thắc mắc học tập chưa được giải quyết phải được giữ lại (`1` hoặc `2`). Fail nếu gán nhãn `0` (nuốt mất câu hỏi).
- **Golden set (30 case phủ kín User Input Grid, lưu tại `eval/golden_test_30.csv`):**
  - *Nhãn 2 (URGENT - 8 case):* `M44084`, `M60776`, `M06758`, `M33885`, `M88027`, `M53281`, `M12158`, `M80884`.
  - *Nhãn 1 (NORMAL - 12 case):* `M87936`, `P_SYNTH_01` (Bẫy cảm ơn có chuyển ý); `M84888`, `M69081`, `M99769`, `M10991`, `M60122`, `M27566`, `M40040`, `M03948`, `M21623`, `M21374` (Hỏi thủ tục, slide, điểm danh, kỹ thuật Git).
  - *Nhãn 0 (IGNORE - 10 case):* `M49586`, `M67785`, `M56285` (Đùa giỡn); `M54235`, `M81676`, `M01360` (Coach đã trả lời ngầm không bấm reply); `M47011`, `M12505`, `M11917`, `M00318`, `M83821` (Thông báo, cảm ơn, tự fix).
- **Quality bar (Chốt cứng tại mốc spec CP4):**
  > **"Đạt chuẩn SHIP khi: Urgent Recall = 100% (8/8 case Nhãn 2 được phát hiện, không có ca khẩn cấp nào bị gán nhãn 0), Overall Accuracy >= 83,3 % (>= 25/30 case đoán đúng), và Noise Precision >= 85%."**
- **Kết quả các lượt chạy thực nghiệm (Báo cáo CP3):**

| Lượt chạy | Tổng case | Số case đúng | Accuracy | Urgent Recall (Nhãn 2) | Nhận xét & Hành động |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **Run 01 (Prompt thô)** | 30 | 21/30 | 70.0% | 62.5% (5/8) | Bị sót 3 ca kẹt phòng học do không có dấu `?` (`Declarative Blocker`). Trạng thái: **HOLD**. |
| **Run 02 (Thêm Few-shot)** | 30 | 25/30 | 83.3% | 87.5% (7/8) | Nhận diện tốt trần thuật nhưng bị lọt ca icon `:v` (`M33885`). Trạng thái: **LIMITED**. |
| **Run 03 (Chuẩn hóa Pipeline 3 bước)** | 30 | 27/30 | **90.0%** | **100% (8/8)** | Đạt trọn vẹn Quality Bar: Bắt trọn 8/8 ca khẩn cấp, chỉ nhầm 2 ca biên giữa 0 và 1. Trạng thái: **SHIP**. |

---

## §8. Phân công & kế hoạch
- **Phân công trách nhiệm:**
  - *Data Lead (Evidence & Evaluation):* Hùng — Khai thác k4_messages.csv tìm các ca câu hỏi bị bỏ rơi, dán nhãn bộ Golden Set (30 tin), sau đó trực tiếp tính toán tỷ lệ Precision/Recall để đo lường hiệu quả Before vs After.
  - *AI Engineer (Prompt & LLM):* Khánh  — Viết và tối ưu System Prompt phân loại Question Intent & Mức độ khẩn cấp (chuẩn hóa output JSON), kiểm thử prompt trực tiếp trên tập mẫu.
  - *UI/Backend/Pipeline Engineer:* Tú  — Viết code Python cho luồng worker: xử lý lọc tin theo mốc thời gian created_at_vn, map reply_to với msg_id, tích hợp gọi API LLM từ prompt và xuất dữ liệu cảnh báo.
  - *Product & Delivery Lead:* Chi  — Viết tài liệu Product Spec, vẽ sơ đồ luồng kiến trúc (architecture flow), thiết kế mẫu bản tin cảnh báo gửi TA và phụ trách toàn bộ slide thuyết trình cùng kịch bản demo.
- **Willing users (Thử nghiệm thực tế):**
  - Võ Đức Tài – 2A202603007, Đỗ Đình Long – 2A202602673, Phan Duy Thành – 2A202602930.
- **Multi-prototype:**
  - *Phương án A (Realtime Classifier):* Gọi phân loại từng tin nhắn khi vừa gửi tới -> Bị loại do chi phí API cao và không gom được ngữ cảnh trả lời ngầm.
  - *Phương án B (15-min Batch Sanitizer & Classifier — ĐƯỢC CHỌN):* Gom lô định kỳ 15 phút, lọc code thuần trước rồi gọi 1 lần LLM duy nhất. -> Tối ưu vượt trội về chi phí và độ chính xác ngữ cảnh.

---

## §9. Changelog
| Thời điểm | Đổi gì | Vì sao (Trỏ về feedback/case nào) |
| :--- | :--- | :--- |
| **20:00-17/09/2026** | Chuyển từ Realtime sang Batch Cron-job 15 phút | Tránh lãng phí token per-message và giảm tình trạng chai sạn cảnh báo (Alert Fatigue). |
| **10:00-18/09/2026** | Nâng nhãn cho các ca kẹt nền tảng (`M53930`, `M01360`) từ 1 lên 2 | Các ca này là Blocker kỹ thuật nghiêm trọng tương đương lỗi phòng học. |
