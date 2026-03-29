# 使用指南 — VoltageHub

---

## 1. 前置要求

开始之前，请确保以下工具和凭证已就绪：

| 依赖项 | 说明 |
|---|---|
| GCP 项目 | 需开通计费 |
| Service Account JSON 密钥 | 需具备 GCS 和 BigQuery 访问权限 |
| EIA API Key | 在 [EIA Open Data](https://www.eia.gov/opendata/) 注册获取 |
| Docker + Docker Compose | v2 CLI（`docker compose`） |
| Python 3.11 | 用于宿主机 lint 和测试 |
| `uv` | Python 包管理器（[文档](https://docs.astral.sh/uv/)） |
| Terraform 1.5+ | 用于 GCP 基础设施部署 |

**项目默认值**（以下各节均使用这些值）：

| 配置项 | 值 |
|---|---|
| GCP Project ID | `voltage-hub-dev` |
| Region | `us-central1` |
| Raw Bucket | `voltage-hub-raw` |

---

## 2. 项目配置

### 2.1 克隆仓库并创建 `.env`

```bash
git clone <your-repo-url>
cd voltage-hub
cp .env.example .env
```

### 2.2 环境变量

打开 `.env`，根据实际环境填写各变量值：

```env
# GCP
GCP_PROJECT_ID=voltage-hub-dev
GCP_REGION=us-central1
GCP_SERVICE_ACCOUNT_KEY_PATH=/opt/airflow/keys/service-account.json
GOOGLE_APPLICATION_CREDENTIALS=/opt/airflow/keys/service-account.json

# GCS
GCS_BUCKET_NAME=voltage-hub-raw

# BigQuery
BQ_DATASET_RAW=raw
BQ_DATASET_STAGING=staging
BQ_DATASET_MARTS=marts
BQ_DATASET_META=meta
BQ_DATASET_RAW_SAMPLE=raw_sample
BQ_DATASET_STAGING_SAMPLE=staging_sample
BQ_DATASET_MARTS_SAMPLE=marts_sample
BQ_DATASET_META_SAMPLE=meta_sample

# Airflow
AIRFLOW__CORE__EXECUTOR=LocalExecutor
AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=postgresql+psycopg2://airflow:airflow@postgres:5432/airflow
AIRFLOW__CORE__LOAD_EXAMPLES=False

# Pipeline
BACKFILL_DAYS=7
SAMPLE_MODE=false
DBT_RUN_RESULTS_PATH=/opt/airflow/dbt/target/run_results.json

# EIA
EIA_API_KEY=your-eia-api-key

# Serving API
PORT=8090
CACHE_TTL_SECONDS=300
```

需要注意的变量：

- **`PORT`** — Serving API 端口，请勿改名为 `SERVER_PORT`。
- **`GCS_BUCKET_NAME`** — 原始数据落盘 bucket。
- **`SAMPLE_MODE`** — 设为 `true` 可将所有写入路由到隔离的 `*_sample` 数据集（详见[附录 A](#附录-a-sample-mode)）。

### 2.3 Service Account 密钥

运行时需要的 Service Account 将在 3.1 节由 Terraform 自动创建。**完成 3.1 节部署后**，请手动执行：

1. 在 GCP 控制台下载该 Service Account 的 JSON 密钥。
2. 将文件重命名为 `service-account.json`，并放置到：
   ```
   keys/service-account.json
   ```

Docker Compose 会将该文件挂载到容器的 `/opt/airflow/keys/service-account.json`。`.env` 中的两个凭证变量应指向这个容器内路径。

---

## 3. 部署与启动

所有操作通过 `make` 完成。Makefile 封装了底层的 `docker compose` 命令，无需直接调用 Docker。

### 3.1 基础设施部署（Terraform）

```bash
make terraform-init
make terraform-apply
```

该步骤会创建：

- 用于原始数据落盘的 GCS bucket
- BigQuery 数据集：`raw`、`staging`、`marts`、`meta`
- 运行时 service account 及 IAM 权限绑定

### 3.2 启动服务

```bash
make build
make up
```

启动后包含四个容器：

| 服务 | 地址 |
|---|---|
| Airflow UI | [http://localhost:8080](http://localhost:8080) |
| FastAPI 接口文档 | [http://localhost:8090/docs](http://localhost:8090/docs) |
| FastAPI 健康检查 | [http://localhost:8090/health](http://localhost:8090/health) |
| PostgreSQL | 内部服务（Airflow 元数据库） |

Airflow 默认账号：`admin` / `admin`

### 3.3 安装 dbt 依赖

```bash
make dbt-deps
```

首次运行 pipeline 或 dbt 相关命令前需执行一次，用于在 Airflow 容器内安装 dbt 外部包。

---

## 4. 运行 Pipeline

### 4.1 触发 DAG

主 DAG 名为 `eia_grid_batch`。可在 Airflow UI 中手动触发，也可通过命令行运行 backfill：

```bash
make backfill START_DATE=2026-03-27T00:00:00+00:00 END_DATE=2026-03-28T00:00:00+00:00
```

每次运行按以下顺序依次执行：

```
extract_grid_batch
→ land_raw_to_gcs
→ load_to_bq_raw
→ dbt_source_freshness
→ dbt_build
→ check_anomalies
→ record_run_metrics
→ update_pipeline_state
```

DAG 启用了 `catchup=True` 且限制 `max_active_runs=1`，因此 backfill 窗口会按顺序逐一执行，不会产生分区写入冲突。

### 4.2 Serving API

Serving API（`serving-fastapi`）随 `make up` 一起启动，本地使用无需额外操作。

如需脱离 Docker 独立运行：

```bash
cd serving-fastapi
uv sync
uv run uvicorn app.main:app --host 0.0.0.0 --port 8090
```

快速验证：

```bash
curl http://localhost:8090/health
curl http://localhost:8090/pipeline/status
curl "http://localhost:8090/metrics/load?region=US48&start_date=2026-03-27&end_date=2026-03-27&granularity=daily"
```

---

## 5. 验证

至少完成一次 DAG 运行后，逐项确认以下内容：

| 检查项 | 验证方式 |
|---|---|
| Terraform 完成 | `make terraform-apply` 无报错退出 |
| 服务正常运行 | `make up` 后运行 `docker compose -f docker/docker-compose.yml ps` — 全部容器 healthy |
| Airflow 可访问 | 打开 [http://localhost:8080](http://localhost:8080) |
| dbt 依赖已安装 | `make dbt-deps` 无报错退出 |
| DAG 运行成功 | Airflow UI 中 `eia_grid_batch` 显示已完成的运行 |
| BigQuery 有数据 | `raw`、`staging`、`marts`、`meta` 数据集中包含数据 |
| `/health` | `curl http://localhost:8090/health` → `200` |
| `/freshness` | 返回 `pipeline_freshness_timestamp` 和 `data_freshness_timestamp` |
| `/pipeline/status` | 返回最新成功窗口和 `last_successful_run_id` |
| 数据接口 | 返回预计算的分析结果 |

---

## 6. 测试

### 6.1 测试路径总览

项目包含六条测试路径，通过环境变量切换：

| 路径 | 范围 | 适用场景 | 是否连接 GCP |
|---|---|---|---|
| **Unit Tests** | 抽取、加载、freshness、anomaly 逻辑；Serving API 路由和服务层 | 每次改动后 | 否 |
| **E2E Smoke** | 单窗口 pipeline 全链路：GCS → BigQuery → dbt → marts → meta；跨 UTC 午夜日期边界场景 | pipeline 相关改动后 | 是 |
| **E2E Heavy** | 幂等重跑 + 多窗口 backfill 验证 | 阶段性验收前 | 是 |
| **E2E Failure-Path** | Freshness warn / error 路径（使用隔离临时数据集） | 验证故障处理逻辑时 | 是 |
| **Serving API Integration** | 全部 FastAPI 端点对真实 BigQuery 数据的验证 | Pipeline 跑通后 | 是 |
| **CI** | Ruff + SQLFluff + Unit Tests + dbt parse + Terraform validate | push / PR 时自动运行 | 否 |

### 6.2 Unit Tests

```bash
uv run pytest tests/unit
```

覆盖 pipeline 任务逻辑（抽取请求构造、GCS 路径生成、BigQuery load 配置、重试行为、freshness 状态判断、anomaly 检测）以及 Serving API 单元测试（路由、服务层、校验逻辑）。全部使用 mock，不需要 GCP 连接。

### 6.3 E2E Tests

三条 E2E 路径均位于 `tests/integration/test_pipeline_e2e.py`，通过环境变量控制。

**Smoke**（默认集成路径）：

```bash
set -a; source .env; set +a
VOLTAGE_HUB_RUN_PIPELINE_TESTS=1 .venv/bin/pytest -rs tests/integration/test_pipeline_e2e.py
```

运行单窗口全链路抽取 + 跨 UTC 午夜日期边界场景，适合日常改动后的快速回归。

**Heavy**（包含 smoke）：

```bash
set -a; source .env; set +a
VOLTAGE_HUB_RUN_PIPELINE_TESTS=1 \
VOLTAGE_HUB_RUN_HEAVY_PIPELINE_TESTS=1 \
  .venv/bin/pytest -rs tests/integration/test_pipeline_e2e.py
```

在 smoke 基础上增加幂等重跑和多窗口 backfill 验证。backfill 默认为 2 个 hourly 窗口，可通过以下变量调整：

```bash
VOLTAGE_HUB_TEST_BACKFILL_HOURS=12    # 必须 ≥ 2，整数
VOLTAGE_HUB_TEST_BACKFILL_END_BOUNDARY=2026-03-27T00:00:00+00:00  # 必须对齐到整点
```

Heavy 测试运行后会保留 GCS / BigQuery 中的数据（不做自动清理），这些数据可直接用于后续开发。

**Failure-Path**（包含 smoke）：

```bash
set -a; source .env; set +a
VOLTAGE_HUB_RUN_PIPELINE_TESTS=1 \
VOLTAGE_HUB_RUN_FAILURE_PATH_PIPELINE_TESTS=1 \
  .venv/bin/pytest -rs tests/integration/test_pipeline_e2e.py
```

创建隔离的临时 BigQuery 数据集，通过修改 `_ingestion_timestamp` 触发 freshness 的 warn 和 error 路径，测试结束后自动清理。不会影响共享开发数据。

**运行全部 E2E 路径**：

```bash
set -a; source .env; set +a
VOLTAGE_HUB_RUN_PIPELINE_TESTS=1 \
VOLTAGE_HUB_RUN_HEAVY_PIPELINE_TESTS=1 \
VOLTAGE_HUB_RUN_FAILURE_PATH_PIPELINE_TESTS=1 \
  .venv/bin/pytest -rs tests/integration/test_pipeline_e2e.py
```

**推荐执行顺序**：

1. 日常开发 → unit tests + E2E smoke
2. 阶段验收 → E2E heavy
3. 故障路径验证 → E2E failure-path（可独立运行）

### 6.4 Serving API Integration Tests

```bash
set -a; source .env; set +a
VOLTAGE_HUB_RUN_PIPELINE_TESTS=1 .venv/bin/pytest -rs tests/integration/test_serving_api.py
```

前提条件：BigQuery 中已有 pipeline 产出的数据。测试覆盖全部端点（`/health`、`/freshness`、`/pipeline/status`、`/anomalies`、`/metrics/*`），包括响应元数据验证和错误处理。

### 6.5 CI

三条 GitHub Actions workflow 在 push 和 PR 时自动运行：

| Workflow | 检查内容 |
|---|---|
| **Lint** | Ruff + SQLFluff + pipeline unit tests + Serving API unit tests |
| **dbt Parse** | `dbt deps` + `dbt parse --target ci`（离线解析，不连接 GCP） |
| **Terraform Validate** | `terraform fmt -check` + `terraform validate` |

CI 不连接 GCP，仅做语法和结构校验。

---

## 附录 A: Sample Mode

Sample mode 将所有 pipeline 写入路由到隔离的 `*_sample` BigQuery 数据集，用于轻量验证而不影响主数据仓库。

在 `.env` 中启用：

```env
SAMPLE_MODE=true
```

启用后的影响：

- DAG 将写入 `raw_sample`、`staging_sample`、`marts_sample`、`meta_sample` 而非主数据集
- dbt 使用 `sample` target
- 调度器可见的历史窗口范围会缩窄，便于快速验证

Sample mode 仍使用相同的 GCS bucket 和落盘路径，隔离仅作用于 BigQuery 数据集。

---

## 附录 B: 常见问题排查

**凭据路径错误**
请确认 `keys/service-account.json` 存在于本地，且 `.env` 中的路径指向 `/opt/airflow/keys/service-account.json`。运行 `docker compose -f docker/docker-compose.yml ps` 确认容器处于 healthy 状态。

**IAM 权限不足**
运行时 service account 需要以下角色：`bigquery.dataEditor`、`bigquery.jobUser`、`storage.objectAdmin`。

**dbt 命令报缺少依赖包**
请先运行 `make dbt-deps`。

**Airflow UI 中看不到 DAG**
查看容器日志：`docker compose -f docker/docker-compose.yml logs airflow-webserver` 和 `docker compose -f docker/docker-compose.yml logs airflow-scheduler`。确认 `airflow/dags/` 目录是否正确挂载。

**BigQuery 数据集不存在**
重新运行 `make terraform-apply`，并在 GCP 控制台确认数据集已创建。

**API 返回空数据**
请确保至少有一次 DAG 运行成功完成，并确认查询的日期范围内 marts 表中存在数据。

**Sample Mode 混淆**
启用 `SAMPLE_MODE=true` 后，所有读写都指向 `*_sample` 数据集。请检查对应的 sample 数据集，而非主数据集。

---

## 相关文档

- [SPEC.md](SPEC.md)
- [ARCHITECTURE.md](ARCHITECTURE.md)
- [INTERFACES.md](INTERFACES.md)
- [TESTING.md](TESTING.md)
- [CHANGELOG.md](CHANGELOG.md)
