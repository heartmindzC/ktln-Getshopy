# Next-Week Purchase Prediction Service (`ai-next-week`)

Dịch vụ độc lập dự đoán xác suất khách hàng mua lại từng sản phẩm trong cửa sổ thời gian $W$ ngày tới (mặc định 7 ngày) trên nền tảng thương mại điện tử Getshopy.

---

## 1. Cơ sở lý thuyết & Thuật toán

Khác với kênh gợi ý sản phẩm tổng quát (Collaborative Filtering / Hybrid, xếp hạng tương đối), `ai-next-week` ước lượng **xác suất hiệu chuẩn tuyệt đối $P \in [0, 1]$** một khách hàng sẽ phát sinh hành vi mua lại món hàng cụ thể trong $W$ ngày tiếp theo.

Mô hình hỗ trợ hai biến thể xác suất:
1. **A1 — Modified Poisson–Gamma (`poisson_gamma`, Mặc định):**
   - Số lần mua lặp lại được mô hình hoá bằng Quá trình Poisson (Poisson Process) với tốc độ $\lambda_{ui}$.
   - Tần suất mua tiềm ẩn tuân theo phân phối tiên nghiệm Gamma $\lambda \sim \text{Gamma}(\alpha_c, \beta_c)$ theo từng danh mục `ParentCategory` học bằng phương pháp khớp Moment (Method of Moments).
   - Cập nhật hậu nghiệm Bayes thực nghiệm (Empirical Bayes):
     $$P(N_W \ge 1 \mid x, T_{\text{obs}}) = 1 - \left( \frac{\beta_c + T_{\text{obs}}}{\beta_c + T_{\text{obs}} + W} \right)^{\alpha_c + x}$$
   - Chu kỳ mua lặp lại kỳ vọng:
     $$\mathbb{E}[\text{Cycle}_{ui}] = \frac{\beta_c + T_{\text{obs}}}{\alpha_c + x} \quad (\text{ngày})$$
2. **A2 — Log-Normal Inter-Purchase Time Hazard (`ipt_hazard`):**
   - Khoảng cách giữa các lần mua $\Delta t \sim \text{LogNormal}(\mu_{ui}, \sigma_{ui}^2)$ kết hợp với tỷ lệ mua lặp lại $p_{\text{repeat}}(u, i)$.

> **Tài liệu tham khảo học thuật:**
> - Bhagat, R., Muralidharan, S., Lobzhanidze, A., & Vishwanath, S. (2018). *Buy It Again: Modeling Repeat Purchase Recommendations*. KDD '18, 62–70.
> - Fader, P. S., Hardie, B. G. S., & Lee, K. L. (2005). *"Counting Your Customers" the Easy Way: An Alternative to the Pareto/NBD Model*. Marketing Science, 24(2).
> - Wang, J., & Zhang, Y. (2013). *Opportunity Model for E-Commerce Recommendation: Right Product; Right Time*. SIGIR '13, 303–312.

---

## 2. API Endpoints

Cổng nội bộ: `8002` (qua Gateway Nginx: `/api/v1/predict/next-week/*` và `/next-week/*`).

| Phương thức | Endpoint | Mô tả |
| :--- | :--- | :--- |
| `GET` | `/health` | Kiểm tra tình trạng sức khỏe, số lượng khách, cặp theo dõi, phiên bản mô hình. |
| `GET` | `/api/v1/predict/next-week/customer/{customer_id}?top_k=10&horizon_days=7&min_prob=0.05` | Dự đoán top sản phẩm khách có xác suất mua lại cao nhất trong $W$ ngày tới kèm lịch sử đã mua. |
| `POST` | `/api/v1/predict/next-week` | Dự đoán thời gian thực gộp các món khách vừa mua trong ngày (`DaysSince = 0`). |
| `POST` | `/admin/train` | Kích hoạt huấn luyện lại tức thì từ kho dữ liệu ClickHouse. |

---

## 3. Kiến trúc dữ liệu & Huấn luyện

- **Dữ liệu nguồn:** Đọc trực tiếp từ kho ClickHouse:
  - `serving.purchase_events_for_AI_rec`: Lịch sử đơn hàng kèm `DaysSince`.
  - `serving.catalog_features`: Danh mục sản phẩm `ParentCategory`.
- **Lịch trình huấn luyện:** Tự động chạy định kỳ mỗi ngày lúc `22:00` (`TRAIN_DAILY_AT`) theo múi giờ `Asia/Ho_Chi_Minh`.
- **Lưu trữ Model:** Artifact được lưu ra volume `ai_next_week_models:/app/output/next_week/predictor.joblib`.
