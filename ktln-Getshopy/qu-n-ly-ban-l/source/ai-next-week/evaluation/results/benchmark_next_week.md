# Benchmark: Dự đoán sản phẩm mua lại trong 7 ngày tới (Phương án A)

> **Ngày chạy:** 2026-11-23 16:24 UTC  
> **Dữ liệu:** `evaluation/data/order_lines.csv` (6,373,091 sự kiện cấp đơn hàng; 39,578 khách; 15,136 sản phẩm)  
> **Cửa sổ dự đoán:** $W = 7$ ngày (chia Temporal Split, không rò rỉ tương lai)

## Validation (cut = max - 14d)

- **Mốc cắt:** `2026-09-26 19:49:44` $\to$ `2026-10-03 19:49:44`
- **Cặp ứng viên (đã mua trước cut):** 3,829,078 | **Dương tính (mua lại trong 7 ngày):** 62,325 (1.63%) | **Khách có mua lại:** 20,502
- **Thời gian fit:** 10.30s

| Mô hình | ROC-AUC ↑ | PR-AUC ↑ | Brier ↓ | LogLoss ↓ | Precision@10 ↑ | Recall@10 ↑ | HitRate@10 ↑ |
|---|---:|---:|---:|---:|---:|---:|---:|
| RepeatBaseline (hl=37d) | 0.6931 | 0.0920 | 0.08552 | 0.2811 | 0.0914 | 0.3279 | 0.5934 |
| A1: Poisson-Gamma | 0.7468 | 0.1126 | 0.01532 | 0.0755 | 0.1107 | 0.4058 | 0.6825 |
| A2: IPT LogNormal Hazard | 0.7405 | 0.1075 | 0.01547 | 0.0775 | 0.1079 | 0.3945 | 0.6716 |

## Test (cut = max - 7d)

- **Mốc cắt:** `2026-10-03 19:49:44` $\to$ `2026-10-10 19:49:44`
- **Cặp ứng viên (đã mua trước cut):** 3,901,334 | **Dương tính (mua lại trong 7 ngày):** 54,346 (1.39%) | **Khách có mua lại:** 19,210
- **Thời gian fit:** 10.78s

| Mô hình | ROC-AUC ↑ | PR-AUC ↑ | Brier ↓ | LogLoss ↓ | Precision@10 ↑ | Recall@10 ↑ | HitRate@10 ↑ |
|---|---:|---:|---:|---:|---:|---:|---:|
| RepeatBaseline (hl=37d) | 0.6960 | 0.0810 | 0.08377 | 0.2755 | 0.0862 | 0.3280 | 0.5769 |
| A1: Poisson-Gamma | 0.7488 | 0.0993 | 0.01329 | 0.0671 | 0.1038 | 0.4024 | 0.6634 |
| A2: IPT LogNormal Hazard | 0.7424 | 0.0950 | 0.01347 | 0.0702 | 0.1007 | 0.3889 | 0.6478 |

## Kết luận chọn mô hình mặc định

- **Mô hình thắng trên Validation:** `A1: Poisson-Gamma` (`NEXT_WEEK_MODEL_TYPE = "poisson_gamma"`)
- Tổng thời gian chạy benchmark: 61.1s
