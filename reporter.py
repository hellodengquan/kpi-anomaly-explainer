import os
import re
import yaml
import pandas as pd
from datetime import datetime


DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kpi_config.yaml")

TIMEZONE_MAP_BUILTIN = {
    "CST": "+08:00",
    "JST": "+09:00",
    "PST": "-08:00",
    "EST": "-05:00",
    "UTC": "+00:00",
    "CET": "+01:00",
    "IST": "+05:30",
    "KST": "+09:00",
    "AEST": "+10:00",
    "NST": "+12:00",
    "Asia/Shanghai": "+08:00",
    "Asia/Beijing": "+08:00",
    "Asia/Tokyo": "+09:00",
    "Asia/Seoul": "+09:00",
    "Asia/Singapore": "+08:00",
    "Asia/Kolkata": "+05:30",
    "Asia/Dubai": "+04:00",
    "Asia/Hong_Kong": "+08:00",
    "Asia/Taipei": "+08:00",
    "America/Los_Angeles": "-08:00",
    "America/New_York": "-05:00",
    "America/Chicago": "-06:00",
    "America/Denver": "-07:00",
    "America/Sao_Paulo": "-03:00",
    "Europe/London": "+00:00",
    "Europe/Paris": "+01:00",
    "Europe/Berlin": "+01:00",
    "Europe/Moscow": "+03:00",
    "Australia/Sydney": "+10:00",
    "Pacific/Auckland": "+12:00",
    "America/Indiana/Marengo": "-05:00",
    "America/Indiana/Knox": "-06:00",
    "America/Indiana/Petersburg": "-05:00",
    "America/Indiana/Vevay": "-05:00",
    "America/Indiana/Vincennes": "-05:00",
    "America/Indiana/Winamac": "-05:00",
    "America/Kentucky/Louisville": "-05:00",
    "America/Kentucky/Monticello": "-05:00",
    "America/North_Dakota/Beulah": "-06:00",
    "America/North_Dakota/Center": "-06:00",
    "America/North_Dakota/New_Salem": "-06:00",
}

EDGE_DST_TIMEZONES = {
    "America/Indiana/Marengo",
    "America/Indiana/Knox",
    "America/Indiana/Petersburg",
    "America/Indiana/Vevay",
    "America/Indiana/Vincennes",
    "America/Indiana/Winamac",
    "America/Kentucky/Louisville",
    "America/Kentucky/Monticello",
    "America/North_Dakota/Beulah",
    "America/North_Dakota/Center",
    "America/North_Dakota/New_Salem",
}

OFFSET_PATTERN = re.compile(r"^[+-]\d{2}:\d{2}$")


def load_config(config_path=None):
    path = config_path or DEFAULT_CONFIG_PATH
    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config


def resolve_timezone(tz_label, config=None):
    if not tz_label:
        cfg = config or {}
        tz_label = cfg.get("output", {}).get("default_timezone", "Asia/Shanghai")

    if OFFSET_PATTERN.match(tz_label):
        return tz_label

    if config:
        custom_map = config.get("timezone_map", {})
        if tz_label in custom_map:
            return custom_map[tz_label]

    if tz_label in TIMEZONE_MAP_BUILTIN:
        return TIMEZONE_MAP_BUILTIN[tz_label]

    try:
        from zoneinfo import ZoneInfo
        from datetime import timezone as dt_timezone
        tz = ZoneInfo(tz_label)
        now = datetime.now(tz)
        offset = now.utcoffset()
        if offset is not None:
            total_seconds = int(offset.total_seconds())
            hours = total_seconds // 3600
            minutes = abs((total_seconds % 3600) // 60)
            sign = "+" if hours >= 0 else "-"
            return f"{sign}{abs(hours):02d}:{minutes:02d}"
    except Exception:
        pass

    return "+00:00"


class ReportGenerator:
    def __init__(self, output_dir=None, config=None, config_path=None, tz_label=None):
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self.config = config or load_config(self.config_path)
        self.output_dir = output_dir or os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            self.config.get("output", {}).get("report_dir", "output")
        )
        self.tz_label = tz_label or self.config.get("output", {}).get("default_timezone", "Asia/Shanghai")
        self.timezone_offset = resolve_timezone(self.tz_label, self.config)
        self.csv_encoding = self.config.get("output", {}).get("csv_encoding", "utf-8-sig")
        self.kpi_meta = {k["name"]: k for k in self.config.get("kpi_list", [])}
        os.makedirs(self.output_dir, exist_ok=True)

    def reload_config(self, new_config=None, new_tz_label=None):
        if new_config is None:
            new_config = load_config(self.config_path)
        self.config = new_config
        if new_tz_label:
            self.tz_label = new_tz_label
        else:
            self.tz_label = new_config.get("output", {}).get("default_timezone", self.tz_label)
        self.timezone_offset = resolve_timezone(self.tz_label, new_config)
        self.csv_encoding = new_config.get("output", {}).get("csv_encoding", self.csv_encoding)
        self.kpi_meta = {k["name"]: k for k in new_config.get("kpi_list", [])}
        self.output_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            new_config.get("output", {}).get("report_dir", self.output_dir)
        )
        os.makedirs(self.output_dir, exist_ok=True)
        return {
            "tz_label": self.tz_label,
            "timezone_offset": self.timezone_offset,
            "csv_encoding": self.csv_encoding,
            "kpi_count": len(self.kpi_meta),
            "output_dir": self.output_dir,
        }

    def get_config_snapshot(self):
        return {
            "tz_label": self.tz_label,
            "timezone_offset": self.timezone_offset,
            "csv_encoding": self.csv_encoding,
            "kpi_count": len(self.kpi_meta),
            "output_dir": self.output_dir,
            "config_path": self.config_path,
        }

    @staticmethod
    def resolve_tz(tz_label, config=None):
        return resolve_timezone(tz_label, config)

    def _kpi_display(self, kpi_name):
        meta = self.kpi_meta.get(kpi_name, {})
        return meta.get("display_name", kpi_name)

    def _kpi_unit(self, kpi_name):
        meta = self.kpi_meta.get(kpi_name, {})
        return meta.get("unit", "")

    def _format_ts(self, dt_obj):
        if hasattr(dt_obj, "strftime"):
            base = dt_obj.strftime("%Y-%m-%d")
        else:
            base = str(dt_obj)
        return f"{base} {self.timezone_offset}"

    def _format_now_ts(self):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return f"{now} {self.timezone_offset}"

    def generate(self, overall_summary, current_df, single_dim_results, cross_df, root_causes,
                 three_dim_df=None, kpi_name="revenue"):
        md_content = self._build_markdown(overall_summary, current_df, single_dim_results, cross_df, root_causes, three_dim_df, kpi_name)
        safe_kpi = kpi_name.replace("/", "_")
        md_path = os.path.join(self.output_dir, f"{safe_kpi}_anomaly_report.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        csv_paths = self._export_csv(current_df, single_dim_results, cross_df, root_causes, three_dim_df, kpi_name)

        return md_path, csv_paths

    def generate_multi(self, all_results):
        lines = []
        now_ts = self._format_now_ts()
        lines.append("# KPI 异常分析报告（多指标）")
        lines.append("")
        lines.append(f"> 生成时间: {now_ts}")
        lines.append(f"> 时区: {self.tz_label} ({self.timezone_offset})")
        lines.append("")

        lines.append("## 指标概览")
        lines.append("")
        lines.append("| 指标 | 展示名 | 单位 | 判定 | 偏差方向 | 偏差% | 置信度Top-1 |")
        lines.append("|------|------|------|------|------|------|------|")
        for kpi_name, result in all_results.items():
            summary = result["overall_summary"]
            root_causes = result["root_causes"]
            display = self._kpi_display(kpi_name)
            unit = self._kpi_unit(kpi_name)
            anomaly_tag = "⚠️ 异常" if summary.get("is_anomalous") else "✅ 正常"
            direction = summary.get("anomaly_direction", "N/A")
            dev_pct = summary.get("overall_deviation_pct", 0)
            top_cause = root_causes.get("single_dimension_causes", [[]])
            top_label = top_cause[0]["label"] if top_cause else "N/A"
            lines.append(f"| {kpi_name} | {display} | {unit} | {anomaly_tag} | {direction} | {dev_pct:.2f}% | {top_label} |")
        lines.append("")

        for kpi_name, result in all_results.items():
            lines.append(f"---")
            lines.append("")
            lines.append(f"## 详细分析: {self._kpi_display(kpi_name)}")
            lines.append("")
            lines.append(self._build_markdown(
                result["overall_summary"],
                result["current_df"],
                result["single_dim_results"],
                result["cross_df"],
                result["root_causes"],
                result.get("three_dim_df"),
                kpi_name,
                section_offset=1
            ))
            lines.append("")

        md_path = os.path.join(self.output_dir, "kpi_anomaly_report.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        all_csv_paths = {}
        for kpi_name, result in all_results.items():
            csv_paths = self._export_csv(
                result["current_df"],
                result["single_dim_results"],
                result["cross_df"],
                result["root_causes"],
                result.get("three_dim_df"),
                kpi_name
            )
            all_csv_paths[kpi_name] = csv_paths

        return md_path, all_csv_paths

    def _build_markdown(self, overall_summary, current_df, single_dim_results, cross_df, root_causes, three_dim_df, kpi_name, section_offset=0):
        lines = []
        now_ts = self._format_now_ts()
        display = self._kpi_display(kpi_name)
        unit = self._kpi_unit(kpi_name)

        if section_offset == 0:
            lines.append(f"# {display} 异常分析报告")
            lines.append("")
            lines.append(f"> 生成时间: {now_ts}")
            lines.append(f"> 分析指标: {kpi_name} ({display})")
            lines.append(f"> 指标单位: {unit}")
            lines.append(f"> 分析窗口: {overall_summary.get('date_range', 'N/A')} ({self.tz_label} {self.timezone_offset})")
            lines.append(f"> STL 周期: {overall_summary.get('seasonal_period', 'N/A')} 天")
            lines.append("")

        lines.append(f"## {section_offset + 1}. 异常概述")
        lines.append("")
        lines.append("| 指标 | 值 |")
        lines.append("|------|------|")
        lines.append(f"| 当前窗口均值 | {overall_summary.get('current_mean', 'N/A'):,.2f} {unit} |")
        lines.append(f"| 历史均值 | {overall_summary.get('historical_mean', 'N/A'):,.2f} {unit} |")
        lines.append(f"| 历史标准差 | {overall_summary.get('historical_std', 'N/A'):,.2f} {unit} |")
        lines.append(f"| 绝对偏差 | {overall_summary.get('overall_deviation', 'N/A'):,.2f} {unit} |")
        lines.append(f"| 相对偏差 | {overall_summary.get('overall_deviation_pct', 'N/A'):.2f}% |")
        lines.append(f"| 总体 Z-Score | {overall_summary.get('overall_z_score', 'N/A'):.2f} |")
        if 'stl_residual_mean' in overall_summary:
            lines.append(f"| STL 残差均值 | {overall_summary.get('stl_residual_mean', 'N/A'):,.2f} {unit} |")
            lines.append(f"| STL Z-Score | {overall_summary.get('stl_z_score', 'N/A'):.2f} |")
        lines.append(f"| 异常判定 | {'⚠️ **是**' if overall_summary.get('is_anomalous') else '✅ 否'} |")
        lines.append(f"| 偏差方向 | {overall_summary.get('anomaly_direction', 'N/A')} |")
        lines.append("")

        sub_num = section_offset + 2
        lines.append(f"## {sub_num}. STL 日级趋势")
        lines.append("")
        lines.append("| 日期 | 实际值 | STL预期值 | 季节性分量 | 残差 | 偏差% | Z-Score | 异常 |")
        lines.append("|------|------|------|------|------|------|------|------|")
        for _, row in current_df.iterrows():
            date_str = self._format_ts(row["date"])
            anomaly_tag = "⚠️" if row.get("is_anomaly") else ""
            lines.append(
                f"| {date_str} | {row[kpi_name]:,.2f} | {row['expected']:,.2f} | "
                f"{row['seasonal']:,.2f} | {row['residual']:,.2f} | "
                f"{row['deviation_pct']:.2f}% | {row['z_score']:.2f} | {anomaly_tag} |"
            )
        lines.append("")

        sub_num = section_offset + 3
        lines.append(f"## {sub_num}. 单维度下钻分析")
        lines.append("")
        for dim_idx, (dim_name, result) in enumerate(single_dim_results.items()):
            df = result["data"]
            lines.append(f"### {sub_num}.{dim_idx + 1} 维度: {dim_name}")
            lines.append("")
            lines.append(f"| {dim_name} | 日均当前 | 日均历史 | 偏差 | 偏差% | 贡献度% | Z-Score | 方向 |")
            lines.append(f"|------|------|------|------|------|------|------|------|")
            for _, row in df.iterrows():
                direction = "下降" if row["deviation"] < 0 else "上升"
                lines.append(
                    f"| {row[dim_name]} | {row['curr_mean']:,.2f} | {row['hist_mean']:,.2f} | "
                    f"{row['deviation']:,.2f} | {row['deviation_pct']:.2f}% | "
                    f"{row['contribution']:.2f}% | {row['z_score']:.2f} | {direction} |"
                )
            lines.append("")

        sub_num = section_offset + 4
        lines.append(f"## {sub_num}. 交叉维度分析")
        lines.append("")
        if not cross_df.empty:
            lines.append("| 维度组合 | 窗口合计 | 偏差 | 偏差% | 贡献度% | Z-Score | 方向 | 优先 |")
            lines.append("|------|------|------|------|------|------|------|------|")
            for _, row in cross_df.head(15).iterrows():
                priority_tag = "⭐" if row.get("is_priority_combo") else ""
                lines.append(
                    f"| {row['dimension_combo']} | {row['curr_sum']:,.2f} | "
                    f"{row['deviation']:,.2f} | {row.get('deviation_pct', 0):.2f}% | "
                    f"{row['contribution']:.2f}% | "
                    f"{row['z_score']:.2f} | {row['direction']} | {priority_tag} |"
                )
        else:
            lines.append("无显著交叉维度异常。")
        lines.append("")

        if three_dim_df is not None and not three_dim_df.empty:
            sub_num = section_offset + 5
            lines.append(f"## {sub_num}. 多层深度下钻")
            lines.append("")
            layer_name_map = {}
            for _, r in three_dim_df.iterrows():
                ld = tuple(r.get("layer_dims", []))
                if ld not in layer_name_map:
                    layer_name_map[ld] = " + ".join(ld)
            for ld, name in layer_name_map.items():
                layer_rows = three_dim_df[three_dim_df["layer_dims"].apply(lambda x: tuple(x) == ld)]
                if layer_rows.empty:
                    continue
                lines.append(f"### {sub_num}.1 {name}（{len(ld)}层）")
                lines.append("")
                lines.append("| 维度组合 | 父组合 | 偏差 | 偏差% | 父内贡献% | Z-Score | 方向 |")
                lines.append("|------|------|------|------|------|------|------|")
                for _, row in layer_rows.head(10).iterrows():
                    lines.append(
                        f"| {row['dimension_combo']} | {row['parent_combo']} | "
                        f"{row['deviation']:,.2f} | {row['deviation_pct']:.2f}% | "
                        f"{row['contribution_in_parent']:.2f}% | {row['z_score']:.2f} | {row['direction']} |"
                    )
                lines.append("")

        sub_num_offset = 5 if (three_dim_df is not None and not three_dim_df.empty) else 4
        sub_num = section_offset + sub_num_offset + 1
        lines.append(f"## {sub_num}. 根因排序")
        lines.append("")

        lines.append(f"### {sub_num}.1 单维度根因")
        lines.append("")
        single_causes = root_causes.get("single_dimension_causes", [])
        if single_causes:
            lines.append("| 排名 | 维度 | 标签 | 偏差 | 偏差% | 贡献度% | 归一化贡献% | Z-Score | 方向 | 方向匹配 | 置信度 |")
            lines.append("|------|------|------|------|------|------|------|------|------|------|------|")
            for c in single_causes:
                match_tag = "✓" if c.get("direction_match") else "✗"
                lines.append(
                    f"| {c['rank']} | {c['dimension']} | {c['label']} | {c['deviation']:,.2f} | "
                    f"{c['deviation_pct']:.2f}% | {c['contribution_pct']:.2f}% | {c['normalized_contribution']:.2f}% | "
                    f"{c['z_score']:.2f} | {c['direction']} | {match_tag} | {c['confidence']:.4f} |"
                )
        else:
            lines.append("未检测到显著单维度根因。")
        lines.append("")

        lines.append(f"### {sub_num}.2 交叉维度根因")
        lines.append("")
        cross_causes = root_causes.get("cross_dimension_causes", [])
        if cross_causes:
            lines.append("| 排名 | 维度组合 | 偏差 | 贡献度% | 归一化贡献% | Z-Score | 方向 | 优先 | 置信度 |")
            lines.append("|------|------|------|------|------|------|------|------|------|")
            for c in cross_causes:
                priority_tag = "⭐" if c.get("is_priority_combo") else ""
                lines.append(
                    f"| {c['rank']} | {c['dimension_combo']} | {c['deviation']:,.2f} | "
                    f"{c['contribution_pct']:.2f}% | {c['normalized_contribution']:.2f}% | {c['z_score']:.2f} | "
                    f"{c['direction']} | {priority_tag} | {c['confidence']:.4f} |"
                )
        else:
            lines.append("未检测到显著交叉维度根因。")
        lines.append("")

        three_causes = root_causes.get("three_dimension_causes", [])
        if three_causes:
            lines.append(f"### {sub_num}.3 多层根因")
            lines.append("")
            lines.append("| 排名 | 维度组合 | 父组合 | 偏差 | 父内贡献% | Z-Score | 方向 | 置信度 |")
            lines.append("|------|------|------|------|------|------|------|------|")
            for c in three_causes:
                lines.append(
                    f"| {c['rank']} | {c['dimension_combo']} | {c['parent_combo']} | {c['deviation']:,.2f} | "
                    f"{c['contribution_in_parent_pct']:.2f}% | {c['z_score']:.2f} | {c['direction']} | {c['confidence']:.4f} |"
                )
            lines.append("")

        sub_num += 1
        lines.append(f"## {sub_num}. 结论与建议")
        lines.append("")
        if overall_summary.get("is_anomalous"):
            direction = overall_summary.get("anomaly_direction", "")
            deviation_pct = abs(overall_summary.get("overall_deviation_pct", 0))
            lines.append(f"当前窗口{display} **{direction}** 偏差约 **{deviation_pct:.2f}%**，已被判定为异常。")
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
            if three_causes:
                lines.append("**多层维度嫌疑:**")
                lines.append("")
                for c in three_causes[:3]:
                    lines.append(f"- {c['dimension_combo']} (父: {c['parent_combo']}): {c['direction']}偏差，父内贡献 {abs(c['contribution_in_parent_pct']):.2f}%，置信度 {c['confidence']:.4f}")
                lines.append("")
            lines.append("**建议行动:**")
            lines.append("")
            lines.append("1. 优先排查贡献度最高且置信度最大的维度组合，确认是否存在业务侧变更或外部冲击。")
            lines.append("2. 对比同期的运营活动日志，验证是否存在促销、价格调整等因素。")
            lines.append("3. 如果偏差集中在特定区域/渠道，建议联系相关业务团队进行现场核实。")
        else:
            lines.append(f"当前窗口{display}未检测到显著异常，各项指标均在正常范围内波动。")
        lines.append("")

        lines.append("---")
        lines.append("")
        lines.append(f"*本报告由 KPI 异常解释器自动生成，采用 STL 季节性分解算法 | 时区 {self.tz_label} ({self.timezone_offset})*")

        return "\n".join(lines)

    def _add_timezone_to_df(self, df):
        df = df.copy()
        if "date" in df.columns:
            df["date"] = df["date"].apply(lambda x: self._format_ts(x))
        return df

    def _export_csv(self, current_df, single_dim_results, cross_df, root_causes, three_dim_df, kpi_name):
        csv_paths = {}
        safe_kpi = kpi_name.replace("/", "_")

        trend_path = os.path.join(self.output_dir, f"{safe_kpi}_daily_trend.csv")
        current_ts = self._add_timezone_to_df(current_df)
        current_ts.to_csv(trend_path, index=False, encoding=self.csv_encoding)
        csv_paths["daily_trend"] = trend_path

        all_dim_rows = []
        for dim_name, result in single_dim_results.items():
            df = result["data"].copy()
            all_dim_rows.append(df)
        if all_dim_rows:
            combined = pd.concat(all_dim_rows, ignore_index=True)
            dim_path = os.path.join(self.output_dir, f"{safe_kpi}_dimension_analysis.csv")
            combined.to_csv(dim_path, index=False, encoding=self.csv_encoding)
            csv_paths["dimension_analysis"] = dim_path

        if not cross_df.empty:
            cross_path = os.path.join(self.output_dir, f"{safe_kpi}_cross_dimension_analysis.csv")
            cross_df.to_csv(cross_path, index=False, encoding=self.csv_encoding)
            csv_paths["cross_dimension"] = cross_path

        single_causes = root_causes.get("single_dimension_causes", [])
        if single_causes:
            sc_df = pd.DataFrame(single_causes)
            sc_path = os.path.join(self.output_dir, f"{safe_kpi}_root_causes_single.csv")
            sc_df.to_csv(sc_path, index=False, encoding=self.csv_encoding)
            csv_paths["root_causes_single"] = sc_path

        cross_causes = root_causes.get("cross_dimension_causes", [])
        if cross_causes:
            cc_df = pd.DataFrame(cross_causes)
            cc_path = os.path.join(self.output_dir, f"{safe_kpi}_root_causes_cross.csv")
            cc_df.to_csv(cc_path, index=False, encoding=self.csv_encoding)
            csv_paths["root_causes_cross"] = cc_path

        three_causes = root_causes.get("three_dimension_causes", [])
        if three_causes:
            tc_df = pd.DataFrame(three_causes)
            tc_path = os.path.join(self.output_dir, f"{safe_kpi}_root_causes_multi.csv")
            tc_df.to_csv(tc_path, index=False, encoding=self.csv_encoding)
            csv_paths["root_causes_multi"] = tc_path

        if three_dim_df is not None and not three_dim_df.empty:
            td_path = os.path.join(self.output_dir, f"{safe_kpi}_multi_dimension_drilldown.csv")
            three_dim_df.to_csv(td_path, index=False, encoding=self.csv_encoding)
            csv_paths["multi_dim_drilldown"] = td_path

        return csv_paths
