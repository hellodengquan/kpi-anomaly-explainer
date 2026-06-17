# KPI 异常解释器

自动从数据库提取业务指标时间序列，基于 STL 季节性分解检测异常，按维度逐层下钻定位根因，生成 Markdown 报告与 CSV 数据。支持 CLI 调用和 HTTP 常驻服务两种模式。

## 快速开始

### CLI 模式

```bash
python main.py                        # 默认分析 primary KPI，时区 Asia/Shanghai
python main.py --kpi order_count      # 指定 KPI
python main.py --tz JST               # 日本时区
python main.py --tz Asia/Tokyo        # IANA 标准时区
python main.py --tz PST --kpi revenue # 美西时区
python main.py --tz +05:30            # 直接传 UTC offset
```

### HTTP 服务模式

```bash
python main.py --serve --port 8765 --tz Asia/Shanghai
# curl http://localhost:8765/health
# curl -X POST http://localhost:8765/admin/reload \
#      -H 'X-Admin-Token: kpi-explainer-admin-2026' \
#      -H 'Content-Type: application/json' \
#      -d '{"tz":"Asia/Tokyo"}'
# curl -X POST http://localhost:8765/run \
#      -H 'X-Admin-Token: kpi-explainer-admin-2026'
```

## 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--kpi` | 指定分析的 KPI 名称 | 所有 primary KPI |
| `--tz` | 时区：支持 3 字母缩写 (CST/JST/PST)、IANA (Asia/Shanghai)、UTC offset (+08:00) | 配置文件 `output.default_timezone` |
| `--db` | 数据库文件路径 | 内存数据库 |
| `--single` | 仅生成单指标报告 | False |
| `--serve` | 常驻 HTTP 服务模式 | False |
| `--host` | 服务监听地址 | 0.0.0.0 |
| `--port` | 服务监听端口 | 8765 |

## HTTP 接口

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| GET | `/` | ❌ | 服务概览与端点列表 |
| GET | `/health` | ❌ | 健康检查，返回 `{"status":"healthy", "tz":"Asia/Shanghai", "offset":"+08:00"}` |
| GET | `/status` | ❌ | 完整状态：KPI 列表、已加载模块、配置快照、推荐参数档、KPI 类型档位、安全配置 |
| GET | `/admin/reload` | ⚠️ 默认禁用 | 热重载（需 `security.allow_get_admin: true` + Token）|
| POST | `/admin/reload` | ✅ 需要 Token | 热重载 kpi_config.yaml（无需重启）。body: `{"tz":"Asia/Tokyo"}`（可选）|
| GET | `/run` | ❌ | 执行一次分析（GET 无鉴权，适合内部测试）|
| POST | `/run` | ✅ 需要 Token | 执行一次分析。body: `{"kpi":"revenue", "multi":false}` |

鉴权通过 `X-Admin-Token` 请求头（可在 `security.token_header` 自定义）传递。`/admin/reload` 默认禁用 GET 调用，必须用 POST 且带 Token，防 CSRF/误触。

`/admin/reload` 热推后，已缓存的 detector / analyzer / ranker / reporter 会全部刷新配置，包括每个 KPI 的 seasonal_period、normalization_threshold、drilldown_layers、security 配置本身。

## 时区支持 (--tz)

三种格式任选其一：

| 格式 | 示例 | 说明 |
|------|------|------|
| **缩写** | `CST`, `JST`, `PST`, `UTC` | 内置 10+ 常见缩写，可在 `timezone_map` 自定义覆盖 |
| **IANA** | `Asia/Shanghai`, `America/New_York`, `Europe/London` | 标准时区名，Python 3.9+ 通过 `zoneinfo` 实时解析 |
| **UTC offset** | `+08:00`, `-05:00`, `+05:30` | 直接使用 |

内置 IANA 映射：`Asia/Shanghai`, `Asia/Beijing`, `Asia/Tokyo`, `Asia/Seoul`, `Asia/Singapore`, `Asia/Kolkata`, `Asia/Dubai`, `Asia/Hong_Kong`, `Asia/Taipei`, `America/Los_Angeles`, `America/New_York`, `America/Chicago`, `America/Denver`, `America/Sao_Paulo`, `Europe/London`, `Europe/Paris`, `Europe/Berlin`, `Europe/Moscow`, `Australia/Sydney`, `Pacific/Auckland`。

### 夏令时边缘时区（单独识别）

以下美国州内县区存在独立 DST 策略，已内置映射，避免 `zoneinfo` 解析异常：

| 时区 | UTC offset | 说明 |
|------|------------|------|
| `America/Indiana/Marengo` | `-05:00` | 印第安纳州克劳福德县 |
| `America/Indiana/Knox` | `-06:00` | 印第安纳州诺克斯县（使用中部时间）|
| `America/Indiana/Petersburg` | `-05:00` | 印第安纳州派克县 |
| `America/Indiana/Vevay` | `-05:00` | 印第安纳州瑞士县 |
| `America/Indiana/Vincennes` | `-05:00` | 印第安纳州诺克斯县以东 |
| `America/Indiana/Winamac` | `-05:00` | 印第安纳州普瓦斯基县 |
| `America/Kentucky/Louisville` | `-05:00` | 肯塔基州路易斯维尔 |
| `America/Kentucky/Monticello` | `-05:00` | 肯塔基州韦恩县 |
| `America/North_Dakota/Beulah` | `-06:00` | 北达科他州 Mercer 县 |
| `America/North_Dakota/Center` | `-06:00` | 北达科他州 Oliver 县 |
| `America/North_Dakota/New_Salem` | `-06:00` | 北达科他州 Morton 县 |

所有 CSV 时间戳格式：`YYYY-MM-DD ±HH:MM`，由 `--tz` 或配置决定。

## kpi_config.yaml Schema

配置文件控制 KPI 定义、分析参数、维度和输出格式，新增 KPI 无需改源码。

### 顶层结构

```yaml
kpi_list:              # KPI 指标列表 (必填)
analysis:              # 分析参数 (必填)
dimensions:            # 维度定义 (必填)
security:              # 安全配置 (可选，服务模式推荐)
timezone_map:          # 自定义时区映射 (可选)
output:                # 输出配置 (必填)
recommended_defaults:  # 推荐参数档 (可选，运营参考)
kpi_type_profiles:     # KPI 类型档位 (可选，运营参考)
```

### security — 安全配置（服务模式推荐）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `admin_token` | string | ❌ | 管理接口 Token。未设置时所有接口免鉴权（不推荐生产使用）|
| `token_header` | string | ❌ | Token 所在请求头，默认 `X-Admin-Token` |
| `allow_get_admin` | bool | ❌ | 是否允许 GET 调用 `/admin/reload`，默认 `false`（仅 POST）|

### kpi_list[] — KPI 指标定义

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | ✅ | 指标英文名，**须与数据库列名完全一致** |
| `display_name` | string | ✅ | 报告展示用中文名 |
| `unit` | string | ✅ | 指标单位，如 `元`、`单`、`%`、`元/单` |
| `description` | string | ❌ | 指标描述 |
| `expected_direction` | string | ✅ | 期望方向：`up`（越高越好）或 `down`（越低越好） |
| `aggregation` | string | ✅ | 聚合方式：`sum` / `avg` / `count` |
| `primary` | bool | ❌ | 是否默认分析（不传 `--kpi` 时分析 primary 指标） |
| `kpi_type` | string | ❌ | KPI 类型：`monetary` / `order_volume` / `click_rate` / `retention` / `error_rate`，按类型套用档位 |
| `seasonal_period` | int | ✅ | STL 季节性周期天数。周级=7，双周=14，月度=30 |
| `normalization_threshold` | float | ✅ | 反向归一化惩罚系数（方向不匹配时乘此系数）。0~1，越小越严格 |
| `sensitivity_profile` | string | ❌ | 灵敏度档位：`strict` / `standard` / `lenient`，覆盖类型档位与显式数值 |

优先级（从低到高）：全局默认 → `kpi_type` → `sensitivity_profile` → 显式 `z_threshold` / `normalization_threshold`。

### analysis — 分析参数

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `window_size` | int | ✅ | 当前分析窗口天数 |
| `z_threshold` | float | ✅ | Z-Score 异常阈值（全局，可被 per-KPI 覆盖） |
| `normalization_threshold` | float | ❌ | 全局反向归一化阈值（未设置 per-KPI 时使用） |
| `drilldown_layers` | list[list[string]] | ✅ | 多层下钻维度组合，支持任意 3+ 层。例：`[[region, product_line, channel], [region, product_line, channel, member_level], [region, product_line, channel, member_level, is_weekend]]` |
| `priority_combos` | list[list[string]] | ✅ | 优先维度组合，匹配时排序加权 +0.08。例：`[[region, product_line]]` |
| `max_combo_cardinality` | int | ❌ | 单层维度组合基数上限，超过即跳过以防组合爆炸。默认 200 |

### dimensions[] — 维度定义

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | ✅ | 维度英文名，**须与数据库列名完全一致** |
| `display_name` | string | ✅ | 报告展示用中文名 |
| `values` | list[string] | ✅ | 维度枚举值列表（参考用） |

### timezone_map — 自定义时区映射

| 键 | 值 | 说明 |
|------|------|------|
| 时区标签 | UTC offset 字符串 | 如 `Asia/Shanghai: "+08:00"`，覆盖内置同名映射 |

### output — 输出配置

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `report_dir` | string | ✅ | 输出目录 |
| `default_timezone` | string | ✅ | 默认时区标签（`--tz` 未指定时使用） |
| `csv_encoding` | string | ✅ | CSV 编码，推荐 `utf-8-sig`（Excel 兼容） |

### recommended_defaults — 推荐参数档（运营参考）

```yaml
recommended_defaults:
  seasonal_period:
    weekly: 7          # 周级周期性
    biweekly: 14       # 双周级
    monthly: 30        # 月度级
  normalization_threshold:
    strict: 0.15       # 严格：方向错误强惩罚
    standard: 0.30     # 标准：默认档
    lenient: 0.50      # 宽松：方向错误弱惩罚
  z_threshold:
    strict: 1.5        # 严格：捕捉弱信号
    standard: 2.0      # 标准：默认档
    lenient: 3.0       # 宽松：仅强信号
```

### kpi_type_profiles — KPI 类型档位（运营参考）

```yaml
kpi_type_profiles:
  monetary:      { z_threshold: 2.0, normalization_threshold: 0.30 }  # 营收、客单价、GMV
  order_volume:  { z_threshold: 2.0, normalization_threshold: 0.25 }  # 订单量、UV、PV
  click_rate:    { z_threshold: 1.8, normalization_threshold: 0.20 }  # CTR、CVR
  retention:     { z_threshold: 2.0, normalization_threshold: 0.35 }  # DAU、次日留存
  error_rate:    { z_threshold: 1.5, normalization_threshold: 0.15 }  # 支付失败率、流失率
```

运营可直接设置 `kpi_type: "click_rate"` 而无需手填数值。

---

## 配置正例

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

security:
  admin_token: "change-me"
  token_header: "X-Admin-Token"
  allow_get_admin: false

output:
  report_dir: output
  default_timezone: Asia/Shanghai
  csv_encoding: utf-8-sig
```

### 范例 2: 多 KPI（周级 + 月度级混合周期 + KPI 类型档位）

```yaml
kpi_list:
  - name: revenue
    display_name: 营收
    unit: 元
    expected_direction: up
    aggregation: sum
    primary: true
    kpi_type: monetary        # ← 自动套用 z=2.0, norm=0.30
    seasonal_period: 7

  - name: order_count
    display_name: 订单量
    unit: 单
    expected_direction: up
    aggregation: sum
    primary: false
    kpi_type: order_volume    # ← 自动套用 z=2.0, norm=0.25
    seasonal_period: 7

  - name: click_through_rate
    display_name: 点击率
    unit: "%"
    expected_direction: up
    aggregation: avg
    primary: false
    kpi_type: click_rate      # ← 自动套用 z=1.8, norm=0.20
    seasonal_period: 7
```

### 范例 3: 5 层维度下钻（大零售业态：产品 × 地域 × 渠道 × 会员等级 × 周末）

```yaml
dimensions:
  - { name: region, display_name: 区域, values: [华东, 华南, 华北, 西南, 华中] }
  - { name: product_line, display_name: 产品线, values: [手机, 电脑, 平板, 穿戴设备] }
  - { name: channel, display_name: 渠道, values: [线上直营, 线下门店, 分销商, 运营商] }
  - { name: member_level, display_name: 会员等级, values: [普通, 银卡, 金卡, 黑卡] }
  - { name: is_weekend, display_name: 是否周末, values: [工作日, 周末] }

analysis:
  window_size: 7
  z_threshold: 2.0
  max_combo_cardinality: 200
  drilldown_layers:
    - [region, product_line, channel]
    - [region, product_line, channel, member_level]
    - [region, product_line, channel, member_level, is_weekend]
  priority_combos:
    - [region, product_line]
    - [region, product_line, member_level]
```

### 范例 4: 灵敏度档位覆盖 KPI 类型

```yaml
kpi_list:
  - name: payment_success_rate
    display_name: 支付成功率
    unit: "%"
    expected_direction: up
    aggregation: avg
    primary: true
    kpi_type: error_rate            # z=1.5, norm=0.15
    sensitivity_profile: strict     # 再叠加 strict：更严格 z=1.5, norm=0.15（此处一致）
```

### 范例 5: 跨时区部署（美东边缘县区）

```yaml
timezone_map:
  America/Indiana/Marengo: "-05:00"
  America/New_York: "-05:00"

security:
  admin_token: "prod-secret-token"

output:
  report_dir: output_us
  default_timezone: America/Indiana/Marengo
  csv_encoding: utf-8-sig
```

运行：`python main.py --serve --tz America/Indiana/Marengo`

---

## 常见错配反例（⚠️ 避免）

### 反例 1: KPI name 与数据库列名不一致

```yaml
# ❌ 错误：数据库列是 revenue，这里写了 sales_amount
kpi_list:
  - name: sales_amount
    display_name: 营收
    ...
```

**后果：** 空数据或 KeyError。**修正：** `name` 必须等于 SQL 列名。

### 反例 2: dimension name 拼写错误

```yaml
# ❌ 错误：数据库列是 product_line，这里多了下划线
dimensions:
  - name: product__line   # ← 多了一个 _
    display_name: 产品线
    ...
```

**后果：** 该维度在分析时被静默跳过。**修正：** 对照数据库 schema 逐字核对。

### 反例 3: drilldown_layers 路径深度错配（父维度存在但子维度为空）

```yaml
# ❌ 错误：5 层下钻 [region, product_line, channel, member_level, is_weekend]，
#        但数据库里 is_weekend 仅部分行有值，导致某路径下 member_level=黑卡 & is_weekend=周末
#        组合基数超过 max_combo_cardinality 或返回全空
analysis:
  drilldown_layers:
    - [region, product_line, channel, member_level, is_weekend]
  max_combo_cardinality: 10  # ← 设置太低，5 层实际基数 5×4×4×4×2=640 > 10
```

**后果：** 该 5 层组合被直接跳过（WARN 日志），根因不完整。**修正：**
- 5 层场景建议 `max_combo_cardinality ≥ 500`
- 或拆成多个 3-4 层组合分步下钻，避免 5 层同时展开
- 确认每个维度在所有路径上均有数据

### 反例 4: seasonal_period 设置过大数据不足

```yaml
# ❌ 错误：仅 30 天历史数据，却设为 90 天周期
kpi_list:
  - name: quarterly_rev
    seasonal_period: 90   # ← 需要至少 180 天数据才够 STL 拟合
```

**后果：** STL 退化为滑动窗口，失去季节性修正能力。**修正：** `seasonal_period × 2 ≤ 历史数据天数`；或先保证数据量。

### 反例 5: normalization_threshold 范围错误

```yaml
# ❌ 错误：设置为负数或 > 1
kpi_list:
  - name: revenue
    normalization_threshold: -0.5   # ← 负数导致方向不匹配反而加分
    normalization_threshold: 1.5    # ← >1 方向不匹配惩罚反向变成激励
```

**后果：** 根因排序完全颠倒，无关维度排在前面。**修正：** 取值范围 `(0, 1]`，优先用 `kpi_type` 或 `sensitivity_profile` 档位避免手填出错。

---

## 推荐默认值速查表

### 按灵敏度档位

| 场景 | 档位 | seasonal_period | normalization_threshold | z_threshold |
|------|------|-----------------|-------------------------|-------------|
| 日常营收/订单（周周期） | `standard` + weekly | 7 | 0.30 | 2.0 |
| 支付成功率/留存率（高敏感） | `strict` + weekly | 7 | 0.15 | 1.5 |
| 品牌曝光/流量（高噪声） | `lenient` + weekly | 7 | 0.50 | 3.0 |
| 月度财务指标 | `standard` + monthly | 30 | 0.30 | 2.0 |
| 客单价/ARPU（变化慢） | `standard` + biweekly | 14 | 0.40 | 2.0 |

### 按 KPI 类型

| KPI 类型 | 代表指标 | z_threshold | normalization_threshold | 推荐 profile |
|------|------|------|------|------|
| `monetary` | 营收、客单价、GMV | 2.0 | 0.30 | standard |
| `order_volume` | 订单量、UV、PV | 2.0 | 0.25 | standard |
| `click_rate` | CTR、CVR | 1.8 | 0.20 | strict~standard |
| `retention` | DAU、次日留存、7 日留存 | 2.0 | 0.35 | lenient |
| `error_rate` | 支付失败率、流失率、退货率 | 1.5 | 0.15 | strict |

## 输出文件

| 文件 | 说明 |
|------|------|
| `{kpi}_anomaly_report.md` / `kpi_anomaly_report.md` | Markdown 分析报告（单/多指标） |
| `{kpi}_daily_trend.csv` | 日级趋势（含 STL 分解列） |
| `{kpi}_dimension_analysis.csv` | 单维度分析 |
| `{kpi}_cross_dimension_analysis.csv` | 交叉维度分析 |
| `{kpi}_multi_dimension_drilldown.csv` | 多层（3+ 层）下钻明细 |
| `{kpi}_root_causes_single.csv` | 单维度根因排序 |
| `{kpi}_root_causes_cross.csv` | 交叉维度根因排序 |
| `{kpi}_root_causes_multi.csv` | 多层维度根因排序 |

CSV 时间戳格式：`YYYY-MM-DD ±HH:MM`（UTC offset 由 `--tz` 或配置决定）。

## 依赖

```bash
pip install pandas numpy statsmodels pyyaml
```
