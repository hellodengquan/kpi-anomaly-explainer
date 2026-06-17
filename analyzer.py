import pandas as pd
import numpy as np
from itertools import combinations
from db import get_connection


DIMENSIONS = ["region", "product_line", "channel"]
PRIORITY_COMBO = ("region", "product_line")


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

    def _compute_metrics(self, current, historical, kpi_name, group_cols):
        curr_daily = self._daily_agg(current, kpi_name, group_cols)
        curr_daily.columns = group_cols + ["curr_mean", "curr_std", "curr_count"]

        hist_daily = self._daily_agg(historical, kpi_name, group_cols)
        hist_daily.columns = group_cols + ["hist_mean", "hist_std", "hist_count"]

        curr_total = current.groupby(group_cols)[kpi_name].sum().reset_index()
        curr_total.columns = group_cols + ["curr_sum"]

        hist_total = historical.groupby(group_cols)[kpi_name].sum().reset_index()
        hist_total.columns = group_cols + ["hist_sum"]

        merged = pd.merge(curr_daily, hist_daily, on=group_cols, how="outer").fillna(0)
        merged = pd.merge(merged, curr_total, on=group_cols, how="outer").fillna(0)
        merged = pd.merge(merged, hist_total, on=group_cols, how="outer").fillna(0)
        merged["hist_std"] = merged["hist_std"].replace(0, 1e-9)

        curr_n_days = current["date"].nunique()

        total_curr_daily = merged["curr_mean"].sum()
        total_hist_daily = merged["hist_mean"].sum()
        total_daily_dev = total_curr_daily - total_hist_daily

        merged["deviation"] = (merged["curr_mean"] - merged["hist_mean"]) * curr_n_days
        merged["deviation_pct"] = ((merged["curr_mean"] - merged["hist_mean"]) / merged["hist_mean"].replace(0, 1e-9)) * 100
        merged["contribution"] = ((merged["curr_mean"] - merged["hist_mean"]) / total_daily_dev * 100) if total_daily_dev != 0 else 0
        merged["z_score"] = (merged["curr_mean"] - merged["hist_mean"]) / merged["hist_std"]

        merged = merged.sort_values("contribution", key=abs, ascending=False).reset_index(drop=True)

        if len(group_cols) == 1:
            merged["dimension_name"] = group_cols[0]
            merged["label"] = merged[group_cols[0]].astype(str)
        else:
            merged["dimension_name"] = "+".join(group_cols)
            merged["label"] = merged.apply(
                lambda r: " & ".join([f"{d}={r[d]}" for d in group_cols]), axis=1
            )

        return merged, total_daily_dev * curr_n_days

    def analyze_dimension(self, df, kpi_name, dimension):
        current, historical = self.split_windows(df)
        return self._compute_metrics(current, historical, kpi_name, [dimension])

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

    def _analyze_cross(self, current, historical, kpi_name, dim1, dim2, top_n_per_group=3):
        merged, _ = self._compute_metrics(current, historical, kpi_name, [dim1, dim2])
        top = merged.head(top_n_per_group * 3).copy()
        results = []
        for _, row in top.iterrows():
            direction = "下降" if row["deviation"] < 0 else "上升"
            results.append({
                "dimension_combo": row["label"],
                "dim1": dim1,
                "dim1_value": row[dim1],
                "dim2": dim2,
                "dim2_value": row[dim2],
                "curr_sum": round(row["curr_sum"], 2),
                "hist_sum": round(row["hist_sum"], 2),
                "curr_mean": round(row["curr_mean"], 2),
                "hist_mean": round(row["hist_mean"], 2),
                "deviation": round(row["deviation"], 2),
                "deviation_pct": round(row["deviation_pct"], 2),
                "contribution": round(row["contribution"], 2),
                "z_score": round(row["z_score"], 2),
                "direction": direction,
                "is_priority_combo": (dim1, dim2) == PRIORITY_COMBO or (dim2, dim1) == PRIORITY_COMBO,
            })
        return pd.DataFrame(results)

    def _analyze_three_dim(self, current, historical, kpi_name, parent_filter_top_n=3):
        dim1, dim2 = PRIORITY_COMBO
        two_dim, _ = self._compute_metrics(current, historical, kpi_name, [dim1, dim2])
        top_parents = two_dim.head(parent_filter_top_n)

        all_three = []
        for _, parent_row in top_parents.iterrows():
            filter_mask = (current[dim1] == parent_row[dim1]) & (current[dim2] == parent_row[dim2])
            hist_filter_mask = (historical[dim1] == parent_row[dim1]) & (historical[dim2] == parent_row[dim2])

            curr_filtered = current[filter_mask].copy()
            hist_filtered = historical[hist_filter_mask].copy()

            if curr_filtered.empty and hist_filtered.empty:
                continue

            three_dim, _ = self._compute_metrics(
                curr_filtered, hist_filtered, kpi_name, [dim1, dim2, "channel"]
            )

            for _, row in three_dim.head(5).iterrows():
                direction = "下降" if row["deviation"] < 0 else "上升"
                all_three.append({
                    "dimension_combo": row["label"],
                    "dim1": dim1,
                    "dim1_value": row[dim1],
                    "dim2": dim2,
                    "dim2_value": row[dim2],
                    "dim3": "channel",
                    "dim3_value": row["channel"],
                    "parent_combo": f"{dim1}={parent_row[dim1]} & {dim2}={parent_row[dim2]}",
                    "curr_sum": round(row["curr_sum"], 2),
                    "hist_sum": round(row["hist_sum"], 2),
                    "deviation": round(row["deviation"], 2),
                    "deviation_pct": round(row["deviation_pct"], 2),
                    "contribution_in_parent": round(row["contribution"], 2),
                    "z_score": round(row["z_score"], 2),
                    "direction": direction,
                })

        return pd.DataFrame(all_three)

    def deep_dive(self, kpi_name="revenue", top_n=3):
        single_dim_results = self.analyze_all_dimensions(kpi_name)

        df = self.load_data()
        current, historical = self.split_windows(df)

        two_dim_frames = []
        for dim1, dim2 in combinations(DIMENSIONS, 2):
            cross_df = self._analyze_cross(current, historical, kpi_name, dim1, dim2, top_n_per_group=top_n)
            if not cross_df.empty:
                two_dim_frames.append(cross_df)

        cross_df = pd.concat(two_dim_frames, ignore_index=True) if two_dim_frames else pd.DataFrame()
        if not cross_df.empty:
            priority_mask = cross_df["is_priority_combo"] == True
            cross_df["rank_weight"] = cross_df["is_priority_combo"].astype(int) * 0.2
            cross_df["sorted_score"] = cross_df["contribution"].abs() + cross_df["rank_weight"]
            cross_df = cross_df.sort_values("sorted_score", ascending=False).drop(columns=["sorted_score", "rank_weight"]).reset_index(drop=True)

        three_dim_df = self._analyze_three_dim(current, historical, kpi_name, parent_filter_top_n=3)

        return single_dim_results, cross_df, three_dim_df
