import os
import pandas as pd
from datetime import datetime


OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")


class ReportGenerator:
    def __init__(self, output_dir=None):
        self.output_dir = output_dir or OUTPUT_DIR
        os.makedirs(self.output_dir, exist_ok=True)

    def generate(self, overall_summary, current_df, single_dim_results, cross_df, root_causes):
        md_content = self._build_markdown(overall_summary, current_df, single_dim_results, cross_df, root_causes)
        md_path = os.path.join(self.output_dir, "kpi_anomaly_report.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        csv_paths = self._export_csv(current_df, single_dim_results, cross_df, root_causes)

        return md_path, csv_paths

    def _build_markdown(self, overall_summary, current_df, single_dim_results, cross_df, root_causes):
        lines = []
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        kpi_name = overall_summary.get("kpi_name", "revenue")

        lines.append("# KPI 异常分析报告")
        lines.append("")
        lines.append(f"> 生成时间: {now}")
        lines.append(f"> 分析指标: {kpi_name}")
        lines.append(f"> 分析窗口: {overall_summary.get('date_range', 'N/A')}")
        lines.append("")

        lines.append("## 1. 异常概述")
        lines.append("")
        lines.append("| 指标 | 值 |")
        lines.append("|------|------|")
        lines.append(f"| 当前窗口均值 | {overall_summary.get('current_mean', 'N/A'):,.2f} |")
        lines.append(f"| 历史均值 | {overall_summary.get('historical_mean', 'N/A'):,.2f} |")
        lines.append(f"| 历史标准差 | {overall_summary.get('historical_std', 'N/A'):,.2f} |")
        lines.append(f"| 绝对偏差 | {overall_summary.get('overall_deviation', 'N/A'):,.2f} |")
        lines.append(f"| 相对偏差 | {overall_summary.get('overall_deviation_pct', 'N/A'):.2f}% |")
        lines.append(f"| Z-Score | {overall_summary.get('overall_z_score', 'N/A'):.2f} |")
        lines.append(f"| 异常判定 | {'⚠️ **是**' if overall_summary.get('is_anomalous') else '✅ 否'} |")
        lines.append(f"| 偏差方向 | {overall_summary.get('anomaly_direction', 'N/A')} |")
        lines.append("")

        lines.append("## 2. 日级趋势")
        lines.append("")
        lines.append("| 日期 | 值 | 滑动均值 | 偏差 | 偏差% | Z-Score | 异常 |")
        lines.append("|------|------|------|------|------|------|------|")
        for _, row in current_df.iterrows():
            date_str = row["date"].strftime("%Y-%m-%d") if hasattr(row["date"], "strftime") else str(row["date"])
            anomaly_tag = "⚠️" if row.get("is_anomaly") else ""
            lines.append(
                f"| {date_str} | {row[kpi_name]:,.2f} | {row['rolling_mean']:,.2f} | "
                f"{row['deviation']:,.2f} | {row['deviation_pct']:.2f}% | "
                f"{row['z_score']:.2f} | {anomaly_tag} |"
            )
        lines.append("")

        lines.append("## 3. 单维度下钻分析")
        lines.append("")
        for dim_name, result in single_dim_results.items():
            df = result["data"]
            lines.append(f"### 3.{list(single_dim_results.keys()).index(dim_name) + 1} 维度: {dim_name}")
            lines.append("")
            lines.append(f"| {dim_name} | 日均当前 | 日均历史 | 偏差 | 偏差% | 贡献度% | Z-Score |")
            lines.append(f"|------|------|------|------|------|------|------|")
            for _, row in df.iterrows():
                lines.append(
                    f"| {row[dim_name]} | {row['curr_mean']:,.2f} | {row['hist_mean']:,.2f} | "
                    f"{row['deviation']:,.2f} | {row['deviation_pct']:.2f}% | "
                    f"{row['contribution']:.2f}% | {row['z_score']:.2f} |"
                )
            lines.append("")

        lines.append("## 4. 交叉维度分析")
        lines.append("")
        if not cross_df.empty:
            lines.append("| 维度组合 | 窗口合计 | 偏差 | 偏差% | 贡献度% | Z-Score | 方向 |")
            lines.append("|------|------|------|------|------|------|------|")
            for _, row in cross_df.head(15).iterrows():
                lines.append(
                    f"| {row['dimension_combo']} | {row['curr_sum']:,.2f} | "
                    f"{row['deviation']:,.2f} | {row.get('deviation_pct', 0):.2f}% | "
                    f"{row['contribution']:.2f}% | "
                    f"{row['z_score']:.2f} | {row['direction']} |"
                )
        else:
            lines.append("无显著交叉维度异常。")
        lines.append("")

        lines.append("## 5. 根因排序")
        lines.append("")

        lines.append("### 5.1 单维度根因")
        lines.append("")
        single_causes = root_causes.get("single_dimension_causes", [])
        if single_causes:
            lines.append("| 排名 | 维度 | 标签 | 偏差 | 偏差% | 贡献度% | Z-Score | 方向 | 置信度 |")
            lines.append("|------|------|------|------|------|------|------|------|------|")
            for c in single_causes:
                lines.append(
                    f"| {c['rank']} | {c['dimension']} | {c['label']} | {c['deviation']:,.2f} | "
                    f"{c['deviation_pct']:.2f}% | {c['contribution_pct']:.2f}% | "
                    f"{c['z_score']:.2f} | {c['direction']} | {c['confidence']:.4f} |"
                )
        else:
            lines.append("未检测到显著单维度根因。")
        lines.append("")

        lines.append("### 5.2 交叉维度根因")
        lines.append("")
        cross_causes = root_causes.get("cross_dimension_causes", [])
        if cross_causes:
            lines.append("| 排名 | 维度组合 | 偏差 | 贡献度% | Z-Score | 方向 | 置信度 |")
            lines.append("|------|------|------|------|------|------|------|")
            for c in cross_causes:
                lines.append(
                    f"| {c['rank']} | {c['dimension_combo']} | {c['deviation']:,.2f} | "
                    f"{c['contribution_pct']:.2f}% | {c['z_score']:.2f} | "
                    f"{c['direction']} | {c['confidence']:.4f} |"
                )
        else:
            lines.append("未检测到显著交叉维度根因。")
        lines.append("")

        lines.append("## 6. 结论与建议")
        lines.append("")
        if overall_summary.get("is_anomalous"):
            direction = overall_summary.get("anomaly_direction", "")
            deviation_pct = abs(overall_summary.get("overall_deviation_pct", 0))
            lines.append(f"当前窗口KPI **{direction}** 偏差约 **{deviation_pct:.2f}%**，已被判定为异常。")
            lines.append("")
            lines.append("**主要嫌疑根因:**")
            lines.append("")
            for c in single_causes[:3]:
                lines.append(f"- {c['label']}: {c['direction']}偏差 {abs(c['deviation_pct']):.2f}%，贡献度 {abs(c['contribution_pct']):.2f}%，置信度 {c['confidence']:.4f}")
            lines.append("")
            if cross_causes:
                lines.append("**交叉维度嫌疑:**")
                lines.append("")
                for c in cross_causes[:3]:
                    lines.append(f"- {c['dimension_combo']}: {c['direction']}偏差，贡献度 {abs(c['contribution_pct']):.2f}%，置信度 {c['confidence']:.4f}")
                lines.append("")
            lines.append("**建议行动:**")
            lines.append("")
            lines.append("1. 优先排查贡献度最高且置信度最大的维度组合，确认是否存在业务侧变更或外部冲击。")
            lines.append("2. 对比同期的运营活动日志，验证是否存在促销、价格调整等因素。")
            lines.append("3. 如果偏差集中在特定区域/渠道，建议联系相关业务团队进行现场核实。")
        else:
            lines.append("当前窗口KPI未检测到显著异常，各项指标均在正常范围内波动。")
        lines.append("")

        lines.append("---")
        lines.append("")
        lines.append("*本报告由 KPI 异常解释器自动生成*")

        return "\n".join(lines)

    def _export_csv(self, current_df, single_dim_results, cross_df, root_causes):
        csv_paths = {}

        trend_path = os.path.join(self.output_dir, "daily_trend.csv")
        current_df.to_csv(trend_path, index=False, encoding="utf-8-sig")
        csv_paths["daily_trend"] = trend_path

        all_dim_rows = []
        for dim_name, result in single_dim_results.items():
            df = result["data"].copy()
            all_dim_rows.append(df)
        if all_dim_rows:
            combined = pd.concat(all_dim_rows, ignore_index=True)
            dim_path = os.path.join(self.output_dir, "dimension_analysis.csv")
            combined.to_csv(dim_path, index=False, encoding="utf-8-sig")
            csv_paths["dimension_analysis"] = dim_path

        if not cross_df.empty:
            cross_path = os.path.join(self.output_dir, "cross_dimension_analysis.csv")
            cross_df.to_csv(cross_path, index=False, encoding="utf-8-sig")
            csv_paths["cross_dimension"] = cross_path

        single_causes = root_causes.get("single_dimension_causes", [])
        if single_causes:
            sc_df = pd.DataFrame(single_causes)
            sc_path = os.path.join(self.output_dir, "root_causes_single.csv")
            sc_df.to_csv(sc_path, index=False, encoding="utf-8-sig")
            csv_paths["root_causes_single"] = sc_path

        cross_causes = root_causes.get("cross_dimension_causes", [])
        if cross_causes:
            cc_df = pd.DataFrame(cross_causes)
            cc_path = os.path.join(self.output_dir, "root_causes_cross.csv")
            cc_df.to_csv(cc_path, index=False, encoding="utf-8-sig")
            csv_paths["root_causes_cross"] = cc_path

        return csv_paths
