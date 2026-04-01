# 使用指南 — VoltageHub

---

## 1. 克隆仓库

```bash
git clone <your-repo-url>
cd voltage-hub
cp .env.example .env
```

---

## 2. 配置 `.env`

在 `.env` 中填写以下必填项：

- `GCP_PROJECT_ID` — Terraform、Airflow 和服务层使用的 GCP 项目
- `GCS_BUCKET_NAME` — 原始数据落盘使用的 GCS bucket，名称需全局唯一
- `EIA_API_KEY` — EIA 数据接入所需的 API key


`.env.example` 中其余变量均为可选项。

---

## 3. 部署基础设施（Terraform）

```bash
make terraform-init
make terraform-apply
```

此步骤会创建 GCS bucket、BigQuery 数据集以及运行时 service account。

---

## 4. 下载 Service Account Key

Terraform 执行完成后，从 GCP 下载运行时 service account 的 JSON key，并放入 `keys/` 目录。

将文件重命名为：

```text
keys/service-account.json
```

如需使用 MCP，请将 `MCP_GOOGLE_APPLICATION_CREDENTIALS` 设置为该文件在本机上的绝对路径。

---

## 5. 启动 Docker 服务

```bash
make build
make up
```

服务地址：

| 服务 | 地址 |
|---|---|
| Airflow UI | [http://localhost:8080](http://localhost:8080) |
| FastAPI 接口文档 | [http://localhost:8090/docs](http://localhost:8090/docs) |
| FastAPI 健康检查 | [http://localhost:8090/health](http://localhost:8090/health) |
| PostgreSQL | 内部服务（Airflow 元数据库） |

Airflow 默认账号：`admin` / `admin`

---

## 6. 运行 Pipeline

主 DAG 名为 `eia_grid_batch`。可在 Airflow UI 中手动触发，也可通过命令行运行 backfill：

```bash
make backfill START_DATE=2026-03-27T00:00:00+00:00 END_DATE=2026-03-28T00:00:00+00:00
```

---

## 7. 可选：MCP Server

MCP Server 以 **stdio** 进程的形式供 AI Agent 应用接入。

在 `mcp/` 目录中安装依赖并启动：

```bash
cd mcp
uv sync
uv run voltagehub-mcp
```

MCP 配置示例：

```json
{
  "mcpServers": {
    "voltagehub": {
      "command": "uv",
      "args": ["run", "voltagehub-mcp"],
      "cwd": "/absolute/path/to/voltage-hub/mcp",
      "env": {
        "MCP_GCP_PROJECT_ID": "voltage-hub-dev",
        "MCP_GOOGLE_APPLICATION_CREDENTIALS": "/absolute/path/to/voltage-hub/keys/service-account.json"
      }
    }
  }
}
```

请在 `.env` 或 AI Agent 应用的 MCP 配置中设置 `MCP_GCP_PROJECT_ID` 和 `MCP_GOOGLE_APPLICATION_CREDENTIALS`。其中，`MCP_GOOGLE_APPLICATION_CREDENTIALS` 应填写为 `keys/service-account.json` 在本机上的绝对路径。

---

## 8. 测试

### 8.1 测试路径总览

项目包含八条测试路径；其中部分路径通过环境变量切换：

| 路径 | 范围 | 适用场景 | 是否连接 GCP |
|---|---|---|---|
| **Unit Tests** | 抽取、加载、freshness、anomaly 逻辑；Serving API 路由和服务层 | 每次改动后 | 否 |
| **CI** | Ruff + SQLFluff + Unit Tests + dbt parse + Terraform validate | push / PR 时自动运行 | 否 |
| **MCP Tests** | MCP 配置读取、adapter 契约、server 注册、stdio 端到端行为 | MCP 相关改动后 | 否 |
| **Sample Mode** | 将 pipeline 输出写入隔离的 `*_sample` 数据集 | 轻量验证且不影响主数据集 | 是 |
| **E2E Smoke** | 单窗口 pipeline 全链路：GCS → BigQuery → dbt → marts → meta；跨 UTC 午夜日期边界场景 | pipeline 相关改动后 | 是 |
| **E2E Heavy** | 幂等重跑 + 多窗口 backfill 验证 | 阶段性验收前 | 是 |
| **E2E Failure-Path** | Freshness warn / error 路径（使用隔离临时数据集） | 验证故障处理逻辑时 | 是 |
| **Serving API Integration** | 全部 FastAPI 端点对真实 BigQuery 数据的验证 | Pipeline 跑通后 | 是 |

### 8.2 Unit Tests

```bash
uv run pytest tests/unit
```

覆盖 pipeline 任务逻辑（抽取请求构造、GCS 路径生成、BigQuery load 配置、重试行为、freshness 状态判断、anomaly 检测）以及 Serving API 单元测试（路由、服务层、校验逻辑）。全部使用 mock，不需要 GCP 连接。

### 8.3 CI

三条 GitHub Actions workflow 在 push 和 PR 时自动运行：

| Workflow | 检查内容 |
|---|---|
| **Lint** | Ruff + SQLFluff + pipeline unit tests + Serving API unit tests + MCP tests |
| **dbt Parse** | `dbt deps` + `dbt parse --target ci`（离线解析，不连接 GCP） |
| **Terraform Validate** | `terraform fmt -check` + `terraform validate` |

CI 不连接 GCP，仅做语法和结构校验。

### 8.4 MCP Tests

```bash
cd mcp
uv sync --dev
uv run pytest -q tests
```

覆盖 MCP 专用配置读取、adapter 契约、文档中定义的 tool / resource 注册，以及 stdio 端到端行为。这些测试使用本地 stub 运行，不需要连接 GCP。

### 8.5 Sample Mode

Sample Mode 会将 pipeline 的写入重定向到隔离的 `*_sample` BigQuery 数据集，方便进行轻量验证而不影响主数据仓库。

在 `.env` 中启用：

```env
SAMPLE_MODE=true
```

启用后：

- DAG 写入 `raw_sample`、`staging_sample`、`marts_sample`、`meta_sample`
- dbt 使用 `sample` target
- 调度器可见的历史窗口范围缩小，便于快速验证

Sample Mode 仍使用相同的 GCS bucket 与 raw 落盘路径，隔离范围仅限 BigQuery 数据集。

### 8.6 E2E Tests

三条 E2E 路径均位于 `tests/integration/test_pipeline_e2e.py`，通过环境变量启用。

**Smoke**（默认集成路径）：

```bash
set -a; source .env; set +a
VOLTAGE_HUB_RUN_PIPELINE_TESTS=1 .venv/bin/pytest -rs tests/integration/test_pipeline_e2e.py
```

运行单窗口全链路抽取，并覆盖跨 UTC 午夜日期边界场景，适合日常改动后的快速回归。

**Heavy**（包含 smoke）：

```bash
set -a; source .env; set +a
VOLTAGE_HUB_RUN_PIPELINE_TESTS=1 \
VOLTAGE_HUB_RUN_HEAVY_PIPELINE_TESTS=1 \
  .venv/bin/pytest -rs tests/integration/test_pipeline_e2e.py
```

在 smoke 基础上增加幂等重跑和多窗口 backfill 验证。backfill 默认使用 2 个 hourly 窗口，可通过以下变量调整：

```bash
VOLTAGE_HUB_TEST_BACKFILL_HOURS=12    # 整数，且 >= 2
VOLTAGE_HUB_TEST_BACKFILL_END_BOUNDARY=2026-03-27T00:00:00+00:00  # 需对齐到整点
```

Heavy 测试运行后会保留 GCS / BigQuery 中的数据，不会自动清理；这些数据可直接用于后续开发。

**Failure-Path**（包含 smoke）：

```bash
set -a; source .env; set +a
VOLTAGE_HUB_RUN_PIPELINE_TESTS=1 \
VOLTAGE_HUB_RUN_FAILURE_PATH_PIPELINE_TESTS=1 \
  .venv/bin/pytest -rs tests/integration/test_pipeline_e2e.py
```

该路径会创建隔离的临时 BigQuery 数据集，通过修改 `_ingestion_timestamp` 触发 freshness 的 warn 和 error 路径，并在测试结束后自动清理，不会影响共享开发数据。

**执行顺序**：

1. 日常开发 → unit tests + E2E smoke
2. 阶段验收 → E2E heavy
3. 故障路径验证 → E2E failure-path（可独立运行）

### 8.7 Serving API Integration Tests

```bash
set -a; source .env; set +a
VOLTAGE_HUB_RUN_PIPELINE_TESTS=1 .venv/bin/pytest -rs tests/integration/test_serving_api.py
```

前提条件：BigQuery 中已有 pipeline 产出的数据。测试覆盖全部端点（`/health`、`/freshness`、`/pipeline/status`、`/anomalies`、`/metrics/*`），包括响应元数据验证和错误处理。

---

## 9. 问题排查

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
请确保至少已有一次 DAG 运行成功完成，并确认查询日期范围内的 marts 表中确实存在数据。

**Sample Mode 混淆**
启用 `SAMPLE_MODE=true` 后，所有读写都指向 `*_sample` 数据集。请检查对应的 sample 数据集，而非主数据集。

---
