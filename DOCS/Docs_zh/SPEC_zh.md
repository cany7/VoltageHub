# VoltageHub 规范文档（SPEC）

---

## 0. 项目概述

### 项目类型
**批量构建的分析型数据产品**。系统按可配置的时间间隔运行（默认每小时一次），支持增量同步与历史回填。

### 问题陈述
美国电网运行数据，包括区域负荷、发电结构和负载变化模式，会通过 EIA 的公开数据接口持续更新。若直接将这些上游数据用于分析，往往会面临较高的不稳定性和不一致性：数据模式可能变化，数据到达延迟不规律，直接基于原始 API 响应做即席查询也无法支撑可复现的分析、稳定的质量保障和受控的下游消费。

本项目通过构建一个**批量构建的分析型数据产品**来解决这一问题，系统将：
- 按可配置的时间窗口增量提取 EIA 电网运行数据
- 在云端原始着陆区保留批次原文数据，以支持重放和审计
- 使用 dbt 在 BigQuery 中构建分层仓库（staging → marts → meta）
- 在各层执行数据质量校验、新鲜度监控和异常检测
- 通过轻量级 Serving API 和 stdio MCP Server 暴露稳定、可治理的分析指标

### 项目目标
构建一套可复现、可直接用于开发和验证的分析型数据产品系统，交付内容包括：
- 面向电网数据增量提取的批处理编排
- 使用 IaC 进行云基础设施部署
- 支持重放和回填的原始数据湖着陆区
- 包含 staging、marts 和 meta 数据集的分层分析仓库
- 基于 dbt 的转换、数据质量测试和文档生成
- 提供固定分析指标与管道健康状态的轻量级 REST API
- 提供面向 LLM Agent 的 stdio MCP Server（Tools + Resources）
- 将管道元数据、新鲜度监控和异常检测作为一等输出

### 本项目最终交付什么
这不是“做一条数据管道”这么简单，而是要交付一个完整的数据产品。管道只是生产手段，真正的交付物包括：
- **仓库模型**：稳定、经过测试并具备文档说明的分析表
- **控制平面输出**：新鲜度状态、管道状态、运行指标和异常检测结果
- **Serving API**：面向固定指标和管道健康状态的 REST 程序化访问接口
- **MCP Server**：面向 LLM Agent 的 stdio Tools / Resources 接口

---

## 1. 分析问题与消费场景

### 核心分析问题
Serving Layer（REST API + stdio MCP Server）需要支持以下分析问题：
- **区域电力需求（load）** 随时间如何变化？
- 在给定区域或时间范围内，按能源类型 / 燃料类型划分的**发电结构**是什么？
- 在指定时期内，哪些区域的**总需求最高**？
- 相比近期基线，负荷或发电是否存在**异常升高或异常下降**？
- 当前的**数据新鲜度**和管道健康状态如何？

### 消费场景
- **区域负荷趋势分析**：按 balancing area 跟踪需求的时间变化
- **发电结构分析**：按能源类型 / 燃料类型拆解发电构成
- **区域需求对比**：比较不同区域之间的负荷水平
- **高需求区域监控**：识别并持续跟踪负荷最高的区域
- **新鲜度与管道状态查询**：查看数据产品的运行健康状况
- **异常分析**：检测并呈现电网指标中的异常模式
- **Agent 辅助分析**：让 LLM Agent 在读取上下文后，通过固定工具安全查询负荷、发电结构和控制平面状态

### 主要交付物
- 基于 **GCS** 的云端原始数据着陆区
- **BigQuery** 中的分层仓库数据集（staging、marts、meta）
- **dbt** 模型、测试、新鲜度检查与生成文档
- 负责端到端批处理编排的 **Airflow** DAG
- 数据质量产物：新鲜度检查结果、异常检测结果、管道运行指标
- 通过 **Python FastAPI** 提供固定分析指标的 **Serving API**
- 通过 **stdio MCP Server** 提供面向 LLM Agent 的 **Tools / Resources**
- 架构文档、环境配置说明和可复现性指南

---

## 2. 数据源

### 来源
**EIA Grid Data**，即美国能源信息署（EIA）公开发布的电网运行数据，覆盖电力需求、发电量以及相关运行指标。

### 数据源特征
- 可通过 EIA 公开数据接口和下载资源获取
- 支持按**时间窗口**提取，窗口粒度可配置，默认按小时
- 包含关键维度：
  - **区域 / Balancing Area**：电网的地理或运行区域
  - **能源类型 / 燃料类型**：按发电来源分类，如天然气、风电、光伏、核电等
  - **时间**：不同粒度的观测时间戳
- 适合在多种时间粒度上构建分析指标
- 原始响应可先原样落地，再进入仓库转换流程

### 选择该数据源的原因
- 数据持续更新，天然适合增量批量摄取
- 维度结构丰富（区域、燃料类型、时间），便于分析建模
- 公开可获取且文档相对完善，利于复现
- 数据规模适合单项目仓库，不需要引入分布式计算框架
- 能直接支撑核心分析场景，如负荷趋势、发电结构和区域对比

### 范围控制
- **默认回填范围**：最近 7 天，足以完成基础验证与质量检查
- **扩展回填范围**：最多可配置到 90 天，以支持更深的趋势分析
- **增量同步**：按计划提取最新可用时间窗口的数据
- 提取参数（时间范围、区域、指标）通过 Airflow Variables 配置

---

## 3. 架构

### 管道类型
这是一个**批处理**管道。电网运行分析属于周期性分析负载，而不是实时控制或流式处理系统。

### 架构概览

```
EIA 数据源（公开接口）
    │
    ▼
按时间窗口提取批次
    │
    ▼
原始着陆区（GCS）
    │
    ▼
BigQuery Raw（源批次记录）
    │
    ▼
dbt Staging（规范化指标）
    │
    ▼
dbt Marts / Aggregates / Meta
    │
    ▼
Serving Layer
   ├── Serving API（Python FastAPI）
   └── MCP Server（stdio，Tools + Resources）
            │
            ▼
         消费者 / LLM Agent
```

### 数据平面与控制平面

**数据平面（Data Plane）**，即面向分析消费的数据资产：
- 原始数据（GCS 着陆区 + BigQuery raw 表）
- Staging 表（规范化、标准化后的电网指标）
- Marts（事实表与维度表）
- Aggregates（按可配置时间粒度汇总的消费层数据）

**控制平面（Control Plane）**，即管道运行元数据与状态：
- 管道状态 / 水位线（最近一次成功同步的时间窗口）
- 运行指标（处理行数、运行时长、扫描字节数、状态等）
- 新鲜度状态（最新数据时间戳、延迟）
- 异常检查结果（关键指标的偏离标记）

控制平面不仅仅是内部运行记录，它同样会被 **Serving Layer** 读取，并对下游消费者暴露。

### 系统边界

**ELT 层**负责：
- 从 EIA 数据接口提取源数据
- 将原始批次数据落地到 GCS
- 完成仓库建模（raw → staging → marts → aggregates）
- 执行新鲜度、质量和异常检查
- 维护管道状态、运行指标和 meta 表

**Serving Layer** 负责：
- 提供固定模板的分析指标端点和 MCP Tools，而不是任意查询接口
- 进行参数校验并保证响应契约
- 为热点查询提供可选的内存缓存
- 暴露健康检查、新鲜度与管道状态
- 暴露供 Agent 预读取的 MCP Resources（如指标 schema、区域列表、数据质量状态）
- 记录请求日志

---

## 4. 技术栈

### 核心技术栈

| 组件 | 技术 | 版本 / 说明 |
|---|---|---|
| 云平台 | GCP | — |
| 工作流编排 | Apache Airflow | 2.9.x（通过 Docker Compose 运行） |
| 原始存储 / 着陆区 | GCS | — |
| 分析仓库 | BigQuery | — |
| 数据转换 | dbt Core | 1.8.x（安装在 Airflow 容器中） |
| 基础设施即代码 | Terraform | >= 1.5 |
| CI | GitHub Actions | — |
| 容器化 | Docker Compose | v2 |

### Serving Layer（FastAPI + MCP）

| 组件 | 技术 | 版本 / 说明 |
|---|---|---|
| 语言 | Python | 3.11+ |
| 框架 | FastAPI | latest |
| 协议 | Model Context Protocol (MCP) | `stdio` transport |
| 校验 | Pydantic | v2 |
| BigQuery 访问 | BigQuery Python client | — |
| 缓存（可选） | `cachetools` 或手写 TTL dict | 内存缓存，基于 TTL |
| 健康检查 / 可观测性 | 自定义端点 | — |

### 明确不纳入本期范围
- 流式或实时数据处理
- 分布式计算框架
- 即席分析或任意查询服务
- 多服务 / Kubernetes 风格部署
- 第一版中不引入外部缓存或专用 Serving Store

---

## 5. 部署与配置

### 5.1 使用 Docker Compose 进行本地开发

本地开发环境中，所有服务均运行在容器中。

**容器架构：**
- **Airflow webserver**：提供 `localhost:8080` 上的 UI
- **Airflow scheduler**：负责 DAG 调度与执行
- **PostgreSQL**：作为 Airflow 元数据库

**Airflow 容器镜像中安装的关键工具：**
- `dbt-core` + `dbt-bigquery`
- `google-cloud-bigquery`、`google-cloud-storage`（Python SDK）
- `requests`（调用 EIA API）

**推荐使用的 Airflow executor：** `LocalExecutor`

自定义 `Dockerfile` 基于官方 `apache/airflow:2.9.3-python3.11` 镜像扩展，并安装：
```
dbt-core==1.8.*
dbt-bigquery==1.8.*
google-cloud-bigquery
google-cloud-storage
requests
```

执行任何 dbt 命令之前都必须先执行 `dbt deps`。这一步可以放在 Docker 启动入口中完成，也可以在 `docker compose up` 后通过 `make dbt-deps` 执行。

**Docker Compose 服务：**

| 服务 | 镜像 | 用途 |
|---|---|---|
| `airflow-webserver` | 自定义镜像（扩展 `apache/airflow:2.9.3`） | Airflow UI |
| `airflow-scheduler` | 自定义镜像（与上同） | DAG 调度与执行 |
| `postgres` | `postgres:16` | Airflow 元数据库 |

本地的 `./airflow/dags`、`./airflow/plugins` 和 `./dbt` 目录会挂载到 Airflow 容器中。

### 5.2 配置管理

**原则：**
- 代码库和 Docker 镜像中不存储任何密钥或凭证
- 所有环境相关配置全部外置
- 使用单一 `.env.example` 说明所有必需变量

**配置层次：**

| 层次 | 机制 | 示例 |
|---|---|---|
| Secrets | `.env` 文件（git ignore）+ Docker Compose `env_file` | `GCP_PROJECT_ID`, `GCP_SERVICE_ACCOUNT_KEY_PATH` |
| Airflow Variables | `AIRFLOW_VAR_` 前缀或 JSON seed 文件 | `AIRFLOW_VAR_GCS_BUCKET`, `AIRFLOW_VAR_BQ_DATASET_STAGING` |
| Airflow Connections | `AIRFLOW_CONN_` 前缀 | `AIRFLOW_CONN_GOOGLE_CLOUD_DEFAULT` |
| dbt Profiles | 在 `profiles.yml` 中使用 `env_var()` | `{{ env_var('GCP_PROJECT_ID') }}` |
| Terraform Variables | `terraform.tfvars`（git ignore）+ `variables.tf` | `project_id`, `region`, `bucket_name` |

**必需环境变量（`.env.example`）：**

```env
# GCP
GCP_PROJECT_ID=your-gcp-project-id
GCP_REGION=us-central1
GCP_SERVICE_ACCOUNT_KEY_PATH=/opt/airflow/keys/service-account.json

# GCS
GCS_BUCKET_NAME=voltage-hub-raw

# BigQuery
BQ_DATASET_RAW=raw
BQ_DATASET_STAGING=staging
BQ_DATASET_MARTS=marts
BQ_DATASET_META=meta

# Airflow
AIRFLOW__CORE__EXECUTOR=LocalExecutor
AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=postgresql+psycopg2://airflow:airflow@postgres:5432/airflow
AIRFLOW__CORE__LOAD_EXAMPLES=False

# Pipeline
BACKFILL_DAYS=7

# EIA
EIA_API_KEY=your-eia-api-key
```

**GCP 认证：** 将服务账号 JSON 密钥挂载到 `/opt/airflow/keys/service-account.json`，并将 `GOOGLE_APPLICATION_CREDENTIALS` 指向该路径。

**Terraform state：** 单人开发场景使用本地 state 即可。`.gitignore` 必须排除 `terraform.tfstate*`。在多人协作场景中，可选使用远程 GCS backend。

---

## 6. 范围与非目标

### 本期范围内
- 按时间窗口驱动的 EIA 电网数据批量摄取
- 落地到 GCS 的 raw 层，并支持重放 / 回填
- BigQuery 中的 raw、staging、marts、meta 数据集
- dbt 转换、测试、新鲜度检查与异常检测
- 支持定时同步和回填的 Airflow 端到端 DAG
- 轻量级 Serving API（Python FastAPI）
- `stdio` MCP Server（面向 LLM Agent 的只读 Tools / Resources）
- 核心基础设施的 IaC
- 基于 Docker Compose 的本地部署
- 用于 lint、离线 dbt 校验和基础设施校验的 CI
- 可复现性文档

### 本期范围外
- 实时流处理（Kafka、Flink）
- 分布式处理（Spark、Dataproc）
- gRPC 或多服务 RPC
- 微服务拆分或 Service Mesh
- Kubernetes
- Redis 或外部缓存
- 动态 SQL / 任意查询引擎
- 即席分析查询界面
- HTTP / SSE 等 MCP transport
- Agent usability test / 自动化 Agent 问答回路评估
- 复杂机器学习或预测
- 实时电网控制系统
- 云托管 Airflow（Cloud Composer）
- 完整的企业级可观测性或告警平台

---

## 7. 仓库结构

```
voltage-hub/
├── terraform/                          # IaC: GCS, BigQuery, IAM, service accounts
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   └── terraform.tfvars.example
├── docker/
│   └── Dockerfile                      # 自定义 Airflow 镜像，包含 dbt 和 GCP SDK
├── airflow/
│   ├── dags/
│   │   └── eia_grid_batch.py           # 主 ELT DAG
│   ├── schemas/
│   │   └── raw_eia_batch.json          # raw 落地区 BigQuery 显式 schema
│   └── plugins/                        # 自定义 operator 或辅助逻辑
├── dbt/
│   ├── dbt_project.yml
│   ├── packages.yml
│   ├── profiles.yml
│   ├── models/
│   │   ├── staging/
│   │   │   ├── stg_grid_metrics.sql
│   │   │   └── schema.yml
│   │   ├── marts/
│   │   │   ├── core/
│   │   │   │   ├── fct_grid_metrics.sql
│   │   │   │   ├── dim_region.sql
│   │   │   │   ├── dim_energy_source.sql
│   │   │   │   └── schema.yml
│   │   │   └── aggregates/
│   │   │       ├── agg_load_hourly.sql
│   │   │       ├── agg_load_daily.sql
│   │   │       ├── agg_generation_mix.sql
│   │   │       ├── agg_top_regions.sql
│   │   │       └── schema.yml
│   │   └── meta/
│   │       └── schema.yml
│   └── macros/
├── serving-fastapi/                    # FastAPI Serving Layer
│   ├── app/
│   │   ├── routers/
│   │   ├── services/
│   │   ├── repositories/
│   │   ├── schemas/
│   │   ├── cache/
│   │   ├── config/
│   │   ├── health/
│   │   ├── exceptions/
│   │   └── main.py                     # 标准入口，定义 `app` 对象
│   ├── pyproject.toml
│   └── Dockerfile
├── mcp/                                # stdio MCP Server
│   ├── app/
│   │   ├── tools/
│   │   ├── resources/
│   │   ├── adapters/
│   │   ├── config/
│   │   └── main.py
│   └── pyproject.toml
├── docs/
├── scripts/                            # 校验和调试工具
├── .github/workflows/                  # CI: lint, dbt parse, terraform validate
├── docker-compose.yml
├── Makefile
├── .env.example
├── .gitignore
└── README.md
```

### Makefile 目标

| Target | Command | Description |
|---|---|---|
| `make up` | `docker compose up -d` | 启动所有服务 |
| `make down` | `docker compose down` | 停止所有服务 |
| `make build` | `docker compose build` | 构建自定义 Airflow 镜像 |
| `make backfill` | 通过 Airflow CLI 触发启用 catchup 的 DAG | 执行初始回填 |
| `make dbt-build` | 在容器中执行 `dbt build` | 运行 dbt 构建 |
| `make dbt-docs` | 在容器中执行 `dbt docs generate` | 生成 dbt 文档 |
| `make dbt-deps` | 在容器中执行 `dbt deps` | 安装 dbt packages |
| `make lint` | `sqlfluff lint` + `ruff check` | SQL 和 Python 代码检查 |
| `make terraform-init` | `terraform init` | 初始化 Terraform |
| `make terraform-apply` | `terraform apply` | 创建 GCP 资源 |
| `make terraform-destroy` | `terraform destroy` | 销毁 GCP 资源 |
| `make clean` | 删除本地产物、日志和临时文件 | 清理环境 |

---

## 8. 数据流与执行设计

### 基于时间窗口的提取
每次批处理运行都处理一个**确定的时间窗口**。提取步骤会针对该时间范围向 EIA 请求数据，收到响应后，先将原始数据落地到 raw 层，再进入仓库处理流程。

这里不假设“每小时固定一个文件”。每次运行处理的数据范围都由 Airflow 的调度上下文推导出来。调度间隔可配置，默认按小时执行。

### 端到端流程

```
extract_grid_batch              [按时间窗口请求 EIA 数据]
    │
    ▼
land_raw_to_gcs                 [将原始响应落地到 GCS]
    │
    ▼
load_to_bq_raw                  [将原始批次加载到 BigQuery raw 表]
    │
    ▼
dbt_source_freshness            [执行数据源新鲜度预检查]
    │
    ▼
dbt_build                       [staging 规范化 + marts + tests]
    │
    ▼
check_anomalies                 [对关键指标执行异常检测]
    │
    ▼
record_run_metrics              [将运行统计写入 meta]
    │
    ▼
update_pipeline_state           [更新水位线 / 同步状态]
```

### 原始落地要求
EIA 的原始响应数据**必须先写入 GCS**，然后再加载到 BigQuery。这样设计有几个作用：
- 支持重放与重复处理
- 回填时无需再次请求源 API
- 让 Serving Layer 与源 API 可用性解耦
- 保留已摄取数据的审计轨迹

### API 错误处理

| 场景 | 行为 |
|---|---|
| 成功（2xx） | 继续执行落地到 GCS |
| 限流（429） | 指数退避重试（基准 60 秒，最多重试 3 次） |
| 服务端错误（5xx） | 最多重试 3 次，退避间隔 2 分钟 |
| 超时 | 连接超时 120 秒，读取超时 300 秒，最多重试 3 次 |
| 空响应 / 格式错误响应 | 校验响应结构，不合法则任务失败 |

任务级重试负责处理瞬时故障；Airflow 层的重试（2 次重试，间隔 5 分钟）作为第二层保护。

### 加载方式：BigQuery Load Jobs
raw 数据通过 **BigQuery Load Job**（`bigquery.Client.load_table_from_uri`）从 GCS 加载到 BigQuery。

- Load Job **免费**，不按扫描字节计费
- 以分区为粒度使用 `WRITE_TRUNCATE`，保证幂等重载
- 使用版本化管理的显式 schema，存放在 `airflow/schemas/`

### 执行模式
- **Scheduled mode**：按配置计划执行增量同步，默认按小时，并启用 Airflow `catchup=True`
- **Backfill mode**：通过 Airflow 为缺失区间自动生成运行，也支持通过 `airflow dags backfill` 手工回填
- **Sample mode**：设置 `SAMPLE_MODE=true`，提取最小时间窗口，加载到独立数据集，并执行 `dbt build --target sample` 进行本地验证

---

## 9. 增量加载策略

### 增量粒度
每个 DAG run 只处理**一个时间窗口**，窗口由 Airflow 的调度间隔决定。默认按小时运行，但调度频率可以调整。

### 时间区间来源：Airflow `data_interval_start`
在 `catchup=True` 且配置了 schedule 的情况下，Airflow 会为每个区间生成一个 DAG run。每次运行都能拿到 `data_interval_start` 和 `data_interval_end` 两个模板变量，提取时间窗口直接由它们推导。

### 水位线 / 管道状态（灾备恢复）
BigQuery 表：`meta.pipeline_state`

字段：
- `pipeline_name`（STRING）
- `last_successful_window_start`（TIMESTAMP）：最近一次成功处理窗口的起始时间
- `last_successful_window_end`（TIMESTAMP）
- `last_successful_run_id`（STRING）：最近一次成功运行的 Airflow `run_id`，Serving Layer 会用它填充响应元数据中的 `pipeline_run_id`
- `updated_at`（TIMESTAMP）

水位线只会在每次成功运行结束时更新。正常执行路径**不会读取它**，它仅用于 Airflow 元数据丢失时的灾备恢复。

### 每次运行的增量逻辑
1. 从 `{{ data_interval_start }}` / `{{ data_interval_end }}` 推导处理窗口
2. 针对该时间窗口提取 EIA 数据
3. 将原始响应落地到 GCS：`gs://<bucket>/voltage-hub/raw/year=YYYY/month=MM/day=DD/window=<start>/batch.json`
4. 使用 `WRITE_TRUNCATE` 加载到 BigQuery raw 表对应分区
5. **确定受影响的 `observation_date` 集合**：raw 加载完成后，执行 `SELECT DISTINCT DATE(period) FROM raw.eia_grid_batch WHERE batch_date = <current_batch_date>`，这个日期集合就是下游层的重建范围
6. 执行 `dbt build`，staging 和 mart 中使用 `insert_overwrite` 的模型只重建上述受影响的 `observation_date` 分区
7. 记录运行指标
8. 更新管道状态水位线

### 分区重建规则
本项目在每一层都采用显式、确定性的分区重建策略。每次 DAG run **不会**重建所有分区，而只会覆盖当前批次影响到的 `observation_date` 分区。

**具体步骤：**

1. **Raw load**：Load Job 目标表为 `raw.eia_grid_batch`，按 `batch_date` 分区。目标分区使用 `WRITE_TRUNCATE`，因此重跑同一窗口会覆盖同一个分区并写入相同数据。
2. **受影响日期集合**：raw 加载完成后，DAG 计算新批次中涉及的 `observation_date` 去重集合。这个集合通常只有 1 到 2 天，因为一个提取窗口可能跨越日期边界。它定义了所有下游层的重建范围。
3. **dbt staging**：`stg_grid_metrics` 采用 `incremental` + `insert_overwrite`，按 `observation_date` 分区，只重建受影响日期集合中的分区。`is_incremental()` 过滤器会将源数据扫描范围限制在这些日期上。
4. **dbt marts**：`fct_grid_metrics` 同样采用按 `observation_date` 的 `insert_overwrite`，作用范围与上一步一致。维度表 `dim_region` 和 `dim_energy_source` 因为规模小，使用其自然键执行 `merge`，始终按全量范围维护。
5. **Aggregates**：聚合表直接全表重建。在预期规模下成本很低，通常每张表少于 1000 行。

**幂等性保证：**
- 重跑任意时间窗口时，会重新加载相同的 raw 分区、重新计算相同的受影响日期集合，并覆盖完全一致的下游分区，因此结果相同
- `max_active_runs=1` 避免并发运行在重叠分区上发生冲突
- 回填顺序执行，在本项目规模下是可接受的

> **取舍说明：** 顺序执行的 `max_active_runs=1` 会限制回填吞吐，但这是有意做出的简化。若将来需要并行回填，可以演进为 `WRITE_APPEND` 加 dbt 层冲突处理，但这不是当前默认方案。

### Raw 路径约定
```
gs://<bucket>/voltage-hub/raw/year=YYYY/month=MM/day=DD/window=<start_iso>/batch.json
```

---

## 10. BigQuery 仓库设计

### 10.1 数据集

| 数据集 | 用途 |
|---|---|
| `raw` | 源批次着陆区，保存最少处理的 EIA 原始记录 |
| `staging` | dbt staging 模型，完成规范化与标准化 |
| `marts` | 面向分析消费的事实表、维度表和聚合表 |
| `meta` | 管道状态、运行指标、新鲜度结果和异常检测结果 |

### 10.2 Raw Layer

#### `raw.eia_grid_batch`

这是**源批次着陆表**。它的 schema 与 EIA API 响应或下载资源的结构尽可能保持接近，只做最少转换。设计目标是保留一份可重放、可追溯的源数据副本。

**设计原则：**
- schema 反映源响应结构，而不是分析层的规范模型
- 保留所有源字段，不在 raw 层做标准化或指标透视
- 支持重放和重复处理，任意批次都可以从 GCS 重新加载
- 下游消费者（dbt staging）绝不直接依赖源 API

**Schema（显式定义，版本化存放于 `airflow/schemas/raw_eia_batch.json`）：**

| 列名 | BigQuery 类型 | 说明 |
|---|---|---|
| `respondent` | STRING | 源数据中的实体 / balancing authority 标识 |
| `respondent_name` | STRING | 源数据中的可读名称 |
| `type` | STRING | 响应类别（如 demand、generation、interchange） |
| `type_name` | STRING | 类别的可读名称 |
| `value` | FLOAT64 | 上报值 |
| `value_units` | STRING | 源数据中的计量单位 |
| `period` | STRING | 源中的观测时间（ISO 时间戳或日期字符串） |
| `fueltype` | STRING（NULLABLE） | 燃料 / 能源类型代码（用于发电数据） |
| `fueltype_name` | STRING（NULLABLE） | 燃料类型可读名称 |
| `batch_date` | DATE | 提取批次日期，用于分区 |
| `_batch_id` | STRING | 提取批次标识 |
| `_source_url` | STRING | 源接口或资源 URL，便于追溯 |
| `_ingestion_timestamp` | TIMESTAMP | 管道生成，用于新鲜度检查 |

**分区字段：** `batch_date`  
**聚簇字段：** raw 层不做 clustering

> **说明：** 上述 raw schema 对应当前选定的 EIA 数据接口族。如果未来改用其他 EIA endpoint 或资源，只需要调整 raw schema 与 staging 层映射逻辑。`stg_grid_metrics` 这个规范模型才是稳定的下游契约，marts、aggregates 和 Serving API 都只依赖 staging 层，而不会直接依赖 raw。核心原则是：raw 反映源结构，而不是规范结构。

### 10.3 Staging Layer

#### `staging.stg_grid_metrics`（dbt model）

这是**规范指标表**，也是下游 marts 的单一事实来源。dbt staging 模型会把 raw 层源记录转换成统一、长表结构的电网指标表。

**职责：**
- 解析并类型转换源字段
- 统一区域标识和能源类型代码
- 将 `period` 字符串转换成标准 TIMESTAMP
- 使用 surrogate key 保证粒度唯一
- 通过 `insert_overwrite` 实现按分区重建的幂等处理（在 `max_active_runs=1` 下无需行级去重）

核心字段：
- `metric_surrogate_key`：`dbt_utils.generate_surrogate_key(['region', 'observation_timestamp', 'metric_name', 'energy_source'])`
- `region`：标准化后的区域 / balancing area 代码（来自 `respondent`）
- `region_name`：区域名称（来自 `respondent_name`）
- `observation_timestamp`：从 `period` 解析得到的 TIMESTAMP
- `observation_date`：从 `observation_timestamp` 派生的 DATE
- `metric_name`：标准化后的指标类型（来自 `type` / `type_name`）
- `metric_value`：FLOAT64（来自 `value`）
- `energy_source`（nullable）：标准化后的燃料类型（来自 `fueltype`）；允许的 Voltage Hub 代码集合为 `BAT`, `BIO`, `COL`, `GEO`, `HPS`, `HYC`, `NG`, `NUC`, `OES`, `OIL`, `OTH`, `PS`, `SNB`, `SUN`, `UES`, `UNK`, `WAT`, `WNB`, `WND`
- `unit`：标准化后的计量单位（来自 `value_units`）
- `_ingestion_timestamp`：从 raw 层透传

**分区字段：** `observation_date`  
**聚簇字段：** `region`, `metric_name`

### 10.4 Marts Layer

#### Core Models

- **`marts.fct_grid_metrics`**：每条观测一行（region × timestamp × metric × source），按 `observation_date` 分区，按 `region`、`metric_name` 聚簇
- **`marts.dim_region`**：区域 / balancing area 维表，字段包括 `region`（主键）、`region_name`
- **`marts.dim_energy_source`**：能源 / 燃料类型维表，字段包括 `energy_source`（主键）以及可选类别分组

#### Aggregate Models

聚合表是基于 mart 层构建的消费层汇总结果，不受源数据粒度限制。

- **`marts.agg_load_hourly`**：按区域聚合的小时级负荷 / 需求指标
- **`marts.agg_load_daily`**：按区域聚合的日级负荷汇总（平均、最小、最大、总量）
- **`marts.agg_generation_mix`**：按能源类型拆解的发电结构。默认粒度为 **region × observation_date × energy_source**。这是 Serving API 的标准消费粒度，更粗的时间范围聚合（周、月）由 API 查询层或上游消费者处理
- **`marts.agg_top_regions`**：按日对区域需求做排名。默认粒度为 **observation_date × region**，按当日总负荷排序。每行包含：
  - `observation_date`（DATE）
  - `region`（STRING）
  - `region_name`（STRING）
  - `daily_total_load`（FLOAT64）：该区域当天负荷总量
  - `rank`（INT64）：该日期内的排名，`1` 表示最高负荷

Serving API 会直接消费 `marts.agg_top_regions` 来支持“给定日期范围内，每天 Top N 区域”的查询。API 中的 `limit` 参数是**按每天分别生效**，而不是跨整个日期范围统一取前 N。

这些聚合表是 Serving API 的主要数据来源。

### 10.5 Meta Layer

| 表 | 用途 | 被谁消费 |
|---|---|---|
| `meta.pipeline_state` | 最近一次成功同步窗口、水位线、最近运行 ID | `/pipeline/status` |
| `meta.run_metrics` | 每次运行的统计信息：行数、字节数、耗时、状态 | 内部可观测性（不直接通过 API 暴露） |
| `meta.freshness_log` | 每次运行的管道新鲜度与数据新鲜度 | `/freshness` |
| `meta.anomaly_results` | 关键电网指标的异常检测结果 | `/anomalies` |

meta 层是一个**面向消费者的一等数据集**。Serving API 会从这些表中读取新鲜度、管道状态和异常摘要，并通过独立端点暴露。

这些 meta 表属于控制平面，由 Airflow 任务直接维护。如果某张表还不存在，则写入它的 Airflow Python task 需要先按需建表，再执行插入或更新。它们会在 dbt 中保留文档定义以确保 schema 一致，但不会通过 dbt model 物化。

### 10.6 分区与聚簇设计 rationale
- 表按日期分区，因为绝大多数查询都会按时间范围过滤
- 表按 `region` 和 `metric_name` 聚簇，因为下游查询经常按这两个维度过滤和聚合
- 聚合表可以进一步降低 API 消费侧的查询成本与延迟

---

## 11. 使用 dbt 进行转换

### dbt Package Dependencies

```yaml
packages:
  - package: dbt-labs/dbt_utils
    version: [">=1.0.0", "<2.0.0"]
```

### dbt 分层
- **`staging/`**：完成规范化，包括类型转换、字段标准化和 surrogate key 生成。通过按分区幂等重建，将 raw 记录转换成规范的 `stg_grid_metrics`
- **`marts/core/`**：事实表和维度表
- **`marts/aggregates/`**：不同时间粒度的消费层聚合表
- **`meta/`**：管道元数据相关的 schema 定义

### dbt 模型物化方式

| 模型 | Materialization | Strategy | Key |
|---|---|---|---|
| `stg_grid_metrics` | `incremental` | `insert_overwrite` | `partition_by: {field: observation_date, data_type: date}` |
| `fct_grid_metrics` | `incremental` | `insert_overwrite` | `partition_by: {field: observation_date, data_type: date}` |
| `dim_region` | `incremental` | `merge` | `unique_key: region` |
| `dim_energy_source` | `incremental` | `merge` | `unique_key: energy_source` |
| `agg_load_hourly` | `table` | full rebuild | — |
| `agg_load_daily` | `table` | full rebuild | — |
| `agg_generation_mix` | `table` | full rebuild | — |
| `agg_top_regions` | `table` | full rebuild | — |

所有增量模型都使用 `insert_overwrite`，并且作用范围限定在每次 DAG run 计算出的受影响 `observation_date` 集合上（见第 9 节的分区重建规则）。这样每次运行只会改动必要分区。

### dbt 要求
- 用 `sources.yml` 声明 `raw.eia_grid_batch` 作为数据源
- 每个模型都必须在 `schema.yml` 中提供描述和测试
- 使用 `dbt docs generate` 生成文档

---

## 12. 数据质量要求

### 12.1 dbt Tests（作为 `dbt build` 的一部分执行）
最低要求包括：
- 对 `metric_surrogate_key`、`observation_timestamp`、`region`、`metric_name` 执行 `not_null`
- 对 `metric_surrogate_key` 执行 `unique`
- 对 `metric_value` 执行 `not_null`
- 对 `metric_name` 执行 `accepted_values` 校验（限制在预期指标类型内）
- 对 `energy_source` 执行 `accepted_values` 校验，取值限定为文档定义的 Voltage Hub 燃料代码集合：`BAT`, `BIO`, `COL`, `GEO`, `HPS`, `HYC`, `NG`, `NUC`, `OES`, `OIL`, `OTH`, `PS`, `SNB`, `SUN`, `UES`, `UNK`, `WAT`, `WNB`, `WND`
- 对 `fct_grid_metrics.region` 和 `dim_region.region` 建立 `relationships`
- 对 `fct_grid_metrics.energy_source` 和 `dim_energy_source.energy_source` 建立 `relationships`
- 保证预期粒度上的唯一性：`(region, observation_timestamp, metric_name, energy_source)`

### 12.2 新鲜度检查

新鲜度不是一个单一状态，而是拆成**两个独立信号**来跟踪：

#### 管道新鲜度（Pipeline Freshness）
衡量管道最近一次成功摄取数据的时间，依据 raw 表中的 `MAX(_ingestion_timestamp)`。

- 通过 `dbt source freshness` 在 `dbt build` 前作为预检查执行
- 用于识别停滞的管道，例如 DAG 没跑起来或提取失败
- 如果 `_ingestion_timestamp` 超过 `error_after` 阈值，则本次运行失败

```yaml
sources:
  - name: raw
    tables:
      - name: eia_grid_batch
        loaded_at_field: _ingestion_timestamp
        freshness:
          warn_after:
            count: 6
            period: hour
          error_after:
            count: 12
            period: hour
```

阈值可配置，应根据实际调度频率进行调整。

#### 数据新鲜度（Data Freshness）
衡量实际观测数据本身是否足够新，依据 `staging.stg_grid_metrics`（或等价的 `marts.fct_grid_metrics`）中的 `MAX(observation_timestamp)`。

- 在 `dbt build` 之后作为 post-build 检查执行
- 用于识别源侧延迟，即管道按计划运行，但 EIA 尚未发布最新数据
- 记录为 `meta.freshness_log` 中的独立字段
- 面向消费者的默认 stale 阈值为 6 小时：当 `checked_at - data_freshness_timestamp <= 6 hours` 时，`data_freshness_status` 为 `fresh`，否则为 `stale`

#### `meta.freshness_log` Schema

| 列 | 类型 | 说明 |
|---|---|---|
| `run_id` | STRING | Airflow `run_id` |
| `pipeline_freshness_timestamp` | TIMESTAMP | 检查时 raw 表中的 `MAX(_ingestion_timestamp)` |
| `data_freshness_timestamp` | TIMESTAMP | 检查时 staging / marts 中的 `MAX(observation_timestamp)` |
| `pipeline_freshness_status` | STRING | `fresh` \| `stale`，基于 `_ingestion_timestamp` 与阈值比较得出 |
| `data_freshness_status` | STRING | `fresh` \| `stale`，基于 `observation_timestamp` 与 6 小时新近度阈值比较得出 |
| `checked_at` | TIMESTAMP | 检查执行时间 |

Serving API 的 `/freshness` 端点会同时返回这两个信号。响应契约中的 `freshness_status` 字段取两者中**更差**的状态；只要其中任意一个为 `stale`，组合状态就为 `stale`。

### 12.3 异常检查

**目标表：** `meta.anomaly_results`

字段：
- `observation_date`（DATE）
- `region`（STRING）
- `metric_name`（STRING）
- `current_value`（FLOAT64）
- `rolling_7d_avg`（FLOAT64）
- `pct_deviation`（FLOAT64）
- `anomaly_flag`（BOOLEAN）
- `run_id`（STRING）
- `checked_at`（TIMESTAMP）

**逻辑：**
- 在 `dbt build` 之后，查询当前周期的 mart 层聚合结果
- 与同一区域、同一指标在过去 7 天的滚动平均值对比
- 滚动基线使用前 7 个自然日，不包含当前 `observation_date`
- 如果可用历史少于 1 天，或滚动平均值为 `0`，则写入 `pct_deviation = NULL` 且 `anomaly_flag = FALSE`
- 若 `|pct_deviation| > 50%`，则标记为异常
- 结果写入 `meta.anomaly_results`

**失败策略：** 异常检测仅作为**告警**，不会导致 DAG 失败。

### 失败策略汇总

| 检查类型 | 触发条件 | DAG 行为 |
|---|---|---|
| dbt test failure | `unique`、`not_null`、`accepted_values`、`relationships` 失败 | **失败** |
| Source freshness `error_after` | 源数据超过 error 阈值 | **失败** |
| Source freshness `warn_after` | 源数据超过 warn 阈值 | **仅告警** |
| Anomaly check | 相比 7 天均值偏差超过 50% | **仅告警** |

---

## 13. Airflow DAG 设计

### 主 DAG
`eia_grid_batch`

### DAG 配置
- **Schedule:** `@hourly`（可配置；这是默认值，不是结构性约束）
- **Start date:** 可配置（初始回填默认从 7 天前开始）
- **Catchup:** `True`
- **Max active runs:** `1`（确保分区级幂等，不发生冲突）
- **Default retries:** `2`
- **Retry delay:** `timedelta(minutes=5)`
- **Dagrun timeout:** `timedelta(hours=2)`

### 任务序列

```
extract_grid_batch              [按时间窗口请求 EIA 数据]
    │
    ▼
land_raw_to_gcs                 [将原始数据持久化到 GCS]
    │
    ▼
load_to_bq_raw                  [BigQuery load job → raw.eia_grid_batch]
    │
    ▼
dbt_source_freshness            [dbt source freshness check]
    │
    ▼
dbt_build                       [staging + marts + tests]
    │
    ▼
check_anomalies                 [异常检测 → meta.anomaly_results]
    │
    ▼
record_run_metrics              [写入运行统计 → meta.run_metrics]
    │
    ▼
update_pipeline_state           [更新 meta.pipeline_state 水位线]
```

### 任务实现细节

| Task | Operator | Timeout | Notes |
|---|---|---|---|
| `extract_grid_batch` | `PythonOperator` | 10 min | 请求 `{{ data_interval_start }}` 到 `{{ data_interval_end }}` 之间的 EIA 数据 |
| `land_raw_to_gcs` | `PythonOperator` | 10 min | 将原始响应上传到 GCS 着陆区 |
| `load_to_bq_raw` | `PythonOperator` | 15 min | 调用 `bigquery.Client.load_table_from_uri()`，对目标分区使用 `WRITE_TRUNCATE` |
| `dbt_source_freshness` | `BashOperator` | 5 min | 执行 `dbt source freshness` |
| `dbt_build` | `BashOperator` | 30 min | 执行 `dbt build` |
| `check_anomalies` | `PythonOperator` | 5 min | 执行异常检测 SQL 并写入 `meta.anomaly_results` |
| `record_run_metrics` | `PythonOperator` | 5 min | 写入运行统计到 `meta.run_metrics` |
| `update_pipeline_state` | `PythonOperator` | 5 min | 更新 `meta.pipeline_state` 中的水位线 |

### 设计要求
- DAG 必须覆盖端到端流程，不保留关键人工步骤
- 每次运行只处理一个由 Airflow `data_interval_start` / `data_interval_end` 派生的时间窗口
- 回填依赖 Airflow 原生 catchup，不自行实现区间计算
- 所有任务统一通过挂载的服务账号凭证进行认证

---

## 14. Serving Layer 设计

### 功能范围
Serving Layer 暴露的是**一组固定模板的分析能力**，包含：
- 面向程序化集成方的 **REST API**
- 面向 LLM Agent 的 **stdio MCP Server（Tools + Resources）**

它本质上是一个**只读、轻量的查询门面**，背后使用预定义查询模板，明确**不是**通用分析查询接口。

**数据范围约束：** Serving Layer **只**能读取预构建的聚合表（`marts.agg_*`）和 meta 表（`meta.*`）。它**不会**查询大事实表（`fct_grid_metrics`），也**不会**在运行时做聚合。所有重计算都在 dbt 构建阶段完成，Serving Layer 只负责检索和过滤预计算结果。

**指标类能力（固定查询模板）：**
- 按区域和时间粒度提供负荷指标，读取 `marts.agg_load_hourly` / `marts.agg_load_daily`
- 按区域 / 时间范围返回能源来源维度的发电结构，读取 `marts.agg_generation_mix`
- 返回总需求最高的区域，读取 `marts.agg_top_regions`

**控制平面能力：**
- `/health`：服务健康检查（仅服务本身，不依赖 BigQuery）
- `/freshness`：管道新鲜度 + 数据新鲜度，读取 `meta.freshness_log`
- `/pipeline/status`：最近一次成功同步窗口及管道状态，读取 `meta.pipeline_state`
- `/anomalies`：最近异常摘要，读取 `meta.anomaly_results`

**MCP Tool 能力：**
- `get_load_trends`：查询指定区域和时间范围内的负荷趋势
- `get_generation_mix`：查询指定区域和时间范围内的发电结构
- `get_top_demand_regions`：查询指定时间范围内的高需求区域排名
- `check_data_freshness`：查询最新的新鲜度状态
- `get_anomalies`：查询异常检测结果
- `get_pipeline_status`：查询最近一次成功管道运行状态

**MCP Resource 能力：**
- `schema://grid-metrics`：暴露可用指标、时间粒度、时间范围和工具说明
- `status://data-quality`：暴露当前新鲜度、管道状态和异常摘要
- `schema://regions`：暴露可用区域 code、名称和别名
- `schema://energy-sources`：暴露可用能源类型 code 与说明

> **说明：** `meta.run_metrics` 保存的是内部管道遥测信息（如加载行数、处理字节数、耗时等），用于运维排障，但不作为公开 API 暴露。

### 响应契约
每个数据类端点的响应都必须带上以下元数据字段：
- `data_as_of`：最近一次 `data_freshness_timestamp`（来自 `meta.freshness_log`）
- `pipeline_run_id`：最近一次成功管道运行 ID（来自 `meta.pipeline_state.last_successful_run_id`）
- `freshness_status`：组合状态，取值为 `fresh` | `stale` | `unknown`，由 `meta.freshness_log` 中 `pipeline_freshness_status` 和 `data_freshness_status` 的较差者推导而来

MCP Tool 的响应契约在保留上述元数据语义的基础上，还应额外满足以下要求：
- 返回结果优先面向 LLM 消费，默认包含 `summary`、`highlights`、`data`、`metadata`
- `summary` 用于给出单次工具调用的主要结论
- `highlights` 用于给出 2 到 5 条高信号要点，减少模型自行二次归纳的负担
- `data` 保留结构化原始结果，便于模型在需要时引用细节
- `metadata` 延续 Serving API 的 `data_as_of`、`pipeline_run_id` 和 `freshness_status` 语义
- 校验失败时返回统一错误结构，而不是底层异常堆栈

### 约束
- **仅支持固定模板端点 / 工具**：每个 REST 端点或 MCP Tool 都映射到针对特定 `agg_*` 或 `meta.*` 表的预定义查询
- **禁止查询事实表**：Serving Layer 不直接访问 `fct_grid_metrics`，所有指标必须来自预聚合表
- **禁止运行时再聚合**：查询时不做 `GROUP BY`、`SUM()` 或窗口函数，返回预构建行并配合简单 `WHERE` 过滤
- **不提供即席查询能力**：不允许自由选择指标、任意分组或暴露动态 SQL
- **用户过滤能力受限于预定义参数**：如区域、时间范围、粒度
- 对 BigQuery **只读**
- **可选简单 TTL 缓存**：仅内存实现，不接 Redis
- **记录请求级日志和 MCP Tool 调用日志**，用于可观测性
- **不做数据处理**：所有转换都在 ELT 层完成
- **不拆分成微服务**：以单一可部署服务交付
- **MCP 仅支持 `stdio` transport**：不提供 HTTP / SSE 模式
- **MCP Tools 必须为 LLM 友好设计**：描述中要说明“何时使用”，参数命名优先使用自然语言可理解的字段名和 enum，而不是内部 code

> **未来升级路径：** 如果后续 BigQuery 查询延迟或成本在规模扩大后成为问题，可以引入基于 PostgreSQL 的 serving store，作为 aggregate 和 meta 表的物化只读副本。但这不属于当前设计范围。

---

### 14.1 Python FastAPI Serving Layer

**模块结构：**

| Package | Responsibility |
|---|---|
| `routers/` | 路由定义和端点处理 |
| `services/` | 业务逻辑、查询编排、缓存协作 |
| `repositories/` | BigQuery 客户端访问与查询执行 |
| `schemas/` | Pydantic 请求 / 响应模型 |
| `cache/` | 内存缓存实现与 TTL 管理 |
| `config/` | 应用配置、BigQuery client 初始化 |
| `health/` | 健康检查与状态端点实现 |
| `exceptions/` | 自定义异常与错误处理 |

**技术栈：**
- Python 3.11+
- FastAPI
- Pydantic v2
- BigQuery Python client SDK
- `cachetools` 或手写 TTL dict（可选内存缓存）

---

### 14.2 本地部署（Serving Layer）

Serving API 作为**独立进程**运行，不依附于 Airflow 容器。Serving 服务与项目其它部分共享同一份 `.env` 和 GCP 凭证。

**环境与凭证：**
- 服务从项目根目录 `.env`（或等价环境变量）中读取 `GCP_PROJECT_ID`、`BQ_DATASET_MARTS`、`BQ_DATASET_META`
- GCP 认证使用与其它组件相同的服务账号 JSON 密钥，路径由 `GOOGLE_APPLICATION_CREDENTIALS` 指定
- BigQuery client 通过 Application Default Credentials 初始化，因此在进程启动前必须正确设置服务账号密钥路径
- Airflow 的运行指标采集会从 `DBT_RUN_RESULTS_PATH` 读取 dbt 执行元数据，默认路径为 `/opt/airflow/dbt/target/run_results.json`

**本地启动方式：**
- 安装依赖：`cd serving-fastapi && uv sync`
- 本地运行：`uvicorn app.main:app --host 0.0.0.0 --port 8090`
- 或通过 Docker：`docker build -t eia-serving-fastapi ./serving-fastapi && docker run --env-file .env -v $(pwd)/keys:/keys -p 8090:8090 eia-serving-fastapi`
- 默认端口：`8090`（可通过 `PORT` 环境变量配置）
- 健康检查：`curl http://localhost:8090/health`

**BigQuery 连接约束：**
- 使用 `GOOGLE_APPLICATION_CREDENTIALS` 指定路径上的服务账号密钥初始化 BigQuery client
- 连接的项目由 `GCP_PROJECT_ID` 指定
- 所有查询都必须限制在 `marts` 和 `meta` 数据集中，Serving Layer 不查询 `raw` 或 `staging`

**Docker Compose 集成（可选）：**
- Serving 服务可以作为附加服务加入项目的 `docker-compose.yml`
- 即便加入 Compose，也应挂载同一个 `keys/` 卷，并读取同一份 `.env`

**Serving 所需 `.env` 变量：**
```env
GCP_PROJECT_ID=your-gcp-project-id
GOOGLE_APPLICATION_CREDENTIALS=/path/to/keys/service-account.json
BQ_DATASET_MARTS=marts
BQ_DATASET_META=meta
PORT=8090  # optional, default 8090
```

---

### 14.3 stdio MCP Server

MCP Server 作为独立进程运行，并通过 **stdio transport** 与 LLM Agent 通信。它与 Serving API 一样，共享同一套 `.env`、GCP 凭证以及查询逻辑，但其接口形态不是 HTTP 端点，而是面向 Agent 的 Tools 和 Resources。

**设计目标：**
- 让 Agent 在不暴露任意查询能力的前提下，安全访问固定分析能力
- 复用 Serving Layer 已有的查询逻辑、参数校验与新鲜度语义
- 通过 Resource 先提供上下文，再通过 Tool 执行查询
- 返回对 LLM 更易消化的结构化结果，而不仅是原始行数据

**Transport 约束：**
- 仅支持 **`stdio`**
- 不暴露额外网络端口
- 不支持 HTTP / SSE 等 MCP transport

**Tool 列表：**

| Tool | 用途 | 对应 REST 能力 |
|---|---|---|
| `get_load_trends` | 查询指定区域、时间范围和粒度下的负荷趋势；适用于回答“某区域负荷如何变化” | `/metrics/load` |
| `get_generation_mix` | 查询指定区域和时间范围内的发电结构；适用于回答“该区域主要由哪些能源构成” | `/metrics/generation-mix` |
| `get_top_demand_regions` | 查询指定时间范围内的高需求区域排名；适用于回答“哪些区域需求最高” | `/metrics/top-regions` |
| `check_data_freshness` | 查询最新数据新鲜度；适用于回答“数据是不是最新的”或在分析前做前置检查 | `/freshness` |
| `get_anomalies` | 查询异常检测结果；适用于回答“最近有没有明显异常” | `/anomalies` |
| `get_pipeline_status` | 查询最近一次成功管道运行状态；适用于回答“管道最近一次成功跑到哪里” | `/pipeline/status` |

**Tool 描述要求：**
- 每个 Tool 的描述必须明确说明“什么时候应该使用这个工具”
- 描述中应指出与相邻 Tool 的边界，避免 Agent 在相似问题上误选工具
- 描述应避免只写“查询某表”或“返回某字段”这类面向实现的说明

**参数设计要求：**
- 参数名必须面向自然语言理解，例如 `region`、`start_date`、`end_date`、`time_granularity`、`top_n`、`only_flagged`
- Enum 取值应使用 `daily`、`hourly`、`fresh`、`stale` 这类自然语言词汇
- 不直接暴露 BigQuery 表名、列名或内部 code 作为接口参数
- `region` 应尽量支持区域 code 与常见区域名称，并在服务端做规范化

**Tool 返回要求：**
- 默认返回 `summary`、`highlights`、`data`、`metadata`
- `summary` 应总结本次查询的主要结论
- `highlights` 应提取最值得模型引用的要点
- `data` 应保留结构化明细，避免只返回文本摘要
- `metadata` 必须保留 `data_as_of`、`pipeline_run_id`、`freshness_status`

**Resource 列表：**

| Resource | 用途 |
|---|---|
| `schema://grid-metrics` | 暴露可用工具、支持的指标类型、时间粒度和可查询日期范围 |
| `status://data-quality` | 暴露当前数据质量状态、新鲜度状态、管道状态和异常摘要 |
| `schema://regions` | 暴露区域 code、展示名和常见别名，帮助 Agent 在调用 Tool 前选择合法 region |
| `schema://energy-sources` | 暴露能源类型 code 与说明，帮助 Agent 理解发电结构结果 |

**Resource 设计要求：**
- Resource 的职责是为 Tool 调用提供前置上下文
- Agent 应能够通过 Resource 了解可用数据范围、参数候选值和当前数据状态
- Resource 应优先承载低基数、稳定、可缓存的信息，而不是大规模时序数据

**与 Serving API 的关系：**
- MCP Server 与 REST API 共享相同的数据来源：`marts.agg_*` 和 `meta.*`
- MCP Server 与 REST API 应复用相同的业务校验和新鲜度语义
- MCP Server 不应通过 HTTP 再调用 Serving API，而应共享底层查询逻辑
- MCP Server 可以在响应层增加 `summary` 和 `highlights` 这类 LLM 友好包装，但不得改变底层指标口径

---

## 15. 可观测性与运行指标

### 运行指标表
BigQuery 表：`meta.run_metrics`

字段：
- `run_id`（STRING）：Airflow `run_id`
- `dag_id`（STRING）
- `execution_date`（TIMESTAMP）
- `window_start`（TIMESTAMP）：本次处理时间窗口的开始时间
- `window_end`（TIMESTAMP）：本次处理时间窗口的结束时间
- `rows_loaded`（INT64）
- `dbt_models_passed`（INT64）
- `dbt_tests_passed`（INT64）
- `dbt_tests_failed`（INT64）
- `bytes_processed`（INT64）：来自 BigQuery Job metadata
- `duration_seconds`（FLOAT64）
- `status`（STRING）：`success` | `failed`
- `created_at`（TIMESTAMP）

`dbt_models_passed`、`dbt_tests_passed`、`dbt_tests_failed` 和 `bytes_processed` 这些字段，来自 `DBT_RUN_RESULTS_PATH` 指向的 dbt `run_results.json` 产物。

---

## 16. 使用 GitHub Actions 的 CI

### Workflows

| Workflow | Trigger | Steps |
|---|---|---|
| `lint.yml` | Push / PR | 对 dbt SQL 执行 `sqlfluff lint`，对 Python 执行 `ruff` |
| `dbt_compile.yml` | Push / PR | 执行 `dbt deps && dbt parse --target ci --no-populate-cache` |
| `terraform_validate.yml` | Push / PR to `terraform/` | 执行 `terraform fmt -check`、`terraform validate` |

### CI dbt Profile

```yaml
voltage_hub:
  target: dev
  outputs:
    dev:
      type: bigquery
      method: service-account
      project: "{{ env_var('GCP_PROJECT_ID') }}"
      dataset: "{{ env_var('BQ_DATASET_STAGING', 'staging') }}"
      keyfile: "{{ env_var('GCP_SERVICE_ACCOUNT_KEY_PATH') }}"
      threads: 4
    ci:
      type: bigquery
      method: oauth
      project: "ci-placeholder"
      dataset: "ci_placeholder"
      threads: 1
```

CI 只做语法和代码质量校验，不连接 GCP，也不执行真实查询。对于 BigQuery adapter，CI 中的 dbt 工作流使用离线 `dbt parse`，而不是 `dbt compile`，因为后者可能触发 adapter cache 填充与仓库探测行为。

---

## 17. 验证标准

以下维度都必须在开发过程中得到验证，并且都具有可客观检验的标准。

### 基础设施
- `terraform apply` 能无报错创建 GCS bucket、BigQuery 数据集（`raw`、`staging`、`marts`、`meta`）、服务账号和 IAM 配置
- `terraform destroy` 能清理全部资源
- Docker Compose 能正常启动所有服务，Airflow health endpoint 返回 healthy

### ELT 管道
- DAG 能出现在 Airflow UI 中，且不存在 import error
- 针对配置好的时间窗口，增量批处理提取可以成功完成
- 原始数据能按预期路径落地到 GCS
- `raw.eia_grid_batch` 中包含预期批次日期的数据
- `dbt build` 完成且测试失败数为 0
- `staging.stg_grid_metrics` 中存在已规范化的数据
- Mart 表（`fct_grid_metrics`、`dim_region`、`dim_energy_source`）已写入数据
- Aggregate 表中存在预期时间范围的数据
- `meta.pipeline_state` 水位线被正确更新
- `meta.run_metrics` 为每次成功运行写入一条记录
- 对已完成时间窗口进行重跑 / 回填时，结果保持幂等

### 数据质量
- 所有 dbt tests 通过
- `dbt source freshness` 返回 `pass` 或 `warn`
- 每次运行后 `meta.anomaly_results` 都有结果写入

### Serving 接口（REST + MCP）
- Health endpoint 返回 `200`
- Freshness endpoint 能返回最新数据时间戳和状态
- Pipeline status endpoint 能返回最近一次运行信息
- 指标类端点能返回符合 schema 约束的有效响应
- 响应中包含 `data_as_of`、`pipeline_run_id` 和 `freshness_status` 元数据
- MCP Server 能以 `stdio` 模式启动并暴露预期的 Tools / Resources
- MCP Tool 调用能返回符合约定结构的有效响应
- MCP Tool 响应包含 `summary`、`highlights`、`data`、`metadata`
- MCP Tool test 全部通过

### CI
- 所有 CI workflows 在干净 PR 上均通过

---

## 18. 非功能性需求

### 19.1 性能

| Requirement | Target |
|---|---|
| 单批次端到端完成时间 | < 15 分钟 |
| 7 天回填总耗时 | < 8 小时（顺序执行） |
| `dbt build` 执行时长 | < 5 分钟（增量运行） |
| Serving API 响应时间 | 缓存命中 < 2 秒，未命中 < 5 秒 |
| MCP Tool 响应时间 | 与对应 Serving API 查询同级，目标 < 5 秒 |

### 19.2 可靠性

| Requirement | Detail |
|---|---|
| 任务级重试 | 最多 2 次重试，间隔 5 分钟 |
| API 重试 | 每个任务最多 3 次带退避重试 |
| DAG 超时 | 最长 2 小时 |
| 幂等性 | 所有任务都可安全重跑，不造成数据损坏 |

### 19.3 安全性

| Requirement | Detail |
|---|---|
| 凭证存储 | 服务账号密钥以 volume 方式挂载，绝不写入镜像 |
| `.gitignore` | 必须包含 `keys/*.json`、`.env`、`terraform.tfstate*` |
| 服务账号权限 | 最低要求：`bigquery.dataEditor`、`bigquery.jobUser`、`storage.objectAdmin` |
| 网络暴露 | 仅暴露 `localhost:8080`（Airflow UI）和 Serving API 端口；MCP 仅通过 `stdio` 通信，不额外暴露端口 |

### 19.4 可观测性

| Requirement | Detail |
|---|---|
| 运行指标 | 每次运行都写入 `meta.run_metrics` |
| 异常结果 | 每次运行都写入 `meta.anomaly_results` |
| 新鲜度 | 通过 meta 表、Serving API 与 MCP Tool 三重暴露 |
| 日志 | Airflow UI 日志 + Serving API 请求日志 + MCP Tool 调用日志 |

### 19.5 可维护性

| Requirement | Detail |
|---|---|
| 代码检查 | SQL 使用 `sqlfluff`（BigQuery dialect），Python 使用 `ruff` |
| dbt 文档 | 每个模型和列都必须在 `schema.yml` 中有 `description` |
| Terraform 格式化 | CI 中强制执行 `terraform fmt` |

### 19.6 成本约束

| Requirement | Detail |
|---|---|
| BigQuery 查询预算 | 分析查询扫描量 < 1 GB（依赖分区裁剪） |
| GCS 存储 | 为复现保留原始文件，在预期规模下月成本 < 1 美元 |
| 防止失控回填 | `max_active_runs=1` 防止无限并发执行 |

---

## 19. 推荐实施顺序

建议按以下阶段推进开发：

1. **先完成 ELT 骨架和仓库分层**：包括 Terraform 基础设施、Airflow DAG 骨架、GCS raw 落地、BigQuery raw/staging/marts，以及 dbt 模型与测试。这是后续所有能力的基础。

2. **再补齐 Meta Layer、新鲜度与异常检测**：包括 `meta.pipeline_state`、`meta.run_metrics`、`meta.freshness_log`、`meta.anomaly_results`，并把新鲜度检查和异常检测接入 DAG。

3. **最后实现 Serving Layer**：先完成 FastAPI 版本 Serving API，再复用同一查询逻辑实现 `stdio` MCP Server，对接 marts 和 meta 表，并按验证标准逐项校验 REST 端点和 MCP Tools。

---

## 20. 后续方向

### 可视化层（Dashboard）

后续可选引入一个可视化层，例如 Tableau，直接连接 mart 数据集。

**当前状态：** 不属于本期实现范围。可视化层的主要用途是验证 mart 的可用性，并支持对数据产品进行补充性的可视化探索。

**数据源建议：**
- `marts.agg_load_daily`
- `marts.agg_load_hourly`
- `marts.agg_generation_mix`
- `marts.agg_top_regions`
- `meta.anomaly_results`（用于运维类指标）

**建议视图：**
- 区域负荷趋势（时间序列）
- 按能源类型拆解的发电结构
- 高需求区域排行（柱状图）
- 异常摘要指标卡

**范围说明：** 可视化层与 Serving API 一样，直接消费 marts 和 meta 表，不需要为其额外增加新的数据模型或聚合表。
