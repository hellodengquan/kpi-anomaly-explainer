import os
import sys
import json
import argparse
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import setup
from detector import AnomalyDetector
from analyzer import DimensionAnalyzer
from ranker import RootCauseRanker
from reporter import ReportGenerator, load_config, resolve_timezone


class KpiExplainerService:
    _instance = None
    _lock = threading.Lock()

    def __init__(self, db_path=None, tz_label=None):
        self.db_path = db_path
        self.config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kpi_config.yaml")
        self.config = load_config(self.config_path)
        self.initial_tz = tz_label or self.config.get("output", {}).get("default_timezone", "Asia/Shanghai")
        self.tz_label = self.initial_tz
        self.timezone_offset = resolve_timezone(self.tz_label, self.config)

        self.reporter = ReportGenerator(config=self.config, config_path=self.config_path, tz_label=self.tz_label)

        self.detectors = {}
        self.analyzers = {}
        self.rankers = {}

        self.last_reload_at = datetime.now().isoformat()
        self.run_count = 0
        self.last_run_at = None

    @classmethod
    def get_instance(cls, db_path=None, tz_label=None):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(db_path=db_path, tz_label=tz_label)
        return cls._instance

    def _get_detector(self, kpi_name):
        if kpi_name not in self.detectors:
            with self._lock:
                if kpi_name not in self.detectors:
                    self.detectors[kpi_name] = AnomalyDetector.from_config(kpi_name, self.config, db_path=self.db_path)
        return self.detectors[kpi_name]

    def _get_analyzer(self, kpi_name):
        key = kpi_name
        if key not in self.analyzers:
            with self._lock:
                if key not in self.analyzers:
                    self.analyzers[key] = DimensionAnalyzer(
                        db_path=self.db_path,
                        window_size=self.config.get("analysis", {}).get("window_size", 7),
                        config=self.config,
                    )
        return self.analyzers[key]

    def _get_ranker(self, kpi_name):
        if kpi_name not in self.rankers:
            with self._lock:
                if kpi_name not in self.rankers:
                    self.rankers[kpi_name] = RootCauseRanker.from_config(kpi_name, self.config)
        return self.rankers[kpi_name]

    def reload_all(self, new_tz_label=None):
        with self._lock:
            new_config = load_config(self.config_path)
            self.config = new_config

            if new_tz_label:
                self.tz_label = new_tz_label
            else:
                self.tz_label = self.config.get("output", {}).get("default_timezone", self.tz_label)
            self.timezone_offset = resolve_timezone(self.tz_label, self.config)

            reporter_info = self.reporter.reload_config(new_config, new_tz_label=self.tz_label)

            detector_snapshots = {}
            for kpi_name, det in self.detectors.items():
                info = det.reload_config(new_config, new_kpi_name=kpi_name)
                detector_snapshots[kpi_name] = info

            analyzer_snapshots = {}
            for key, ana in self.analyzers.items():
                info = ana.reload_config(new_config)
                analyzer_snapshots[key] = info

            ranker_snapshots = {}
            for kpi_name, rnk in self.rankers.items():
                info = rnk.reload_config(new_config, new_kpi_name=kpi_name)
                ranker_snapshots[kpi_name] = info

            self.last_reload_at = datetime.now().isoformat()

            return {
                "reloaded_at": self.last_reload_at,
                "tz_label": self.tz_label,
                "timezone_offset": self.timezone_offset,
                "reporter": reporter_info,
                "detectors": detector_snapshots,
                "analyzers": analyzer_snapshots,
                "rankers": ranker_snapshots,
                "kpi_count": len(new_config.get("kpi_list", [])),
            }

    def status(self):
        return {
            "last_reload_at": self.last_reload_at,
            "tz_label": self.tz_label,
            "timezone_offset": self.timezone_offset,
            "run_count": self.run_count,
            "last_run_at": self.last_run_at,
            "loaded_detectors": list(self.detectors.keys()),
            "loaded_analyzers": list(self.analyzers.keys()),
            "loaded_rankers": list(self.rankers.keys()),
            "reporter": self.reporter.get_config_snapshot(),
            "recommended_profiles": RootCauseRanker.get_recommended_profiles(),
            "kpi_list": [
                {
                    "name": k["name"],
                    "display_name": k.get("display_name", k["name"]),
                    "primary": k.get("primary", False),
                    "seasonal_period": k.get("seasonal_period"),
                    "normalization_threshold": k.get("normalization_threshold"),
                }
                for k in self.config.get("kpi_list", [])
            ],
        }

    def run_analysis_for_kpi(self, kpi_name):
        detector = self._get_detector(kpi_name)
        current_df, historical_df, overall_summary = detector.get_current_window(kpi_name)

        analyzer = self._get_analyzer(kpi_name)
        single_dim_results, cross_df, multi_dim_df = analyzer.deep_dive(kpi_name)

        ranker = self._get_ranker(kpi_name)
        root_causes = ranker.generate_root_causes(
            single_dim_results, cross_df, overall_summary, multi_dim_df
        )

        return {
            "kpi_name": kpi_name,
            "overall_summary": overall_summary,
            "current_df": current_df,
            "single_dim_results": single_dim_results,
            "cross_df": cross_df,
            "three_dim_df": multi_dim_df,
            "root_causes": root_causes,
        }

    def run(self, kpi_name=None, generate_multi_report=True):
        with self._lock:
            kpi_list_cfg = self.config.get("kpi_list", [])
            if kpi_name:
                target_kpis = [k for k in kpi_list_cfg if k["name"] == kpi_name]
                if not target_kpis:
                    target_kpis = kpi_list_cfg
            else:
                target_kpis = [k for k in kpi_list_cfg if k.get("primary", False)]
                if not target_kpis:
                    target_kpis = kpi_list_cfg

            all_results = {}
            for kpi_cfg in target_kpis:
                kpi_n = kpi_cfg["name"]
                result = self.run_analysis_for_kpi(kpi_n)
                all_results[kpi_n] = result

            if generate_multi_report and len(all_results) > 1:
                md_path, all_csv_paths = self.reporter.generate_multi(all_results)
            else:
                first_kpi = list(all_results.keys())[0]
                r = all_results[first_kpi]
                md_path, csv_paths = self.reporter.generate(
                    r["overall_summary"],
                    r["current_df"],
                    r["single_dim_results"],
                    r["cross_df"],
                    r["root_causes"],
                    r.get("three_dim_df"),
                    first_kpi
                )
                all_csv_paths = {first_kpi: csv_paths}

            self.run_count += 1
            self.last_run_at = datetime.now().isoformat()

            return {
                "run_at": self.last_run_at,
                "run_count": self.run_count,
                "tz_label": self.tz_label,
                "timezone_offset": self.timezone_offset,
                "analyzed_kpis": list(all_results.keys()),
                "report_path": md_path,
                "csv_paths": {k: list(v.values()) for k, v in all_csv_paths.items()},
                "summaries": {k: v["overall_summary"] for k, v in all_results.items()},
            }


def run_cli(kpi_name=None, db_path=None, generate_multi_report=True, tz_label=None):
    config = load_config()

    print("[1/5] 初始化数据库...")
    setup(db_path)

    service = KpiExplainerService.get_instance(db_path=db_path, tz_label=tz_label)

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
    print(f"[2/5] 时区: {service.tz_label} ({service.timezone_offset})")

    all_results = {}
    step = 2
    for kpi_cfg in target_kpis:
        step += 1
        kpi_n = kpi_cfg["name"]
        print(f"  [{step}/5] 分析 KPI: {kpi_n} ({kpi_cfg.get('display_name', kpi_n)})")
        result = service.run_analysis_for_kpi(kpi_n)
        all_results[kpi_n] = result

        top_single = result["root_causes"]["single_dimension_causes"][0] if result["root_causes"]["single_dimension_causes"] else None
        top_cross = result["root_causes"]["cross_dimension_causes"][0] if result["root_causes"]["cross_dimension_causes"] else None
        if top_single:
            print(f"    Top-1 单维度根因: {top_single['label']}, 置信度={top_single['confidence']:.4f}")
        if top_cross:
            print(f"    Top-1 交叉维度根因: {top_cross['dimension_combo']}, 置信度={top_cross['confidence']:.4f}")

    print(f"  [5/5] 生成报告...")
    if generate_multi_report and len(all_results) > 1:
        md_path, all_csv_paths = service.reporter.generate_multi(all_results)
        print(f"\n多指标综合报告已生成: {md_path}")
        for kpi_n, csv_paths in all_csv_paths.items():
            print(f"\n  KPI: {kpi_n}")
            for name, path in csv_paths.items():
                print(f"    CSV ({name}): {path}")
    else:
        first_kpi = list(all_results.keys())[0]
        r = all_results[first_kpi]
        md_path, csv_paths = service.reporter.generate(
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


class AdminHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text, status=200):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        service = KpiExplainerService.get_instance()
        path = self.path.split("?")[0].rstrip("/")

        if path == "" or path == "/":
            self._send_json({"service": "kpi-anomaly-explainer", "status": "ok", "endpoints": ["/health", "/status", "/admin/reload", "/run"]})
        elif path == "/health":
            self._send_json({"status": "healthy", "tz": service.tz_label, "offset": service.timezone_offset})
        elif path == "/status":
            self._send_json(service.status())
        elif path == "/admin/reload":
            info = service.reload_all()
            self._send_json({"status": "ok", "info": info})
        elif path == "/run":
            result = service.run()
            self._send_json({"status": "ok", "result": result})
        else:
            self._send_json({"error": "not_found", "path": path}, status=404)

    def do_POST(self):
        service = KpiExplainerService.get_instance()
        path = self.path.split("?")[0].rstrip("/")
        content_len = int(self.headers.get("Content-Length", 0))
        body = {}
        if content_len > 0:
            try:
                raw = self.rfile.read(content_len)
                body = json.loads(raw.decode("utf-8"))
            except Exception as e:
                self._send_json({"error": "invalid_json", "detail": str(e)}, status=400)
                return

        if path == "/admin/reload":
            new_tz = body.get("tz")
            info = service.reload_all(new_tz_label=new_tz)
            self._send_json({"status": "ok", "info": info})
        elif path == "/run":
            kpi_name = body.get("kpi")
            multi = body.get("multi", True)
            result = service.run(kpi_name=kpi_name, generate_multi_report=multi)
            self._send_json({"status": "ok", "result": result})
        else:
            self._send_json({"error": "not_found", "path": path}, status=404)


def serve(host="0.0.0.0", port=8765, db_path=None, tz_label=None):
    setup(db_path)
    KpiExplainerService.get_instance(db_path=db_path, tz_label=tz_label)
    server = HTTPServer((host, port), AdminHandler)
    print(f"[kpi-explainer] 服务启动: http://{host}:{port}")
    print(f"[kpi-explainer] 时区: {KpiExplainerService.get_instance().tz_label} ({KpiExplainerService.get_instance().timezone_offset})")
    print(f"[kpi-explainer] 接口:")
    print(f"  GET  /health           健康检查")
    print(f"  GET  /status           当前配置状态")
    print(f"  GET/POST /admin/reload 热重载配置 (POST body: {{\"tz\": \"Asia/Tokyo\"}})")
    print(f"  GET/POST /run          执行一次分析 (POST body: {{\"kpi\": \"revenue\", \"multi\": false}})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[kpi-explainer] 服务停止")
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description="KPI 异常解释器")
    parser.add_argument("--kpi", type=str, default=None, help="指定分析的 KPI 名称（默认分析所有 primary KPI）")
    parser.add_argument("--tz", type=str, default=None, help="时区标签 (CST/JST/PST/Asia/Shanghai 或 +08:00)")
    parser.add_argument("--db", type=str, default=None, help="数据库文件路径")
    parser.add_argument("--single", action="store_true", help="仅生成单指标报告（不生成多指标综合报告）")
    parser.add_argument("--serve", action="store_true", help="以 HTTP 服务模式启动（常驻）")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="服务监听地址（--serve 模式）")
    parser.add_argument("--port", type=int, default=8765, help="服务监听端口（--serve 模式）")
    args = parser.parse_args()

    if args.serve:
        serve(host=args.host, port=args.port, db_path=args.db, tz_label=args.tz)
    else:
        run_cli(
            kpi_name=args.kpi,
            db_path=args.db,
            generate_multi_report=not args.single,
            tz_label=args.tz,
        )


if __name__ == "__main__":
    main()
