# KPI 异常解释器

自动从数据库提取业务指标时间序列，基于 STL 季节性分解检测异常，按维度逐层下钻定位根因，生成 Markdown 报告与 CSV 数据。

## 快速开始

```bash
python main.py                        # 默认分析 primary KPI，时区 CST
python main.py --kpi order_count      # 指定 KPI
python main.py --tz JST               # 日本时区
python main.py --tz PST --kpi revenue # 美西时区
python main.py --tz +05:30            # 直接传 UTC offset
```

## 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--kpi` | 指定分析的 KPI 名称 | 所有 primary KPI |
| `--tz` | 时区标签 (CST/JST/PST/UTC 等) 或 UTC offset (+08:00) | 配置文件 `output.default_timezone` |
| `--db` | 数据库文件路径 | 内存数据库 |
| `--single` | 仅生成单指标报告 | False |

## kpi_config.yaml Schema

配置文件控制 KPI 定义、分析参数、维度和输出格式，新增 KPI 无需改源码。

### 顶层结构

```yaml
kpi_list:        # KPI 指标列表 (必填)
analysis:        # 分析参数 (必填)
dimensions:      # 维度定义 (必填)
timezone_map:    # 时区映射表 (可选，扩展内置时区)
output:          # 输出配置 (必填)
```

### kpi_list[] — KPI 指标定义

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | ✅ | 指标英文名，须与数据库列名一致 |
| `display_name` | string | ✅ | 报告展示用的中文名 |
| `unit` | string | ✅ | 指标单位，如 `元`、`单`、`%` |
| `description` | string | ❌ | 指标描述 |
| `expected_direction` | string | ✅ | 期望方向：`up`（越高越好）或 `down`（越低越好） |
| `aggregation` | string | ✅ | 聚合方式：`sum` / `avg` / `count` |
| `primary` | bool | ❌ | 是否默认分析（不传 `--kpi` 时分析 primary 指标） |
| `seasonal_period` | int | ✅ | STL 季节性周期天数。日级=7（周），月度级=30 |
| `normalization_threshold` | float | ✅ | 反向归一化惩罚系数。越低越严格，范围 0~1 |

### analysis — 分析参数

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `window_size` | int | ✅ | 当前分析窗口天数 |
| `z_threshold` | float | ✅ | Z-Score 异常阈值 |
| `drilldown_layers` | list[list[string]] | ✅ | 3 层下钻维度组合，每个元素是长度≥3 的维度名列表 |
| `priority_combos` | list[list[string]] | ✅ | 优先维度组合（2 层），排序加权更高 |

### dimensions[] — 维度定义

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | ✅ | 维度英文名，须与数据库列名一致 |
| `display_name` | string | ✅ | 报告展示用中文名 |
| `values` | list[string] | ✅ | 维度枚举值列表 |

### timezone_map — 自定义时区映射

| 键 | 值 | 说明 |
|------|------|------|
| 时区标签 | UTC offset 字符串 | 如 `CST: "+08:00"` |

内置时区：`CST`(+08:00)、`JST`(+09:00)、`PST`(-08:00)、`EST`(-05:00)、`UTC`(+00:00)、`CET`(+01:00)、`IST`(+05:30)、`KST`(+09:00)、`AEST`(+10:00)、`NST`(+12:00)。自定义映射会覆盖内置。

### output — 输出配置

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `report_dir` | string | ✅ | 输出目录 |
| `default_timezone` | string | ✅ | 默认时区标签（`--tz` 未指定时使用） |
| `csv_encoding` | string | ✅ | CSV 编码，推荐 `utf-8-sig`（Excel 兼容） |

---

## 配置范例

### 范例 1: 最小配置（单 KPI）

```yaml
kpi_list:
  - name: revenue
    display_name: 营收
    unit: 元
    expected_direction: up
    aggregation: sum
    primary: true
    seasonal_period: 7
    normalization_threshold: 0.3

analysis:
  window_size: 7
  z_threshold: 2.0
  drilldown_layers:
    - [region, product_line, channel]
  priority_combos:
    - [region, product_line]

dimensions:
  - name: region
    display_name: 区域
    values: [华东, 华南, 华北]
  - name: product_line
    display_name: 产品线
    values: [手机, 电脑, 平板]
  - name: channel
    display_name: 渠道
    values: [线上直营, 线下门店]

output:
  report_dir: output
  default_timezone: CST
  csv_encoding: utf-8-sig
```

### 范例 2: 多 KPI（周级 + 月度级混合周期）

```yaml
kpi_list:
  - name: revenue
    display_name: 营收
    unit: 元
    expected_direction: up
    aggregation: sum
    primary: true
    seasonal_period: 7
    normalization_threshold: 0.3

  - name: churn_rate
    display_name: 流失率
    unit: "%"
    expected_direction: down
    aggregation: avg
    primary: false
    seasonal_period: 30
    normalization_threshold: 0.2
```

### 范例 3: 多下钻层 + 多优先组合

```yaml
analysis:
  window_size: 7
  z_threshold: 2.0
  drilldown_layers:
    - [region, product_line, channel]
    - [region, product_line, warehouse]
  priority_combos:
    - [region, product_line]
    - [product_line, channel]
```

### 范例 4: 跨时区部署（日企 JST）

```yaml
timezone_map:
  JST: "+09:00"

output:
  report_dir: output_jp
  default_timezone: JST
  csv_encoding: utf-8-sig
```

运行：`python main.py --tz JST`

### 范例 5: 高灵敏度 KPI 配置

```yaml
kpi_list:
  - name: payment_success_rate
    display_name: 支付成功率
    unit: "%"
    expected_direction: up
    aggregation: avg
    primary: true
    seasonal_period: 7
    normalization_threshold: 0.15

analysis:
  window_size: 3
  z_threshold: 1.5
  drilldown_layers:
    - [region, payment_method, channel]
  priority_combos:
    - [region, payment_method]
```

`normalization_threshold: 0.15` 表示方向不匹配时惩罚更重（仅保留 15%），`z_threshold: 1.5` 放宽阈值以捕获更多弱信号。

---

## 输出文件

| 文件 | 说明 |
|------|------|
| `{kpi}_anomaly_report.md` | Markdown 分析报告 |
| `{kpi}_daily_trend.csv` | 日级趋势（含 STL 分解列） |
| `{kpi}_dimension_analysis.csv` | 单维度分析 |
| `{kpi}_cross_dimension_analysis.csv` | 交叉维度分析 |
| `{kpi}_three_dimension_drilldown.csv` | 三维度下钻 |
| `{kpi}_root_causes_single.csv` | 单维度根因排序 |
| `{kpi}_root_causes_cross.csv` | 交叉维度根因排序 |
| `{kpi}_root_causes_three.csv` | 三维度根因排序 |

CSV 时间戳格式：`YYYY-MM-DD +HH:MM`（UTC offset 由 `--tz` 或配置决定）。

## 依赖

```bash
pip install pandas numpy statsmodels pyyaml
```
