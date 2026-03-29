# SETUP — VoltageHub

---

## 1. 目的

本文档说明了如何进行本地的配置、部署、运行以及验证 VoltageHub。

根目录的 `README.md` 是专门针对项目概览和产品展示优化的。这本设置指南则是为了确保本地可重现运行的配套运维文档。

---

## 2. 前置条件

在开始之前，请确保您的计算机上已安装/获取了以下内容：

- 一个 GCP (Google Cloud Platform) 项目
- 一个具有 GCS (Google Cloud Storage) 和 BigQuery 访问权限的服务账号 JSON 密钥
- 一个 EIA API 密钥
- Docker 和 Docker Compose
- Python 3.11
- `uv`
- Terraform 1.5+

项目基准设置：

- GCP 项目 ID: `voltage-hub-dev`
- 默认区域 (Region): `us-central1`
- 默认的原始数据存储桶 (Bucket) 名称: `voltage-hub-raw`

---

## 3. 仓库设置

克隆此代码仓库并进入项目根目录：

```bash
git clone <your-repo-url>
cd voltage-hub
```

在创建本地配置之前，请先查看配置示例文件：

```bash
cp .env.example .env
```

---

## 4. 环境配置

根据您的实际环境填写 `.env` 中的相应变量值。

关键的环境变量包括：

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

# Pipeline (数据管道)
BACKFILL_DAYS=7
SAMPLE_MODE=false
DBT_RUN_RESULTS_PATH=/opt/airflow/dbt/target/run_results.json

# EIA
EIA_API_KEY=your-eia-api-key

# Serving API (API服务)
PORT=8090
CACHE_TTL_SECONDS=300
```

提示：

- `PORT` 是用于 API 服务的端口。切勿将其重命名为 `SERVER_PORT`。
- `GCS_BUCKET_NAME` 是正规原始数据存储桶变量。
- `SAMPLE_MODE=true` 将使管道数据路由至隔离的样本数据集，而不是主数据仓库数据集。

---

## 5. 访问凭证

将您的服务账号密钥放置在以下路径：

```text
keys/service-account.json
```

项目会将此文件挂载（mount）到各个容器内的对等路径：

```text
/opt/airflow/keys/service-account.json
```

这意味着在 `.env` 文件中，以下两个变量通常应保持一致：

```env
GCP_SERVICE_ACCOUNT_KEY_PATH=/opt/airflow/keys/service-account.json
GOOGLE_APPLICATION_CREDENTIALS=/opt/airflow/keys/service-account.json
```

如果日后您的基础设施重新从头部署了一次，请在重启 Docker Compose 之前确保 `keys/service-account.json` 文件中仍包含正确的服务账号密钥。

---

## 6. 基础设施部署 (Provision Infrastructure)

初始化 Terraform：

```bash
make terraform-init
```

应用并创建基础设施：

```bash
make terraform-apply
```

该步骤会部署：

- 用于原始数据落盘的 GCS 存储桶
- BigQuery 数据集：`raw`, `staging`, `marts`, `meta`
- 运行时所需的服务账号和对应的 IAM 权限绑定

如果您倾向于直接运行 Terraform 指令：

```bash
terraform -chdir=terraform init
terraform -chdir=terraform apply -var-file=terraform.tfvars
```

验证目标：

- GCS 中成功创建了对应的 raw 原始数据桶
- BigQuery 中存在上述四个数据集
- Terraform 执行完成且无错误

非绝对必要，请避免破坏性的重新部署。如果您确实需要重新创建所有的基础设施，您可能需要在本地还原新的服务账户密钥，并重启 Docker Compose 容器以让它们重新挂载此密钥。

---

## 7. 启动本地服务

构建并启动本地容器环境：

```bash
make build
make up
```

或者直接使用 Docker Compose 指令：

```bash
docker compose build
docker compose up -d
```

这将会启动：

- `postgres` (数据库)
- `airflow-webserver` (Airflow Web 服务)
- `airflow-scheduler` (Airflow 调度器)
- `serving-fastapi` (FastAPI 接口服务)

本地默认访问地址：

- Airflow 界面 (UI): [http://localhost:8080](http://localhost:8080)
- FastAPI 接口文档 (docs): [http://localhost:8090/docs](http://localhost:8090/docs)
- FastAPI 健康检查 (health): [http://localhost:8090/health](http://localhost:8090/health)

从容器引导阶段建立的 Airflow 默认本地凭据：

- 用户名: `admin`
- 密码: `admin`

快速的容器检查指令：

```bash
docker compose ps
```

---

## 8. 准备 dbt

在执行任何 dbt 命令之前，务必先运行依赖安装 `dbt deps`：

```bash
make dbt-deps
```

这会在 Airflow 容器当中安装所需的 dbt 外部包依赖。

紧接着可以用以下命令来验证仓储环境项目：

```bash
make dbt-build BATCH_DATE=2026-03-27
```

你也可以通过以下指令来生成相关文档：

```bash
make dbt-docs
```

如果您需要手动切换目标到样本模式（Sample mode），请在运行 DAG 或任何 dbt 命令前，先在 `.env` 当中设置 `SAMPLE_MODE=true`。

---

## 9. 运行数据管道 (Pipeline)

主气流图 (DAG) 的名称为：

```text
eia_grid_batch
```

您可以直接通过 Airflow UI 界面触发它，也可以通过命令行运行指定时间段的回填 (backfill) 窗口。

使用 Makefile 的回填示例：

```bash
make backfill START_DATE=2026-03-27T00:00:00+00:00 END_DATE=2026-03-28T00:00:00+00:00
```

其等效的 Docker 命令：

```bash
docker compose exec airflow-webserver airflow dags backfill eia_grid_batch \
  --start-date "2026-03-27T00:00:00+00:00" \
  --end-date "2026-03-28T00:00:00+00:00"
```

每次运行均按以下顺序执行各流程阶段：

```text
extract_grid_batch
-> land_raw_to_gcs
-> load_to_bq_raw
-> dbt_source_freshness
-> dbt_build
-> check_anomalies
-> record_run_metrics
-> update_pipeline_state
```

Airflow 启用了追赶配置 （`catchup=True`）并限制活跃运行数量 （`max_active_runs=1`），所以对于历史数据的回退填充操作也是会按顺序执行的，从而防止发生并行写入分区冲突。

---

## 10. 启动 Serving API 服务

由于 serving API 服务已默认包含在了 `docker compose up -d` 命令编排当中，一般对于大多数的本地测试来说您不需要再额外单独启动它。

如果您想要在环境外部直接脱离 Docker 来运行它：

```bash
cd serving-fastapi
uv sync
uv run uvicorn app.main:app --host 0.0.0.0 --port 8090
```

有用的本地测试指令：

```bash
curl http://localhost:8090/health
curl http://localhost:8090/pipeline/status
curl "http://localhost:8090/metrics/load?region=US48&start_date=2026-03-27&end_date=2026-03-27&granularity=daily"
```

---

## 11. 冒烟测试 (Smoke Test)

在整个容器栈启动并在至少有一次的 DAG 运行完成后，验证系统各端是否运转正常。

### 11.1 Airflow

- UI 界面中能出现 `eia_grid_batch` DAG 
- 某次运行能不带任务错误地正确完成
- 图像化视图 (Graph view) 中能显示各项任务确实已按预期顺序顺利执行了

### 11.2 GCS 的原始数据落盘 (Raw Landing)

检查原始路径是否正按以下预期路径模式存放批处理文件：

```text
gs://<bucket>/voltage-hub/raw/year=YYYY/month=MM/day=DD/window=<start_iso>/batch.json
```

### 11.3 BigQuery 检查

确认以下对象中生成了正常的数据：

- `raw.eia_grid_batch`
- `staging.stg_grid_metrics`
- `marts.agg_load_daily`
- `marts.agg_generation_mix`
- `meta.pipeline_state`
- `meta.run_metrics`
- `meta.freshness_log`

### 11.4 Serving API (数据层 API) 检查

关键端点功能验证：

```bash
curl http://localhost:8090/health
curl http://localhost:8090/freshness
curl http://localhost:8090/pipeline/status
curl "http://localhost:8090/metrics/generation-mix?region=US48&start_date=2026-03-27&end_date=2026-03-27"
```

---

## 12. 样本模式 (Sample Mode)

样本模式用于在无需向主数据仓库表写入的情况下执行轻量级的系统验证。

想要启用它，在此变量项中添加配置：

```env
SAMPLE_MODE=true
```

当启用后：

- 相关的 DAG 会将各项针对 raw, staging, marts 以及 meta 等所有层级的更新重新定位指向到带 `*_sample` 后缀对应的数据集上。
- dbt 工具也会切换采用被称之为 `sample` 的执行目标 (Target)
- 从调度器角度能看见的历史记录面也被变窄，这便于做更为轻量的直接验证

该样本模式依然在使用原本一致的 GCS bucket 和对应的 raw 落盘对象的文件目录规则约定。这里的资源隔离主要发生在 BigQuery 的数据集管理层级以及面向整个管道业务输出层面上的内容隔离，实际上是不对数据下沉 (Landing) 步骤实施物理隔离拦截的。

---

## 13. 检查清单

在正式判定这套工作环境已完全可用之前请通读使用以下的这份清单表：

- Terraform 各命令的 apply 工作均已正常成功完成
- 所有的预设 Docker Compose 服务全部正在运转中
- Airflow UI 是能够通过访问 `localhost:8080` 正常加载的
- `dbt deps` 动作已正确宣告完成
- 相关的 DAG 至少针对了某个对应批次时间完成了一次顺利运转
- `raw`, `staging`, `marts` 和 `meta` 四个库当中均确认带有了数据结果
- 访问各类接口节点如 `/health` 时应当会有并返回 `200` 数据回复
- `/freshness` 能够同时返回出两个维度下的刷新标志
- 对于 `/pipeline/status` 它正提供并展示它最新的完成数据窗结果
- API 可以提供某块相关的、且被事先已经通过预计算好的正确的业务统计报表结果

---

## 14. 疑难解答

### 凭据路径错误 (Credentials path errors)

若 Airflow 或者 FastAPI 反馈无法使用对应的 GCP 认证的时候，请确认：

- `keys/service-account.json` 文件存在于您的本地目录中。
- 在您的 `.env` 内部的设定变量的确被正确导向到了 `/opt/airflow/keys/service-account.json`。
- 上一步的文件名路径应当能够正确与被容器所支持的挂载选项匹配。

### IAM 权限引起的问题 (IAM permission issues)

如果在进行 GCS 文件推入的时候产生了对应的 BigQuery 在上传过程中各种失败状况，可以通过查看一下运行时服务账号是否存在所需的几种重要应用权限角色的设定：

- `bigquery.dataEditor`
- `bigquery.jobUser`
- `storage.objectAdmin`

### `dbt deps` 没有被运行过

在使用各类 dbt 相关指令因为缺少各类外部依赖包并直接引起命令瘫痪的现象时，可尝试先直接向终端发起：

```bash
make dbt-deps
```

### 在 Airflow 当中出现 DAG 丢失

在打开并登录 Airflow UI 以后未能见着预期的相关名为 `eia_grid_batch` 管道任务图存在：

- 请检查各类容器的可用情况是否存在严重报错
- 请复核在：`docker compose logs airflow-webserver` 的日志。
- 请进一步排查 `docker compose logs airflow-scheduler`。
- 查看原本包含的相关的 DAG 逻辑目录 （即 `airflow/dags/` ） 是否得到正确的服务环境正确导入和挂载工作。

### 在 BigQuery 找不到各个数据包合集 (datasets) 

如果整个管道上的相关各种任务由于未能成功调用到各对应数据合集并以失败作为状态终止退出，那就重新再次执行一下关于 terraform 的各类构建应用执行逻辑并且重新去各个实际库当中亲自确认各资源已妥投建成了。

### 接口只反馈空数据 (API returns empty data)

假如一切基础的查询如：`/health` 反馈运转均皆正规无误而其他各主功能统计终端结果依然全呈现空内容反馈现象时：

- 务必确保相关的在 DAG 内定义的整个端到端流程任务已被彻底并确认成功执行过一次。
- 查询对应 marts 数据集合集里相关的聚合大表在对应的批次日志对应时间参数上是否含有对应的成功结果返回存在。
- 要确保发起的查询对应在具体的相关所选中的区间查询范围内确实包含并存在有真实合规有效的实际在系统数据层已存在的记录数存在。

### 对于样板测试模式的概念存在各类混淆

如果你发现在启用并且开启了 `SAMPLE_MODE=true` 开关，但一直察觉到查询各原有的业务指标全空或者失真的情况下，请先尝试确保在你查核各种对应结果时请优先核验这批操作动作的目标指向均已被确认切换并且对准在那些后置名为 `*_sample` 相关的新创建样本集合当中了没，反过来说并不是还是去查看那些原本正式的主版本各个模型数据集。

---

## 15. 相关文档

- `DOCS/SPEC.md`
- `DOCS/ARCHITECTURE.md`
- `DOCS/INTERFACES.md`
- `DOCS/TESTING.md`
- `CHANGELOG.md`

