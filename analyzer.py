import pandas as pd
import numpy as np
from db import get_connection


DIMENSIONS = ["region", "product_line", "channel"]


class DimensionAnalyzer:
    def __init__(self, db_path=None, window_size=7):
        self.db_path = db_path
        self.window_size = window_size

    def load_data(self):
        conn = get_connection(self.db_path)
        query = "SELECT * FROM kpi_metrics ORDER BY date"
        df = pd.read_sql_query(query, conn)
        conn.close()
        df["date"] = pd.to_datetime(df["date"])
        return df

    def split_windows(self, df):
        dates = df["date"].sort_values().unique()
        if len(dates) <= self.window_size:
            return df, df
        cutoff = dates[-self.window_size]
        current = df[df["date"] >= cutoff].copy()
        historical = df[df["date"] < cutoff].copy()
        return current, historical

    def _daily_agg(self, df, kpi_name, group_cols):
        daily = df.groupby(group_cols + ["date"])[kpi_name].sum().reset_index()
        return daily.groupby(group_cols)[kpi_name].agg(["mean", "std", "count"]).reset_index()

    def analyze_dimension(self, df, kpi_name, dimension):
        current, historical = self.split_windows(df)

        curr_daily = self._daily_agg(current, kpi_name, [dimension])
        curr_daily.columns = [dimension, "curr_mean", "curr_std", "curr_count"]

        hist_daily = self._daily_agg(historical, kpi_name, [dimension])
        hist_daily.columns = [dimension, "hist_mean", "hist_std", "hist_count"]

        curr_total = current.groupby(dimension)[kpi_name].sum().reset_index()
        curr_total.columns = [dimension, "curr_sum"]

        hist_total = historical.groupby(dimension)[kpi_name].sum().reset_index()
        hist_total.columns = [dimension, "hist_sum"]

        merged = pd.merge(curr_daily, hist_daily, on=dimension, how="outer").fillna(0)
        merged = pd.merge(merged, curr_total, on=dimension, how="outer").fillna(0)
        merged = pd.merge(merged, hist_total, on=dimension, how="outer").fillna(0)
        merged["hist_std"] = merged["hist_std"].replace(0, 1e-9)

        curr_n_days = current["date"].nunique()
        hist_n_days = historical["date"].nunique() if not historical.empty else 1

        total_curr_daily_sum = merged["curr_mean"].sum()
        total_hist_daily_sum = merged["hist_mean"].sum()
        total_daily_deviation = total_curr_daily_sum - total_hist_daily_sum

        merged["deviation"] = (merged["curr_mean"] - merged["hist_mean"]) * curr_n_days
        merged["deviation_pct"] = ((merged["curr_mean"] - merged["hist_mean"]) / merged["hist_mean"].replace(0, 1e-9)) * 100
        merged["contribution"] = ((merged["curr_mean"] - merged["hist_mean"]) / total_daily_deviation * 100) if total_daily_deviation != 0 else 0
        merged["z_score"] = (merged["curr_mean"] - merged["hist_mean"]) / merged["hist_std"]

        merged = merged.sort_values("contribution", key=abs, ascending=False).reset_index(drop=True)
        merged["dimension_name"] = dimension

        return merged, total_daily_deviation * curr_n_days

    def analyze_all_dimensions(self, kpi_name="revenue"):
        df = self.load_data()
        results = {}
        for dim in DIMENSIONS:
            dim_result, total_dev = self.analyze_dimension(df, kpi_name, dim)
            results[dim] = {
                "data": dim_result,
                "total_deviation": total_dev,
            }
        return results

    def deep_dive(self, kpi_name="revenue", top_n=3):
        single_dim_results = self.analyze_all_dimensions(kpi_name)

        df = self.load_data()
        current, historical = self.split_windows(df)

        cross_results = []
        for dim1 in DIMENSIONS:
            for dim2 in DIMENSIONS:
                if dim1 >= dim2:
                    continue

                curr_daily = self._daily_agg(current, kpi_name, [dim1, dim2])
                curr_daily.columns = [dim1, dim2, "curr_mean", "curr_std", "curr_count"]

                hist_daily = self._daily_agg(historical, kpi_name, [dim1, dim2])
                hist_daily.columns = [dim1, dim2, "hist_mean", "hist_std", "hist_count"]

                curr_total = current.groupby([dim1, dim2])[kpi_name].sum().reset_index()
                curr_total.columns = [dim1, dim2, "curr_sum"]

                hist_total = historical.groupby([dim1, dim2])[kpi_name].sum().reset_index()
                hist_total.columns = [dim1, dim2, "hist_sum"]

                merged = pd.merge(curr_daily, hist_daily, on=[dim1, dim2], how="outer").fillna(0)
                merged = pd.merge(merged, curr_total, on=[dim1, dim2], how="outer").fillna(0)
                merged = pd.merge(merged, hist_total, on=[dim1, dim2], how="outer").fillna(0)
                merged["hist_std"] = merged["hist_std"].replace(0, 1e-9)

                curr_n_days = current["date"].nunique()

                total_daily_dev = merged["curr_mean"].sum() - merged["hist_mean"].sum()

                merged["deviation"] = (merged["curr_mean"] - merged["hist_mean"]) * curr_n_days
                merged["deviation_pct"] = ((merged["curr_mean"] - merged["hist_mean"]) / merged["hist_mean"].replace(0, 1e-9)) * 100
                merged["contribution"] = ((merged["curr_mean"] - merged["hist_mean"]) / total_daily_dev * 100) if total_daily_dev != 0 else 0
                merged["z_score"] = (merged["curr_mean"] - merged["hist_mean"]) / merged["hist_std"]

                top = merged.reindex(merged["contribution"].abs().sort_values(ascending=False).index).head(top_n)
                for _, row in top.iterrows():
                    direction = "下降" if row["deviation"] < 0 else "上升"
                    cross_results.append({
                        "dimension_combo": f"{dim1}={row[dim1]} & {dim2}={row[dim2]}",
                        "dim1": dim1,
                        "dim1_value": row[dim1],
                        "dim2": dim2,
                        "dim2_value": row[dim2],
                        "curr_sum": round(row["curr_sum"], 2),
                        "hist_sum": round(row["hist_sum"], 2),
                        "deviation": round(row["deviation"], 2),
                        "deviation_pct": round(row["deviation_pct"], 2),
                        "contribution": round(row["contribution"], 2),
                        "z_score": round(row["z_score"], 2),
                        "direction": direction,
                    })

        cross_df = pd.DataFrame(cross_results)
        if not cross_df.empty:
            cross_df = cross_df.sort_values("contribution", key=abs, ascending=False).reset_index(drop=True)

        return single_dim_results, cross_df
