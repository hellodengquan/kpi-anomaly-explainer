import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import setup
from detector import AnomalyDetector
from analyzer import DimensionAnalyzer
from ranker import RootCauseRanker
from reporter import ReportGenerator, load_config


def run_analysis_for_kpi(kpi_name, config, db_path=None):
    analysis_cfg = config.get("analysis", {})
    window_size = analysis_cfg.get("window_size", 7)

    print(f"  [1/4] 异常检测 (STL)...")
    detector = AnomalyDetector.from_config(kpi_name, config, db_path=db_path)
    current_df, historical_df, overall_summary = detector.get_current_window(kpi_name)

    print(f"  [2/4] 维度下钻分析...")
    analyzer = DimensionAnalyzer(db_path=db_path, window_size=window_size, config=config)
    single_dim_results, cross_df, three_dim_df = analyzer.deep_dive(kpi_name)

    for dim_name, result in single_dim_results.items():
        top = result["data"].iloc[0] if not result["data"].empty else None
        if top is not None:
            print(f"    {dim_name} 最大贡献: {top[dim_name]}, 贡献度={top['contribution']:.2f}%")

    print(f"  [3/4] 根因排序...")
    ranker = RootCauseRanker.from_config(kpi_name, config)
    root_causes = ranker.generate_root_causes(
        single_dim_results, cross_df, overall_summary, three_dim_df
    )

    top_single = root_causes["single_dimension_causes"][0] if root_causes["single_dimension_causes"] else None
    top_cross = root_causes["cross_dimension_causes"][0] if root_causes["cross_dimension_causes"] else None
    if top_single:
        print(f"    Top-1 单维度根因: {top_single['label']}, 置信度={top_single['confidence']:.4f}")
    if top_cross:
        print(f"    Top-1 交叉维度根因: {top_cross['dimension_combo']}, 置信度={top_cross['confidence']:.4f}")

    return {
        "kpi_name": kpi_name,
        "overall_summary": overall_summary,
        "current_df": current_df,
        "single_dim_results": single_dim_results,
        "cross_df": cross_df,
        "three_dim_df": three_dim_df,
        "root_causes": root_causes,
    }


def run(kpi_name=None, db_path=None, generate_multi_report=True, tz_label=None):
    config = load_config()

    print("[1/5] 初始化数据库...")
    setup(db_path)

    kpi_list_cfg = config.get("kpi_list", [])
    if kpi_name:
        target_kpis = [k for k in kpi_list_cfg if k["name"] == kpi_name]
        if not target_kpis:
            print(f"未在配置中找到 KPI: {kpi_name}，使用所有 KPI")
            target_kpis = kpi_list_cfg
    else:
        target_kpis = [k for k in kpi_list_cfg if k.get("primary", False)]
        if not target_kpis:
            target_kpis = kpi_list_cfg

    print(f"[2/5] 将分析 {len(target_kpis)} 个 KPI: {[k['name'] for k in target_kpis]}")

    all_results = {}
    for kpi_cfg in target_kpis:
        kpi_n = kpi_cfg["name"]
        print(f"[3-4/5] 分析 KPI: {kpi_n} ({kpi_cfg.get('display_name', kpi_n)})")
        result = run_analysis_for_kpi(kpi_n, config, db_path)
        all_results[kpi_n] = result

    print("[5/5] 生成报告...")
    reporter = ReportGenerator(config=config, tz_label=tz_label)

    if generate_multi_report and len(all_results) > 1:
        md_path, all_csv_paths = reporter.generate_multi(all_results)
        print(f"\n多指标综合报告已生成: {md_path}")
        for kpi_n, csv_paths in all_csv_paths.items():
            print(f"\n  KPI: {kpi_n}")
            for name, path in csv_paths.items():
                print(f"    CSV ({name}): {path}")
    else:
        first_kpi = list(all_results.keys())[0]
        r = all_results[first_kpi]
        md_path, csv_paths = reporter.generate(
            r["overall_summary"],
            r["current_df"],
            r["single_dim_results"],
            r["cross_df"],
            r["root_causes"],
            r.get("three_dim_df"),
            first_kpi
        )
        print(f"\n报告已生成: {md_path}")
        for name, path in csv_paths.items():
            print(f"  CSV ({name}): {path}")

    return md_path, all_results


def main():
    parser = argparse.ArgumentParser(description="KPI 异常解释器")
    parser.add_argument("--kpi", type=str, default=None, help="指定分析的 KPI 名称（默认分析所有 primary KPI）")
    parser.add_argument("--tz", type=str, default=None, help="时区标签，如 CST/JST/PST/UTC 或 +08:00 格式")
    parser.add_argument("--db", type=str, default=None, help="数据库文件路径")
    parser.add_argument("--single", action="store_true", help="仅生成单指标报告（不生成多指标综合报告）")
    args = parser.parse_args()

    run(
        kpi_name=args.kpi,
        db_path=args.db,
        generate_multi_report=not args.single,
        tz_label=args.tz,
    )


if __name__ == "__main__":
    main()
