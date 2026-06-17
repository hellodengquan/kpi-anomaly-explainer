import pandas as pd
import numpy as np
from itertools import combinations
from db import get_connection


class DimensionAnalyzer:
    def __init__(self, db_path=None, window_size=7, config=None):
        self.db_path = db_path
        self.window_size = window_size
        self.config = config or {}

        dim_cfg = self.config.get("dimensions", [])
        self.dimensions = [d["name"] for d in dim_cfg] if dim_cfg else ["region", "product_line", "channel"]

        drilldown_cfg = self.config.get("analysis", {}).get("drilldown_layers", [])
        self.drilldown_layers = drilldown_cfg if drilldown_cfg else [self.dimensions]

        priority_cfg = self.config.get("analysis", {}).get("priority_combos", [])
        self.priority_combos = [tuple(pc) for pc in priority_cfg] if priority_cfg else []

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
        valid_cols = [c for c in group_cols if c in df.columns]
        daily = df.groupby(valid_cols + ["date"])[kpi_name].sum().reset_index()
        return daily.groupby(valid_cols)[kpi_name].agg(["mean", "std", "count"]).reset_index()

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

    def _is_priority(self, group_cols):
        gc_tuple = tuple(group_cols)
        for pc in self.priority_combos:
            if set(gc_tuple) == set(pc):
                return True
        return False

    def analyze_dimension(self, df, kpi_name, dimension):
        current, historical = self.split_windows(df)
        return self._compute_metrics(current, historical, kpi_name, [dimension])

    def analyze_all_dimensions(self, kpi_name="revenue"):
        df = self.load_data()
        results = {}
        for dim in self.dimensions:
            if dim not in df.columns:
                continue
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
                "is_priority_combo": self._is_priority([dim1, dim2]),
            })
        return pd.DataFrame(results)

    def _analyze_drilldown_layer(self, current, historical, kpi_name, layer_dims, parent_filter_top_n=3):
        if len(layer_dims) < 3:
            return pd.DataFrame()

        two_dim_keys = layer_dims[:2]
        third_dim = layer_dims[2]

        two_dim, _ = self._compute_metrics(current, historical, kpi_name, list(two_dim_keys))
        top_parents = two_dim.head(parent_filter_top_n)

        all_rows = []
        for _, parent_row in top_parents.iterrows():
            filter_mask = pd.Series(True, index=current.index)
            hist_filter_mask = pd.Series(True, index=historical.index)
            for d in two_dim_keys:
                filter_mask &= (current[d] == parent_row[d])
                hist_filter_mask &= (historical[d] == parent_row[d])

            curr_filtered = current[filter_mask].copy()
            hist_filtered = historical[hist_filter_mask].copy()

            if curr_filtered.empty and hist_filtered.empty:
                continue

            if third_dim not in curr_filtered.columns:
                continue

            three_dim, _ = self._compute_metrics(
                curr_filtered, hist_filtered, kpi_name, list(layer_dims)
            )

            for _, row in three_dim.head(5).iterrows():
                direction = "下降" if row["deviation"] < 0 else "上升"
                parent_label = " & ".join([f"{d}={parent_row[d]}" for d in two_dim_keys])
                all_rows.append({
                    "dimension_combo": row["label"],
                    "layer_dims": list(layer_dims),
                    "parent_combo": parent_label,
                    "curr_sum": round(row["curr_sum"], 2),
                    "hist_sum": round(row["hist_sum"], 2),
                    "deviation": round(row["deviation"], 2),
                    "deviation_pct": round(row["deviation_pct"], 2),
                    "contribution_in_parent": round(row["contribution"], 2),
                    "z_score": round(row["z_score"], 2),
                    "direction": direction,
                    "is_priority_combo": self._is_priority(layer_dims),
                })

        return pd.DataFrame(all_rows)

    def deep_dive(self, kpi_name="revenue", top_n=3):
        single_dim_results = self.analyze_all_dimensions(kpi_name)

        df = self.load_data()
        current, historical = self.split_windows(df)

        two_dim_frames = []
        for dim1, dim2 in combinations(self.dimensions, 2):
            if dim1 not in df.columns or dim2 not in df.columns:
                continue
            cross_df = self._analyze_cross(current, historical, kpi_name, dim1, dim2, top_n_per_group=top_n)
            if not cross_df.empty:
                two_dim_frames.append(cross_df)

        cross_df = pd.concat(two_dim_frames, ignore_index=True) if two_dim_frames else pd.DataFrame()
        if not cross_df.empty:
            cross_df["rank_weight"] = cross_df["is_priority_combo"].astype(int) * 0.2
            cross_df["sorted_score"] = cross_df["contribution"].abs() + cross_df["rank_weight"]
            cross_df = cross_df.sort_values("sorted_score", ascending=False).drop(columns=["sorted_score", "rank_weight"]).reset_index(drop=True)

        three_dim_frames = []
        for layer in self.drilldown_layers:
            if len(layer) >= 3 and all(d in df.columns for d in layer):
                layer_df = self._analyze_drilldown_layer(current, historical, kpi_name, layer, parent_filter_top_n=3)
                if not layer_df.empty:
                    three_dim_frames.append(layer_df)

        three_dim_df = pd.concat(three_dim_frames, ignore_index=True) if three_dim_frames else pd.DataFrame()
        if not three_dim_df.empty:
            three_dim_df = three_dim_df.sort_values("contribution_in_parent", key=abs, ascending=False).reset_index(drop=True)

        return single_dim_results, cross_df, three_dim_df
