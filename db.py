import sqlite3
import random
import datetime
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kpi_data.db")

REGIONS = ["华东", "华南", "华北", "西南", "华中"]
PRODUCT_LINES = ["手机", "电脑", "平板", "穿戴设备"]
CHANNELS = ["线上直营", "线下门店", "分销商", "运营商"]

CREATE_KPI_METRICS_SQL = """
CREATE TABLE IF NOT EXISTS kpi_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    region TEXT NOT NULL,
    product_line TEXT NOT NULL,
    channel TEXT NOT NULL,
    revenue REAL NOT NULL,
    order_count INTEGER NOT NULL,
    avg_price REAL NOT NULL
)
"""

CREATE_KPI_META_SQL = """
CREATE TABLE IF NOT EXISTS kpi_meta (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kpi_name TEXT NOT NULL UNIQUE,
    description TEXT,
    unit TEXT,
    expected_direction TEXT
)
"""


def get_connection(db_path=None):
    path = db_path or DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn):
    cursor = conn.cursor()
    cursor.execute(CREATE_KPI_METRICS_SQL)
    cursor.execute(CREATE_KPI_META_SQL)
    conn.commit()


def seed_meta(conn):
    meta_rows = [
        ("revenue", "营收金额", "元", "up"),
        ("order_count", "订单数量", "单", "up"),
        ("avg_price", "平均客单价", "元/单", "up"),
    ]
    cursor = conn.cursor()
    for row in meta_rows:
        cursor.execute(
            "INSERT OR IGNORE INTO kpi_meta (kpi_name, description, unit, expected_direction) VALUES (?, ?, ?, ?)",
            row,
        )
    conn.commit()


def seed_metrics(conn, days=90, anomaly_day_offset=5):
    cursor = conn.cursor()
    cursor.execute("DELETE FROM kpi_metrics")

    base_date = datetime.date.today() - datetime.timedelta(days=days)

    base_revenues = {
        "华东": {"手机": 520000, "电脑": 380000, "平板": 210000, "穿戴设备": 150000},
        "华南": {"手机": 480000, "电脑": 350000, "平板": 190000, "穿戴设备": 130000},
        "华北": {"手机": 450000, "电脑": 320000, "平板": 180000, "穿戴设备": 120000},
        "西南": {"手机": 300000, "电脑": 220000, "平板": 130000, "穿戴设备": 90000},
        "华中": {"手机": 340000, "电脑": 250000, "平板": 150000, "穿戴设备": 100000},
    }

    channel_ratios = {
        "线上直营": 0.35,
        "线下门店": 0.30,
        "分销商": 0.20,
        "运营商": 0.15,
    }

    random.seed(42)

    rows = []
    for day_idx in range(days):
        current_date = base_date + datetime.timedelta(days=day_idx)
        date_str = current_date.isoformat()

        is_anomaly_window = day_idx >= (days - anomaly_day_offset)

        for region in REGIONS:
            for product_line in PRODUCT_LINES:
                for channel in CHANNELS:
                    base_rev = base_revenues[region][product_line] * channel_ratios[channel]
                    weekday = current_date.weekday()
                    if weekday >= 5:
                        base_rev *= 0.75
                    noise = random.gauss(0, base_rev * 0.05)
                    revenue = base_rev + noise

                    if is_anomaly_window:
                        if region == "华东" and product_line == "手机" and channel == "线上直营":
                            revenue *= random.uniform(0.45, 0.55)
                        if region == "华南" and product_line == "平板":
                            revenue *= random.uniform(1.30, 1.45)

                    revenue = max(0, revenue)
                    order_count = max(1, int(revenue / random.uniform(150, 450)))
                    avg_price = revenue / order_count if order_count > 0 else 0

                    rows.append((date_str, region, product_line, channel, round(revenue, 2), order_count, round(avg_price, 2)))

    cursor.executemany(
        "INSERT INTO kpi_metrics (date, region, product_line, channel, revenue, order_count, avg_price) VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()


def setup(db_path=None):
    conn = get_connection(db_path)
    init_schema(conn)
    seed_meta(conn)
    seed_metrics(conn)
    conn.close()


if __name__ == "__main__":
    setup()
    print(f"Database initialized at {DB_PATH}")
