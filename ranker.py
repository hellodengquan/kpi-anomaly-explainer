import pandas as pd
import numpy as np


class RootCauseRanker:
    def __init__(self, z_threshold=2.0):
        self.z_threshold = z_threshold

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
            normalized *= 0.3

        return normalized

    def rank_single_dimensions(self, single_dim_results, overall_deviation):
        candidates = []
        overall_dev_sign = 1 if overall_deviation >= 0 else -1

        for dim_name, result in single_dim_results.items():
            df = result["data"]
            for _, row in df.iterrows():
                deviation = row["deviation"]
                contribution = row["contribution"]
                z_score = row["z_score"]
                deviation_pct = row["deviation_pct"]

                is_significant = abs(z_score) > self.z_threshold

                direction_match = (deviation > 0 and overall_dev_sign > 0) or (deviation < 0 and overall_dev_sign < 0)
                if deviation == 0:
                    direction_match = False

                normalized_contribution = self._direction_normalize(contribution, overall_deviation, deviation)

                consistency_score = self._consistency_score(normalized_contribution, abs(z_score))
                magnitude_score = min(normalized_contribution / 50.0, 1.0)
                z_score_norm = min(abs(z_score) / 5.0, 1.0)

                direction_bonus = 0.15 if direction_match else 0.0

                confidence = self._compute_confidence(
                    normalized_contribution, z_score, consistency_score, magnitude_score, is_significant, direction_bonus
                )

                direction = "下降" if deviation < 0 else "上升"

                candidates.append({
                    "rank": 0,
                    "dimension": dim_name,
                    "value": row[dim_name],
                    "label": f"{dim_name}={row[dim_name]}",
                    "deviation": round(deviation, 2),
                    "deviation_pct": round(deviation_pct, 2),
                    "contribution_pct": round(contribution, 2),
                    "normalized_contribution": round(normalized_contribution, 2),
                    "z_score": round(z_score, 2),
                    "direction": direction,
                    "direction_match": direction_match,
                    "is_significant": is_significant,
                    "consistency_score": round(consistency_score, 4),
                    "magnitude_score": round(magnitude_score, 4),
                    "confidence": round(confidence, 4),
                })

        candidates.sort(key=lambda x: (x["confidence"], x["normalized_contribution"]), reverse=True)
        for i, c in enumerate(candidates, 1):
            c["rank"] = i

        return candidates

    def rank_cross_dimensions(self, cross_df, overall_deviation):
        if cross_df.empty:
            return []

        candidates = []
        overall_dev_sign = 1 if overall_deviation >= 0 else -1

        for _, row in cross_df.iterrows():
            contribution = row["contribution"]
            z_score = row["z_score"]
            deviation = row["deviation"]

            is_significant = abs(z_score) > self.z_threshold

            direction_match = (deviation > 0 and overall_dev_sign > 0) or (deviation < 0 and overall_dev_sign < 0)
            if deviation == 0:
                direction_match = False

            normalized_contribution = self._direction_normalize(contribution, overall_deviation, deviation)

            is_priority = row.get("is_priority_combo", False)
            priority_bonus = 0.08 if is_priority else 0.0

            magnitude_score = min(normalized_contribution / 30.0, 1.0)
            z_score_norm = min(abs(z_score) / 5.0, 1.0)
            consistency_score = (magnitude_score + z_score_norm) / 2.0

            direction_bonus = 0.12 if direction_match else 0.0

            confidence = self._compute_confidence(
                normalized_contribution, z_score, consistency_score, magnitude_score, is_significant, direction_bonus + priority_bonus
            )

            direction = "下降" if deviation < 0 else "上升"

            candidates.append({
                "rank": 0,
                "dimension_combo": row["dimension_combo"],
                "curr_sum": row["curr_sum"],
                "hist_sum": row["hist_sum"],
                "deviation": row["deviation"],
                "deviation_pct": row.get("deviation_pct", 0),
                "contribution_pct": contribution,
                "normalized_contribution": round(normalized_contribution, 2),
                "z_score": z_score,
                "direction": direction,
                "direction_match": direction_match,
                "is_significant": is_significant,
                "is_priority_combo": is_priority,
                "confidence": round(confidence, 4),
            })

        candidates.sort(key=lambda x: (x["confidence"], x["normalized_contribution"]), reverse=True)
        for i, c in enumerate(candidates, 1):
            c["rank"] = i

        return candidates

    def rank_three_dimensions(self, three_dim_df, overall_deviation):
        if three_dim_df.empty:
            return []

        candidates = []
        overall_dev_sign = 1 if overall_deviation >= 0 else -1

        for _, row in three_dim_df.iterrows():
            contribution = row["contribution_in_parent"]
            z_score = row["z_score"]
            deviation = row["deviation"]

            is_significant = abs(z_score) > self.z_threshold

            direction_match = (deviation > 0 and overall_dev_sign > 0) or (deviation < 0 and overall_dev_sign < 0)

            normalized_contribution = self._direction_normalize(contribution, overall_deviation, deviation)

            magnitude_score = min(normalized_contribution / 30.0, 1.0)
            z_score_norm = min(abs(z_score) / 5.0, 1.0)
            consistency_score = (magnitude_score + z_score_norm) / 2.0

            direction_bonus = 0.12 if direction_match else 0.0
            depth_bonus = 0.05

            confidence = self._compute_confidence(
                normalized_contribution, z_score, consistency_score, magnitude_score, is_significant, direction_bonus + depth_bonus
            )

            direction = "下降" if deviation < 0 else "上升"

            candidates.append({
                "rank": 0,
                "dimension_combo": row["dimension_combo"],
                "parent_combo": row["parent_combo"],
                "curr_sum": row["curr_sum"],
                "hist_sum": row["hist_sum"],
                "deviation": row["deviation"],
                "deviation_pct": row["deviation_pct"],
                "contribution_in_parent_pct": row["contribution_in_parent"],
                "normalized_contribution": round(normalized_contribution, 2),
                "z_score": z_score,
                "direction": direction,
                "direction_match": direction_match,
                "is_significant": is_significant,
                "confidence": round(confidence, 4),
            })

        candidates.sort(key=lambda x: (x["confidence"], x["normalized_contribution"]), reverse=True)
        for i, c in enumerate(candidates, 1):
            c["rank"] = i

        return candidates

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
