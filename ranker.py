import pandas as pd
import numpy as np


class RootCauseRanker:
    def __init__(self, z_threshold=2.0, normalization_threshold=0.3):
        self.z_threshold = z_threshold
        self.normalization_threshold = normalization_threshold

    @classmethod
    def from_config(cls, kpi_name, config):
        analysis_cfg = config.get("analysis", {})
        z_threshold = analysis_cfg.get("z_threshold", 2.0)
        default_norm = analysis_cfg.get("normalization_threshold", 0.3)

        kpi_list = config.get("kpi_list", [])
        kpi_cfg = next((k for k in kpi_list if k["name"] == kpi_name), {})
        normalization_threshold = kpi_cfg.get("normalization_threshold", default_norm)

        return cls(z_threshold=z_threshold, normalization_threshold=normalization_threshold)

    def _direction_normalize(self, contribution, overall_deviation, deviation):
        if overall_deviation > 0:
            target_direction = 1
        elif overall_deviation < 0:
            target_direction = -1
        else:
            return abs(contribution)

        direction_match = (deviation > 0 and target_direction > 0) or (deviation < 0 and target_direction < 0)

        if overall_deviation < 0:
            if contribution < 0:
                normalized = abs(contribution)
            else:
                normalized = max(0, 100 - contribution)
        else:
            if contribution > 0:
                normalized = contribution
            else:
                normalized = max(0, 100 - abs(contribution))

        if not direction_match:
            normalized *= self.normalization_threshold

        return normalized

    def _rank_candidates(self, rows, overall_deviation, extra_fields_fn=None):
        candidates = []
        overall_dev_sign = 1 if overall_deviation >= 0 else -1

        for row_data in rows:
            if isinstance(row_data, dict):
                contribution = row_data.get("contribution", row_data.get("contribution_in_parent", 0))
                z_score = row_data["z_score"]
                deviation = row_data["deviation"]
                deviation_pct = row_data.get("deviation_pct", 0)
                raw_row = row_data
            else:
                contribution = row_data["contribution"]
                z_score = row_data["z_score"]
                deviation = row_data["deviation"]
                deviation_pct = row_data["deviation_pct"]
                raw_row = row_data

            is_significant = abs(z_score) > self.z_threshold

            direction_match = (deviation > 0 and overall_dev_sign > 0) or (deviation < 0 and overall_dev_sign < 0)
            if deviation == 0:
                direction_match = False

            normalized_contribution = self._direction_normalize(contribution, overall_deviation, deviation)

            consistency_score = self._consistency_score(normalized_contribution, abs(z_score))
            magnitude_score = min(normalized_contribution / 30.0, 1.0)
            z_score_norm = min(abs(z_score) / 5.0, 1.0)

            direction_bonus = 0.15 if direction_match else 0.0

            extra_bonus = 0.0
            if extra_fields_fn:
                extra_bonus = extra_fields_fn(raw_row, direction_match)

            confidence = self._compute_confidence(
                normalized_contribution, z_score, consistency_score, magnitude_score, is_significant, direction_bonus + extra_bonus
            )

            direction = "下降" if deviation < 0 else "上升"

            candidate = {
                "rank": 0,
                "deviation": round(deviation, 2),
                "deviation_pct": round(deviation_pct, 2),
                "contribution_pct": round(contribution, 2),
                "normalized_contribution": round(normalized_contribution, 2),
                "z_score": round(z_score, 2),
                "direction": direction,
                "direction_match": direction_match,
                "is_significant": is_significant,
                "normalization_threshold": self.normalization_threshold,
                "confidence": round(confidence, 4),
            }

            if extra_fields_fn:
                extra = extra_fields_fn(raw_row, direction_match, result_only=True)
                candidate.update(extra)

            candidates.append(candidate)

        candidates.sort(key=lambda x: (x["confidence"], x["normalized_contribution"]), reverse=True)
        for i, c in enumerate(candidates, 1):
            c["rank"] = i

        return candidates

    def rank_single_dimensions(self, single_dim_results, overall_deviation):
        def single_extra(row, direction_match, result_only=False):
            if result_only:
                return {
                    "dimension": row.get("dimension_name", row.get("dimension", "")),
                    "value": row.get("label", row.get("value", "")),
                    "label": row.get("label", f"{row.get('dimension_name', '')}={row.get('label', '')}"),
                }
            return 0.0

        all_rows = []
        for dim_name, result in single_dim_results.items():
            df = result["data"]
            for _, row in df.iterrows():
                row_dict = {
                    "contribution": row["contribution"],
                    "z_score": row["z_score"],
                    "deviation": row["deviation"],
                    "deviation_pct": row["deviation_pct"],
                    "dimension_name": dim_name,
                    "label": f"{dim_name}={row[dim_name]}",
                    "value": row[dim_name],
                }
                all_rows.append(row_dict)

        return self._rank_candidates(all_rows, overall_deviation, single_extra)

    def rank_cross_dimensions(self, cross_df, overall_deviation):
        if cross_df.empty:
            return []

        def cross_extra(row, direction_match, result_only=False):
            if result_only:
                return {
                    "dimension_combo": row.get("dimension_combo", ""),
                    "curr_sum": row.get("curr_sum", 0),
                    "hist_sum": row.get("hist_sum", 0),
                    "is_priority_combo": row.get("is_priority_combo", False),
                }
            is_priority = row.get("is_priority_combo", False)
            return 0.08 if is_priority else 0.0

        all_rows = []
        for _, row in cross_df.iterrows():
            all_rows.append(row.to_dict())

        return self._rank_candidates(all_rows, overall_deviation, cross_extra)

    def rank_three_dimensions(self, three_dim_df, overall_deviation):
        if three_dim_df.empty:
            return []

        def three_extra(row, direction_match, result_only=False):
            if result_only:
                return {
                    "dimension_combo": row.get("dimension_combo", ""),
                    "parent_combo": row.get("parent_combo", ""),
                    "contribution_in_parent_pct": row.get("contribution_in_parent", row.get("contribution_in_parent_pct", 0)),
                    "is_priority_combo": row.get("is_priority_combo", False),
                }
            return 0.05

        all_rows = []
        for _, row in three_dim_df.iterrows():
            all_rows.append(row.to_dict())

        return self._rank_candidates(all_rows, overall_deviation, three_extra)

    def _compute_confidence(self, contribution, z_score, consistency, magnitude, is_significant, extra_bonus=0.0):
        z_norm = min(abs(z_score) / 5.0, 1.0)
        contrib_norm = min(abs(contribution) / 50.0, 1.0)

        raw = (0.35 * contrib_norm + 0.30 * z_norm + 0.20 * consistency
               + 0.10 * magnitude + 0.05 * float(is_significant) + extra_bonus)
        return min(raw, 1.0)

    def _consistency_score(self, contribution, z_abs):
        if contribution == 0 or z_abs == 0:
            return 0.0
        contrib_norm = min(abs(contribution) / 50.0, 1.0)
        z_norm = min(z_abs / 5.0, 1.0)
        harmonic = 2 * contrib_norm * z_norm / (contrib_norm + z_norm + 1e-9)
        return harmonic

    def generate_root_causes(self, single_dim_results, cross_df, overall_summary, three_dim_df=None):
        overall_deviation = overall_summary.get("overall_deviation", 0)

        single_candidates = self.rank_single_dimensions(single_dim_results, overall_deviation)
        cross_candidates = self.rank_cross_dimensions(cross_df, overall_deviation)
        three_candidates = []
        if three_dim_df is not None and not three_dim_df.empty:
            three_candidates = self.rank_three_dimensions(three_dim_df, overall_deviation)

        return {
            "single_dimension_causes": single_candidates[:10],
            "cross_dimension_causes": cross_candidates[:10],
            "three_dimension_causes": three_candidates[:10],
        }
