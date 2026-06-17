import pandas as pd
import numpy as np


class RootCauseRanker:
    def __init__(self, z_threshold=2.0):
        self.z_threshold = z_threshold

    def rank_single_dimensions(self, single_dim_results, overall_deviation):
        candidates = []

        for dim_name, result in single_dim_results.items():
            df = result["data"]
            for _, row in df.iterrows():
                deviation = row["deviation"]
                contribution = row["contribution"]
                z_score = row["z_score"]
                deviation_pct = row["deviation_pct"]

                is_significant = abs(z_score) > self.z_threshold
                consistency_score = self._consistency_score(contribution, abs(z_score))
                magnitude_score = min(abs(contribution) / 50.0, 1.0)
                z_score_norm = min(abs(z_score) / 5.0, 1.0)

                confidence = self._compute_confidence(
                    contribution, z_score, consistency_score, magnitude_score, is_significant
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
                    "z_score": round(z_score, 2),
                    "direction": direction,
                    "is_significant": is_significant,
                    "consistency_score": round(consistency_score, 4),
                    "magnitude_score": round(magnitude_score, 4),
                    "confidence": round(confidence, 4),
                })

        candidates.sort(key=lambda x: x["confidence"], reverse=True)
        for i, c in enumerate(candidates, 1):
            c["rank"] = i

        return candidates

    def rank_cross_dimensions(self, cross_df):
        if cross_df.empty:
            return []

        candidates = []
        for _, row in cross_df.iterrows():
            contribution = row["contribution"]
            z_score = row["z_score"]

            is_significant = abs(z_score) > self.z_threshold
            magnitude_score = min(abs(contribution) / 30.0, 1.0)
            z_score_norm = min(abs(z_score) / 5.0, 1.0)
            consistency_score = (magnitude_score + z_score_norm) / 2.0

            confidence = self._compute_confidence(
                contribution, z_score, consistency_score, magnitude_score, is_significant
            )

            direction = "下降" if row["deviation"] < 0 else "上升"

            candidates.append({
                "rank": 0,
                "dimension_combo": row["dimension_combo"],
                "curr_sum": row["curr_sum"],
                "hist_sum": row["hist_sum"],
                "deviation": row["deviation"],
                "contribution_pct": contribution,
                "z_score": z_score,
                "direction": direction,
                "is_significant": is_significant,
                "confidence": round(confidence, 4),
            })

        candidates.sort(key=lambda x: x["confidence"], reverse=True)
        for i, c in enumerate(candidates, 1):
            c["rank"] = i

        return candidates

    def _compute_confidence(self, contribution, z_score, consistency, magnitude, is_significant):
        z_norm = min(abs(z_score) / 5.0, 1.0)
        contrib_norm = min(abs(contribution) / 50.0, 1.0)

        raw = 0.35 * contrib_norm + 0.30 * z_norm + 0.20 * consistency + 0.10 * magnitude + 0.05 * float(is_significant)
        return min(raw, 1.0)

    def _consistency_score(self, contribution, z_abs):
        if contribution == 0 or z_abs == 0:
            return 0.0
        contrib_norm = min(abs(contribution) / 50.0, 1.0)
        z_norm = min(z_abs / 5.0, 1.0)
        harmonic = 2 * contrib_norm * z_norm / (contrib_norm + z_norm + 1e-9)
        return harmonic

    def generate_root_causes(self, single_dim_results, cross_df, overall_summary):
        single_candidates = self.rank_single_dimensions(
            single_dim_results, overall_summary.get("overall_deviation", 0)
        )
        cross_candidates = self.rank_cross_dimensions(cross_df)

        return {
            "single_dimension_causes": single_candidates[:10],
            "cross_dimension_causes": cross_candidates[:10],
        }
