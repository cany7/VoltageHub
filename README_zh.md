[🇺🇸 English](./README.md) | [🇨🇳 简体中文](./README_zh.md)

# VoltageHub

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue)](./pyproject.toml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](./LICENSE)
[![Airflow](https://img.shields.io/badge/Airflow-2.8%2B-017CEE?logo=apacheairflow)](https://airflow.apache.org/)
[![dbt](https://img.shields.io/badge/dbt-1.7%2B-FF694B?logo=dbt)](https://www.getdbt.com/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688?logo=fastapi)](https://fastapi.tiangolo.com/)

一个基于 EIA 电网运行数据构建的端到端批处理分析数据产品，包含 Airflow 编排、分层的 BigQuery 数据仓库以及 FastAPI 服务层。

## 概述

VoltageHub 将原始的 EIA 电网运行数据转化为可供查询的分析表和 API 接口。

整个数据管道不再是直接查询上游数据源，而是在计划的时间窗口内提取数据，将原始批次数据落盘到 GCS 以支持可重放的重新处理，将符合源结构的记录加载到 BigQuery 中，通过 dbt 在 `raw`、`staging`、`marts` 和 `meta` 层中转换它们，最后通过 FastAPI 暴露精选指标。它还将数据新鲜度、运行指标和异常结果记录在 meta 表中。

## 项目亮点

- 支持增量同步、重跑和历史数据回放的时间窗口批处理 ELT
- 在 Google Cloud Storage 进行原始数据落盘，提供可重放性、可审计性和解耦的重新处理能力
- 使用 dbt 构建的分层 BigQuery 数据仓库，用于标准化建模和预计算分析
- 基于分区范围的增量重建，保持重跑的幂等性，并将下游计算限制在受影响的日期范围内
- 一等公民级别的运维控制输出，包括管道新鲜度、异常检测、运行指标和管道状态
- 由预聚合的数据仓库表而非原始或事实级查询提供支持的 FastAPI 服务层

## 架构

```text
Source Layer (数据源层)
  -> EIA 公开电网数据接口

Orchestration Layer (编排层)
  -> Airflow DAG 调度
  -> 时间窗口批处理执行
  -> 增量同步与回填

Raw Data Layer (原始数据层)
  -> GCS 原始数据落盘
  -> 可重放的批次文件
  -> BigQuery 原始数据提取

Transformation Layer (转换层)
  -> dbt 规范化暂存层
  -> 事实、维度与聚合模型
  -> 基于分区的增量重建

Control Plane Layer (控制平面层)
  -> 管道状态
  -> 运行指标
  -> 新鲜度跟踪
  -> 异常结果

Serving Layer (服务层)
  -> FastAPI 分析接口
  -> 健康状况、新鲜度、管道状态
  -> 指标与异常数据访问
```

Airflow 负责数据摄取的编排，GCS 和 BigQuery 处理原始数据的落盘与存储，dbt 负责数据仓库的构建，FastAPI 对外提供 marts 和 meta 表的精选结果。

## 数据管道流程

每个 DAG 运行都会处理一个由 Airflow 调度上下文驱动的时间窗口。

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

Airflow 协调整个工作流，而核心的数据转换和分析计算主要通过 dbt 模型和构建后检查在 BigQuery 内完成。

## 仓库分层

- `raw`：保持上游 EIA 响应结构的原始批次数据层，以便于数据回放和审计
- `staging`：被规范化和标准化的电网指标层，作为下游建模的整洁基础
- `marts`：专为分析消费和 API 访问设计的事实表、维度表和聚合表
- `meta`：用于跟踪管道状态、运行指标、新鲜度以及异常结果的控制平面表

这种分层设计使得数据的摄取、标准化、消费和可观测性职责被清晰地分离开来。

## 增量与回填策略

管道每小时运行一次，每次 DAG 运行处理一个 Airflow 的时间窗口数据。

对于每次的运行，它会提取 `data_interval_start` 到 `data_interval_end` 对应的数据，幂等性地重新加载对应的原始数据分区，接着在下游的分段和事实模型中只重建受影响的 `observation_date` 对应分区。

小型的聚合模型则进行全表重建以保持目前规模下实现的简单性。系统刻意使用了 `max_active_runs=1` 从而避免并发下的分区写入冲突并确保重跑时的确定性结果。

也可以使用“样本模式（Sample mode）”，它使用隔离的数据集和单独的 dbt 目标，从而进行轻量级的验证。

## 数据质量与可观测性

数据质量通过 dbt 测试、数据源新鲜度检查和构建后的异常检查进行多重保障。

项目将管道的新鲜度和系统数据的新鲜度分开进行追踪记录，在 meta 表里存下每次的运行指标，将异常数据判定作为“仅警告”信号储存起来，使得各类异常模式能够暴露但不会阻断例行的计划运行。

控制平面的输出包括：

- `meta.pipeline_state`：记录最新的成功处理窗口状态
- `meta.run_metrics`：记录单次运行维度的各项操作性指标
- `meta.freshness_log`：提供管道与数据当前的新鲜度状态日志
- `meta.anomaly_results`：汇总关键业务指标上的异常事件结果

## 接口服务 (API)

API 服务读取已预先聚合的 `marts.agg_*` 表以及 `meta.*` 表，而不是在大型事实表上运行直接的聚合查询。

它暴露了包括健康状态、新鲜度和管道状态的运维终端接口，同时还开放了用以分析电力负荷趋势、发电结构和区域最高需求的各项分析型接口。

接口返回的内容也包含了能协助数据消费者结合实际运行情况理解各项结果的元数据：

- `data_as_of`
- `pipeline_run_id`
- `freshness_status`

## 快速上手

```bash
cp .env.example .env
make terraform-init
make terraform-apply
make build && make up
make dbt-deps
```

准备完成后即可在 Airflow 中触发 `eia_grid_batch` 运行管道，随后在访问 `http://localhost:8090` 查询对应的 API 的反馈数据即可。

如需完整的环境配置、凭证处理、冒烟测试、样本模式以及各种故障排查方法，请参阅 [DOCS/SETUP_zh.md](DOCS/SETUP_zh.md)。

## 演示

下方的截图展示了项目的端到端运行情况，从任务编排到多层仓库结果，再到 API 服务。

### 1. Airflow DAG 执行流程

![Airflow DAG execution flow](assets/Graph%20View.png)

展现了各任务之间的端到端 DAG 编排图，覆盖了从抓取，数据落盘到后续的 dbt 构建，各类异常检查，以及管道状态更新的过程。

### 2. 在 BigQuery 中的规范化暂存模型

![Canonical staging model in BigQuery](assets/Canonical%20staging%20model%20in%20BigQuery%20after%20dbt%20transformation.png)

展示未经处理的 EIA 记录被标准化转入暂存层，以便下游数据集市和服务。

### 3. 数据集市中的每日区域负荷预计算聚合数据

![Precomputed daily regional load mart](assets/Precomputed%20analytical%20output%20for%20daily%20regional%20load%20in%20marts.png)

展示数据集市层中预计算好的日常区域负载指标，随后即可供下游应用和 API 接口查询。

### 4. FastAPI 业务分析接口

![FastAPI analytical endpoint](assets/FastAPI.png)

展示由数据仓库的预计算输出内容支持服务的分析业务接口逻辑层。

## 项目布局

- `terraform/`: 用于 GCP 资源的架构代码 (IaC)
- `airflow/`: DAG 和各类任务编排逻辑
- `dbt/`: 数据仓库模型、测试及文档
- `serving-fastapi/`: 分析 API 和各类查询服务接口层
- `tests/`: 单元与集成测试
- `DOCS/`: 项目规范文档、技术架构、接口和测试记录。

## 技术栈

此项目使用了下述工具及框架构建：

- [Apache Airflow](https://airflow.apache.org/): 批处理数据摄取、dbt 执行和管道控制平面更新的工作流编排。
- [BigQuery](https://cloud.google.com/bigquery): 作为 `raw`、`staging`、`marts` 和 `meta` 数据集的分析型数据仓库。
- [dbt Core](https://www.getdbt.com/) 与 [dbt-bigquery](https://docs.getdbt.com/docs/core/connect-data-platform/bigquery-setup): 用于数据仓库转换、数据测试、新鲜度检查及文档。
- [Docker](https://www.docker.com/) 和 [Docker Compose](https://docs.docker.com/compose/): Airflow 及其支持服务的本地开发环境。
- [FastAPI](https://fastapi.tiangolo.com/): 分析和运维端点的 API 服务层。
- [GitHub Actions](https://github.com/features/actions): 用于代码风格检查、dbt 验证和 Terraform 检查的 CI/CD。
- [Google Cloud Storage (GCS)](https://cloud.google.com/storage): 用于可重放和可审计批处理文件的原始登岸区。
- [Pydantic](https://docs.pydantic.dev/): 用于 API 层的请求和响应的数据验证。
- [ruff](https://docs.astral.sh/ruff/) 和 [sqlfluff](https://docs.sqlfluff.com/): Python 和 SQL 的格式检查。
- [Terraform](https://www.terraform.io/): 用于 GCP 资源和 IAM 配置的基础设施即代码 (IaC)。
- [uv](https://docs.astral.sh/uv/): Python 依赖管理和本地命令执行。

## 开源协议

该项目采用 Apache License 2.0 授权。详情参见 `LICENSE` 文件。
