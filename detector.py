import pandas as pd
import numpy as np
from db import get_connection


class AnomalyDetector:
    def __init__(self, window_size=7, z_threshold=2.0, db_path=None):
        self.window_size = window_size
        self.z_threshold = z_threshold
        self.db_path = db_path

    def load_daily_kpi(self, kpi_name="revenue"):
        conn = get_connection(self.db_path)
        query = """
            SELECT date, SUM(revenue) AS revenue, SUM(order_count) AS order_count,
                   SUM(revenue) * 1.0 / NULLIF(SUM(order_count), 0) AS avg_price
            FROM kpi_metrics
            GROUP BY date
            ORDER BY date
        """
        df = pd.read_sql_query(query, conn)
        conn.close()
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        return df

    def compute_rolling_stats(self, series):
        rolling_mean = series.rolling(window=self.window_size, min_periods=1).mean()
        rolling_std = series.rolling(window=self.window_size, min_periods=1).std()
        rolling_std = rolling_std.fillna(0).replace(0, 1e-9)
        return rolling_mean, rolling_std

    def detect(self, kpi_name="revenue"):
        df = self.load_daily_kpi(kpi_name)
        if df.empty:
            return df

        col = kpi_name
        rolling_mean, rolling_std = self.compute_rolling_stats(df[col])

        df["rolling_mean"] = rolling_mean
        df["rolling_std"] = rolling_std
        df["deviation"] = df[col] - df["rolling_mean"]
        df["deviation_pct"] = (df["deviation"] / df["rolling_mean"].replace(0, 1e-9)) * 100
        df["z_score"] = df["deviation"] / rolling_std
        df["is_anomaly"] = df["z_score"].abs() > self.z_threshold

        return df

    def get_current_window(self, kpi_name="revenue", last_n=None):
        df = self.detect(kpi_name)
        n = last_n or self.window_size
        current = df.tail(n).copy()
        historical = df.iloc[:-n].copy() if len(df) > n else df.copy()

        if historical.empty:
            return current, historical, {}

        hist_mean = historical[kpi_name].mean()
        hist_std = historical[kpi_name].std()
        if pd.isna(hist_std) or hist_std == 0:
            hist_std = 1e-9

        curr_mean = current[kpi_name].mean()
        overall_deviation = curr_mean - hist_mean
        overall_deviation_pct = (overall_deviation / hist_mean) * 100 if hist_mean != 0 else 0
        overall_z = overall_deviation / hist_std

        summary = {
            "kpi_name": kpi_name,
            "current_window_days": len(current),
            "current_mean": round(curr_mean, 2),
            "historical_mean": round(hist_mean, 2),
            "historical_std": round(hist_std, 2),
            "overall_deviation": round(overall_deviation, 2),
            "overall_deviation_pct": round(overall_deviation_pct, 2),
            "overall_z_score": round(overall_z, 2),
            "is_anomalous": abs(overall_z) > self.z_threshold,
            "anomaly_direction": "下降" if overall_deviation < 0 else "上升",
            "date_range": f"{current['date'].min().strftime('%Y-%m-%d')} ~ {current['date'].max().strftime('%Y-%m-%d')}",
        }

        return current, historical, summary
