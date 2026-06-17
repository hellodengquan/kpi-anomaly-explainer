import pandas as pd
import numpy as np
from itertools import combinations
from db import get_connection


class DimensionAnalyzer:
    def __init__(self, db_path=None, window_size=7, config=None):
        self.db_path = db_path
        self.window_size = window_size
        self.config = config or {}
        self._apply_config()

    def _apply_config(self):
        dim_cfg = self.config.get("dimensions", [])
        self.dimensions = [d["name"] for d in dim_cfg] if dim_cfg else ["region", "product_line", "channel", "member_level"]

        drilldown_cfg = self.config.get("analysis", {}).get("drilldown_layers", [])
        self.drilldown_layers = drilldown_cfg if drilldown_cfg else [self.dimensions]

        priority_cfg = self.config.get("analysis", {}).get("priority_combos", [])
        self.priority_combos = [tuple(pc) for pc in priority_cfg] if priority_cfg else []

    def reload_config(self, new_config=None):
        if new_config is None:
            from reporter import load_config
            new_config = load_config()
        self.config = new_config
        self._apply_config()
        return {
            "dimensions": self.dimensions,
            "drilldown_layers": self.drilldown_layers,
            "priority_combos": self.priority_combos,
            "window_size": self.window_size,
        }

    def get_config_snapshot(self):
        return {
            "dimensions": self.dimensions,
            "drilldown_layers": self.drilldown_layers,
            "priority_combos": self.priority_combos,
            "window_size": self.window_size,
        }

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
        if not valid_cols:
            return pd.DataFrame()
        daily = df.groupby(valid_cols + ["date"])[kpi_name].sum().reset_index()
        return daily.groupby(valid_cols)[kpi_name].agg(["mean", "std", "count"]).reset_index()

    def _compute_metrics(self, current, historical, kpi_name, group_cols, parent_total_dev=None):
        valid_cols = [c for c in group_cols if c in current.columns]
        if not valid_cols:
            return pd.DataFrame(), 0.0

        curr_daily = self._daily_agg(current, kpi_name, valid_cols)
        if curr_daily.empty:
            return pd.DataFrame(), 0.0
        curr_daily.columns = valid_cols + ["curr_mean", "curr_std", "curr_count"]

        hist_daily = self._daily_agg(historical, kpi_name, valid_cols)
        if not hist_daily.empty:
            hist_daily.columns = valid_cols + ["hist_mean", "hist_std", "hist_count"]
        else:
            hist_daily = pd.DataFrame(columns=valid_cols + ["hist_mean", "hist_std", "hist_count"])

        curr_total = current.groupby(valid_cols)[kpi_name].sum().reset_index()
        curr_total.columns = valid_cols + ["curr_sum"]

        hist_total = historical.groupby(valid_cols)[kpi_name].sum().reset_index()
        hist_total.columns = valid_cols + ["hist_sum"]

        merged = pd.merge(curr_daily, hist_daily, on=valid_cols, how="outer").fillna(0)
        merged = pd.merge(merged, curr_total, on=valid_cols, how="outer").fillna(0)
        merged = pd.merge(merged, hist_total, on=valid_cols, how="outer").fillna(0)
        merged["hist_std"] = merged["hist_std"].replace(0, 1e-9)

        curr_n_days = current["date"].nunique()

        total_curr_daily = merged["curr_mean"].sum()
        total_hist_daily = merged["hist_mean"].sum()
        total_daily_dev = total_curr_daily - total_hist_daily
        total_dev = total_daily_dev * curr_n_days

        merged["deviation"] = (merged["curr_mean"] - merged["hist_mean"]) * curr_n_days
        merged["deviation_pct"] = ((merged["curr_mean"] - merged["hist_mean"]) / merged["hist_mean"].replace(0, 1e-9)) * 100

        ref_dev = total_daily_dev if total_daily_dev != 0 else parent_total_dev
        merged["contribution"] = ((merged["curr_mean"] - merged["hist_mean"]) / ref_dev * 100) if ref_dev and ref_dev != 0 else 0

        merged["z_score"] = (merged["curr_mean"] - merged["hist_mean"]) / merged["hist_std"]

        merged = merged.sort_values("contribution", key=abs, ascending=False).reset_index(drop=True)

        if len(valid_cols) == 1:
            merged["dimension_name"] = valid_cols[0]
            merged["label"] = merged[valid_cols[0]].astype(str)
        else:
            merged["dimension_name"] = "+".join(valid_cols)
            merged["label"] = merged.apply(
                lambda r: " & ".join([f"{d}={r[d]}" for d in valid_cols]), axis=1
            )

        return merged, total_dev

    def _is_priority(self, group_cols):
        gc_tuple = tuple(group_cols)
        for pc in self.priority_combos:
            if set(gc_tuple) == set(pc):
                return True
            if len(gc_tuple) >= len(pc) and set(pc).issubset(set(gc_tuple)):
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

    def _analyze_cross_n(self, current, historical, kpi_name, dims, top_n_per_group=3, parent_total_dev=None):
        if any(d not in current.columns for d in dims):
            return pd.DataFrame()

        merged, _ = self._compute_metrics(current, historical, kpi_name, list(dims), parent_total_dev)
        if merged.empty:
            return pd.DataFrame()

        top = merged.head(top_n_per_group * 5).copy()
        results = []
        for _, row in top.iterrows():
            direction = "下降" if row["deviation"] < 0 else "上升"
            row_dict = {
                "dimension_combo": row["label"],
                "curr_sum": round(row["curr_sum"], 2),
                "hist_sum": round(row["hist_sum"], 2),
                "curr_mean": round(row["curr_mean"], 2),
                "hist_mean": round(row["hist_mean"], 2),
                "deviation": round(row["deviation"], 2),
                "deviation_pct": round(row["deviation_pct"], 2),
                "contribution": round(row["contribution"], 2),
                "z_score": round(row["z_score"], 2),
                "direction": direction,
                "is_priority_combo": self._is_priority(list(dims)),
                "layer_dims": list(dims),
                "n_dims": len(dims),
            }
            for i, d in enumerate(dims):
                row_dict[f"dim{i+1}"] = d
                row_dict[f"dim{i+1}_value"] = row[d]
            results.append(row_dict)
        return pd.DataFrame(results)

    def _analyze_drilldown_layer(self, current, historical, kpi_name, layer_dims, parent_filter_top_n=3,
                                  parent_total_dev=None):
        if len(layer_dims) < 3:
            return pd.DataFrame()
        if any(d not in current.columns for d in layer_dims):
            return pd.DataFrame()

        parent_keys = list(layer_dims[:-1])

        parent_df, _ = self._compute_metrics(current, historical, kpi_name, parent_keys, parent_total_dev)
        top_parents = parent_df.head(parent_filter_top_n)

        all_rows = []
        for _, parent_row in top_parents.iterrows():
            curr_filter = pd.Series(True, index=current.index)
            hist_filter = pd.Series(True, index=historical.index)
            for d in parent_keys:
                curr_filter &= (current[d] == parent_row[d])
                hist_filter &= (historical[d] == parent_row[d])

            curr_filtered = current[curr_filter].copy()
            hist_filtered = historical[hist_filter].copy()

            if curr_filtered.empty and hist_filtered.empty:
                continue

            sub_df, _ = self._compute_metrics(
                curr_filtered, hist_filtered, kpi_name, list(layer_dims), parent_total_dev
            )

            for _, row in sub_df.head(5).iterrows():
                direction = "下降" if row["deviation"] < 0 else "上升"
                parent_label = " & ".join([f"{d}={parent_row[d]}" for d in parent_keys])
                all_rows.append({
                    "dimension_combo": row["label"],
                    "layer_dims": list(layer_dims),
                    "n_dims": len(layer_dims),
                    "parent_combo": parent_label,
                    "curr_sum": round(row["curr_sum"], 2),
                    "hist_sum": round(row["hist_sum"], 2),
                    "deviation": round(row["deviation"], 2),
                    "deviation_pct": round(row["deviation_pct"], 2),
                    "contribution_in_parent": round(row["contribution"], 2),
                    "z_score": round(row["z_score"], 2),
                    "direction": direction,
                    "is_priority_combo": self._is_priority(list(layer_dims)),
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
            cross_df = self._analyze_cross_n(current, historical, kpi_name, [dim1, dim2], top_n_per_group=top_n)
            if not cross_df.empty:
                two_dim_frames.append(cross_df)

        cross_df = pd.concat(two_dim_frames, ignore_index=True) if two_dim_frames else pd.DataFrame()
        if not cross_df.empty:
            cross_df["rank_weight"] = cross_df["is_priority_combo"].astype(int) * 0.2
            cross_df["sorted_score"] = cross_df["contribution"].abs() + cross_df["rank_weight"]
            cross_df = cross_df.sort_values("sorted_score", ascending=False).drop(columns=["sorted_score", "rank_weight"]).reset_index(drop=True)

        deeper_frames = []
        for layer in self.drilldown_layers:
            if len(layer) < 3:
                continue
            if any(d not in df.columns for d in layer):
                continue
            layer_df = self._analyze_drilldown_layer(
                current, historical, kpi_name, layer, parent_filter_top_n=3
            )
            if not layer_df.empty:
                deeper_frames.append(layer_df)

        deeper_df = pd.concat(deeper_frames, ignore_index=True) if deeper_frames else pd.DataFrame()
        if not deeper_df.empty:
            deeper_df = deeper_df.sort_values("contribution_in_parent", key=abs, ascending=False).reset_index(drop=True)

        return single_dim_results, cross_df, deeper_df
