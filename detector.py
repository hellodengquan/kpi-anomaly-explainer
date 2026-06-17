import pandas as pd
import numpy as np
from statsmodels.tsa.seasonal import STL
from db import get_connection


class AnomalyDetector:
    def __init__(self, window_size=7, seasonal_period=7, z_threshold=2.0, db_path=None):
        self.window_size = window_size
        self.seasonal_period = seasonal_period
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

    def stl_decompose(self, series):
        min_length = max(self.seasonal_period * 2, 14)
        if len(series) < min_length:
            rolling_mean = series.rolling(window=self.seasonal_period, min_periods=1).mean()
            rolling_std = series.rolling(window=self.seasonal_period, min_periods=1).std()
            trend = rolling_mean
            seasonal = pd.Series(np.zeros(len(series)), index=series.index)
            residual = series - trend - seasonal
            resid_std = rolling_std.fillna(0).replace(0, 1e-9)
            return trend, seasonal, residual, resid_std

        freq = self.seasonal_period
        stl = STL(series, period=freq, seasonal=7, trend=None, robust=True)
        result = stl.fit()
        trend = pd.Series(result.trend, index=series.index)
        seasonal = pd.Series(result.seasonal, index=series.index)
        residual = pd.Series(result.resid, index=series.index)
        expected = trend + seasonal

        resid_std = residual.rolling(window=self.seasonal_period, min_periods=1).std()
        resid_std = resid_std.fillna(0).replace(0, 1e-9)

        return expected, seasonal, residual, resid_std

    def detect(self, kpi_name="revenue"):
        df = self.load_daily_kpi(kpi_name)
        if df.empty:
            return df

        col = kpi_name
        series = df.set_index("date")[col].asfreq("D")
        expected, seasonal, residual, resid_std = self.stl_decompose(series)

        expected = expected.reset_index(drop=True)
        seasonal = seasonal.reset_index(drop=True)
        residual = residual.reset_index(drop=True)
        resid_std = resid_std.reset_index(drop=True)

        df["expected"] = expected
        df["seasonal"] = seasonal
        df["residual"] = residual
        df["resid_std"] = resid_std
        df["deviation"] = residual
        df["deviation_pct"] = (df["deviation"] / df["expected"].replace(0, 1e-9)) * 100
        df["z_score"] = df["deviation"] / df["resid_std"]
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

        curr_resid_mean = current["residual"].mean()
        curr_resid_std = current["resid_std"].mean()
        if curr_resid_std == 0:
            curr_resid_std = 1e-9
        stl_z = curr_resid_mean / curr_resid_std

        summary = {
            "kpi_name": kpi_name,
            "current_window_days": len(current),
            "current_mean": round(curr_mean, 2),
            "historical_mean": round(hist_mean, 2),
            "historical_std": round(hist_std, 2),
            "overall_deviation": round(overall_deviation, 2),
            "overall_deviation_pct": round(overall_deviation_pct, 2),
            "overall_z_score": round(overall_z, 2),
            "stl_residual_mean": round(curr_resid_mean, 2),
            "stl_z_score": round(stl_z, 2),
            "is_anomalous": abs(stl_z) > self.z_threshold,
            "anomaly_direction": "下降" if overall_deviation < 0 else "上升",
            "date_range": f"{current['date'].min().strftime('%Y-%m-%d')} ~ {current['date'].max().strftime('%Y-%m-%d')}",
        }

        return current, historical, summary
