# dbt-core + adapter ClickHouse.
#
# Chạy tay (entrypoint chuyển thẳng cho dbt):
#   docker compose --profile dbt run --rm dbt build
#   docker compose --profile dbt run --rm dbt test
# Lượt định kỳ của dbt-scheduler gọi `scheduled` — xem entrypoint.sh.
FROM python:3.11.18-slim-trixie

RUN pip install --no-cache-dir \
      dbt-core==1.8.9 \
      dbt-clickhouse==1.8.5

COPY entrypoint.sh /usr/local/bin/dbt-entrypoint
RUN chmod +x /usr/local/bin/dbt-entrypoint

WORKDIR /dbt
ENV DBT_PROFILES_DIR=/dbt
ENTRYPOINT ["dbt-entrypoint"]
CMD ["--help"]
