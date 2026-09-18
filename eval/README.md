# Evaluation data contract

## CP3 official run

Các file chính thức để nộp CP3 là:

- `cp3_golden_set.json`: 22 case public đã khóa trước khi chạy lượt đầu.
- `cp3_user_input_grid.csv`: coverage theo năm chiều đầu vào.
- `results/cp3-run-1-cases.csv`: đủ 22 kết quả, gồm cả case sai.
- `results/cp3-run-1-summary.json`: 21/22 đạt (95,5%), URGENT 5/5, provider error 0.
- `results/cp3-run-1-analysis.md`: phân tích case sai và giới hạn của phép đo.
- `results/cp3-run-1-traces.jsonl`: prompt đầu vào và raw model response của 22 lời gọi thật.
- `cp3-review-workbook.xlsx`: bản dễ đọc để nhóm review và điền chấm độc lập.

`phase3-golden-summary.json` là regression trên bộ private 30 case cũ, không phải số đo CP3 chính
thức. Không trộn kết quả hai bộ khi điền form.

Thư mục này chỉ chứa fixture giả an toàn để public. Không đặt raw Discord export,
golden set thật, message ID thật hoặc báo cáo có nội dung chat vào đây.

## Dataset roles

- `eval/fixtures/public_sample.csv`: 12 dòng giả để test parser và demo rule engine.
- Master labels riêng tư: calibration/regression set, không phải blind benchmark.
- `k4_train.csv`: chỉ dùng để phát triển prompt/rule với nhãn `IGNORE` và `NORMAL`.
- `golden_test_30.csv`: regression set đã khóa, chứa đủ 8 mẫu `URGENT` thật.
- Blind test hợp lệ phải lấy dữ liệu mới sau khi prompt và quality bar đã khóa.

Không fine-tune model trên bộ dữ liệu nhỏ này. Không tối ưu prompt bằng cách đọc lỗi
từng dòng trong golden rồi chạy lại mà không tăng `prompt_version`.

## Chạy validator

Tạo `.env` từ `.env.example`, điền bốn đường dẫn local rồi chạy từ repo root:

```bash
make validate-splits
```

Nếu máy không có GNU Make, chạy runner Python cross-platform:

```bash
python scripts/phase0.py
```

Hoặc chạy trực tiếp:

```bash
cd codebase/backend
python -m app.eval.dataset_validator \
  --messages /private/path/k4_messages.csv \
  --labels /private/path/k4_labels.csv \
  --train /private/path/k4_train.csv \
  --golden /private/path/golden_test_30.csv \
  --json-output ../../.private/phase0-data-report.json \
  --manifest-output ../../.private/split-manifest.json
```

Validator không in nội dung chat. Report chỉ chứa số đếm; manifest chỉ chứa hash và
phân bố nhãn. Hai output mặc định nằm trong `.private/` và bị Git ignore.

## Metrics khóa cho Phase 3

- Macro F1 trên ba nhãn.
- Precision và recall theo từng nhãn.
- `URGENT recall` phải hiển thị cả tỷ lệ và dạng `x/8`.
- Confusion matrix 3×3.
- Không dùng accuracy đơn lẻ để kết luận vì lớp `IGNORE` chiếm đa số.

## Chạy Phase 3 classifier evaluation

Golden evaluation cần cả file golden và message source để tái tạo tối đa ba tin trước/sau cùng
channel trong time window. Khai báo trong `.env` local, không commit đường dẫn hoặc dữ liệu:

```text
PRIVATE_GOLDEN_CSV=/private/path/golden_test_30.csv
PRIVATE_MESSAGES_CSV=/private/path/k4_messages.csv
```

Chạy riêng:

```bash
cd codebase/backend
python -m app.eval.classifier_runner --dataset hard
python -m app.eval.classifier_runner --dataset golden
```

Hoặc chạy test và cả hai eval từ repo root:

```bash
python scripts/phase3.py
```

Báo cáo tổng hợp an toàn để commit nằm tại `eval/results/phase3-*-summary.json`. Cache và prediction
theo từng case chỉ chứa hash, nằm trong `.private/eval/` và bị Git ignore. Chạy lại cùng model,
prompt và request sẽ dùng cache; thêm `--no-cache` để bắt buộc gọi provider.

Kết quả ngày 18/09/2026 với prompt `classifier-v4` và model `cx/gpt-5.6-luna`:

- Golden K4: 30/30 đúng, URGENT 8/8, actionable 19/19, notification precision 19/19.
- Hard cases: 6/6 đúng, URGENT 2/2, prompt injection không đổi task.

Đây là regression/calibration evidence, không phải blind benchmark. Không tiếp tục tune prompt trên
golden; vòng đánh giá tiếp theo phải dùng dữ liệu mới được gán nhãn độc lập.
