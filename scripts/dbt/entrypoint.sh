#!/bin/sh
# Entrypoint của image dbt (27/11/2026).
#
#   scheduled  lượt định kỳ của dbt-scheduler (ofelia, mỗi 5 phút):
#                1. dbt build mọi model TRỪ tag audit;
#                2. build xong, nếu lần đối soát gần nhất đã cũ hơn AUDIT_EVERY_MIN phút
#                   (mặc định 60) thì chạy RIÊNG tag audit (audit.checksum_orders).
#   còn lại    chuyển thẳng cho dbt, như trước:
#                docker compose --profile dbt run --rm dbt build   (build cả audit)
#
# Vì sao đối soát chạy SAU build trong cùng một lượt chứ không phải job ofelia riêng mỗi giờ:
# no-overlap của ofelia chỉ chặn một job chồng lên chính nó, không chặn hai job khác nhau.
# Job riêng có thể rơi đúng lúc lượt 5 phút đang chạy, mà checksum_orders tốn tới 1,18 GiB
# (query_log 24 giờ tới 27/11/2026) trong khi trần RAM chung của ClickHouse là 2,70 GiB: 3 trên
# 4 lượt lỗi vượt trần ngày 26/11 có checksum chạy song song với model khác. Ở đây checksum chỉ
# chạy khi các model khác đã xong, và lượt 5 phút kế tiếp phải chờ lượt này xong (no-overlap).
#
# Mốc lần đối soát gần nhất: file /dbt/target/.last_audit (thư mục target/ đã bị git bỏ qua).
# Lượt build chính lỗi thì thoát luôn, không đối soát. Đối soát lỗi thì không cập nhật mốc,
# lượt sau thử lại.
set -eu

if [ "${1:-}" != "scheduled" ]; then
  exec dbt "$@"
fi
shift

dbt build --exclude tag:audit "$@"

mark=/dbt/target/.last_audit
every="${AUDIT_EVERY_MIN:-60}"
# Trừ 3 phút: lượt chạy mỗi 5 phút, mốc ghi lúc đối soát XONG, nên so đúng 60 phút thì lượt
# rơi vào phút 59 bị bỏ và đối soát lùi dần thành 65 phút một lần.
stale_after=$((every - 3))

if [ ! -f "$mark" ] || [ -n "$(find "$mark" -mmin +"$stale_after" 2>/dev/null)" ]; then
  echo "[entrypoint] đối soát (tag:audit): lần gần nhất đã quá ${every} phút"
  dbt build --select tag:audit "$@"
  mkdir -p "$(dirname "$mark")"
  touch "$mark"
else
  echo "[entrypoint] bỏ qua đối soát: chưa đủ ${every} phút từ lần gần nhất"
fi
