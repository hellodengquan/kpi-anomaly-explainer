import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import setup
from detector import AnomalyDetector
from analyzer import DimensionAnalyzer
from ranker import RootCauseRanker
from reporter import ReportGenerator


def run(kpi_name="revenue", window_size=7, z_threshold=2.0, db_path=None):
    print("[1/5] 初始化数据库...")
    setup(db_path)

    print("[2/5] 执行异常检测...")
    detector = AnomalyDetector(window_size=window_size, z_threshold=z_threshold, db_path=db_path)
    current_df, historical_df, overall_summary = detector.get_current_window(kpi_name)

    print(f"  KPI: {kpi_name}")
    print(f"  当前窗口均值: {overall_summary['current_mean']:,.2f}")
    print(f"  历史均值: {overall_summary['historical_mean']:,.2f}")
    print(f"  偏差: {overall_summary['overall_deviation_pct']:.2f}%")
    print(f"  Z-Score: {overall_summary['overall_z_score']:.2f}")
    print(f"  异常判定: {'是' if overall_summary['is_anomalous'] else '否'}")

    print("[3/5] 执行维度下钻分析...")
    analyzer = DimensionAnalyzer(db_path=db_path, window_size=window_size)
    single_dim_results, cross_df = analyzer.deep_dive(kpi_name)

    for dim_name, result in single_dim_results.items():
        top = result["data"].iloc[0] if not result["data"].empty else None
        if top is not None:
            print(f"  {dim_name} 最大贡献: {top[dim_name]}, 贡献度={top['contribution']:.2f}%")

    print("[4/5] 根因排序与置信度计算...")
    ranker = RootCauseRanker(z_threshold=z_threshold)
    root_causes = ranker.generate_root_causes(single_dim_results, cross_df, overall_summary)

    top_cause = root_causes["single_dimension_causes"][0] if root_causes["single_dimension_causes"] else None
    if top_cause:
        print(f"  Top-1 根因: {top_cause['label']}, 置信度={top_cause['confidence']:.4f}")

    print("[5/5] 生成报告...")
    reporter = ReportGenerator()
    md_path, csv_paths = reporter.generate(overall_summary, current_df, single_dim_results, cross_df, root_causes)

    print(f"\n报告已生成:")
    print(f"  Markdown: {md_path}")
    for name, path in csv_paths.items():
        print(f"  CSV ({name}): {path}")

    return md_path, csv_paths


if __name__ == "__main__":
    run()
