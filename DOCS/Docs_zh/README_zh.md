[English](/README.md) | [简体中文](/DOCS/Docs_zh/README_zh.md)

# VoltageHub

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue)](/pyproject.toml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](/LICENSE)
[![Airflow](https://img.shields.io/badge/Airflow-2.8%2B-017CEE?logo=apacheairflow)](https://airflow.apache.org/)
[![dbt](https://img.shields.io/badge/dbt-1.7%2B-FF694B?logo=dbt)](https://www.getdbt.com/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688?logo=fastapi)](https://fastapi.tiangolo.com/)

一个基于 EIA 电网运行数据构建的端到端批处理分析数据产品，包含 Airflow 编排、分层 BigQuery 数据仓库以及 FastAPI 服务层。

## 概述

美国电力市场的运行数据由 EIA（能源信息署）公开发布，涵盖各区域的发电量、负荷和交换量等核心指标。VoltageHub 以这些数据为基础，构建了一套覆盖数据摄取、仓库建模到 API 对外服务的端到端批处理分析数据产品。

项目的核心目标是将原始的 EIA 电网数据转化为可供查询的分析表和 API 接口。数据经 GCS 落盘、BigQuery 加载、dbt 分层转换后，由 FastAPI 对外提供精选指标，同时通过控制平面表记录运行状态，保障系统可观测性。

## 项目亮点

- 支持增量同步、重跑和历史回填的时间窗口批处理 ELT
- 原始数据落盘到 GCS，确保批次可重放、可审计，摄取与处理解耦
- 基于 dbt 的分层 BigQuery 仓库，覆盖标准化建模与预计算分析
- 分区级增量重建保证重跑幂等，同时将下游计算限定在受影响的日期范围内
- 完善的运维可观测性输出：管道状态、运行指标、新鲜度追踪和异常检测
- FastAPI 服务层基于预聚合的仓库表提供查询，而非直接聚合事实表
- **技术栈**：Airflow · BigQuery · dbt · FastAPI · GCS · Terraform · Docker · GitHub Actions

## 演示

下方图片展示了项目从任务编排到仓库产出再到 API 服务的端到端运行情况。

### 1. Airflow DAG 执行流程

![Airflow DAG execution flow](/assets/Graph%20View.png)

覆盖了从数据提取、GCS 落盘到 dbt 构建、异常检查及管道状态更新的完整编排流程。

### 2. BigQuery 中的标准化暂存模型

![Canonical staging model in BigQuery](/assets/Canonical%20staging%20model%20in%20BigQuery%20after%20dbt%20transformation.png)

原始 EIA 记录经 dbt 转换后进入暂存层，为下游数据集市和 API 服务提供整洁的数据基础。

### 3. 数据集市中的每日区域负荷聚合

![Precomputed daily regional load mart](/assets/Precomputed%20analytical%20output%20for%20daily%20regional%20load%20in%20marts.png)

数据集市层中预计算的每日区域负荷指标，可供下游应用和 API 直接查询。

### 4. FastAPI 分析接口

![FastAPI analytical endpoint](/assets/FastAPI.png)

由数据仓库预计算结果驱动的分析业务接口。

## 架构

### 系统架构

```text
数据源层
  -> EIA 公开电网数据接口

编排层
  -> Airflow DAG 调度
  -> 时间窗口批处理执行
  -> 增量同步与回填

原始数据层
  -> GCS 原始数据落盘
  -> 可重放的批次文件
  -> BigQuery 原始数据加载

转换层
  -> dbt 标准化暂存
  -> 事实、维度与聚合模型
  -> 分区级增量重建

控制平面层
  -> 管道状态
  -> 运行指标
  -> 新鲜度追踪
  -> 异常结果

服务层
  -> FastAPI 分析接口
  -> 健康状态、新鲜度、管道状态
  -> 指标与异常数据查询
```

Airflow 负责编排数据摄取，GCS 和 BigQuery 承载原始数据的落盘与存储，dbt 完成仓库建模，FastAPI 对外提供 marts 和 meta 表中的精选结果。

### 数据管道流程

每次 DAG 运行处理一个由 Airflow 调度上下文驱动的时间窗口：

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

Airflow 负责流程协调，而核心的数据转换和分析计算通过 dbt 模型在 BigQuery 内完成。

### 仓库分层

- `raw`：保持上游 EIA 响应原始结构的批次数据层，用于数据回放和审计
- `staging`：经过规范化和标准化处理的电网指标层，作为下游建模的整洁基础
- `marts`：面向分析消费和 API 查询设计的事实表、维度表和聚合表
- `meta`：追踪管道状态、运行指标、新鲜度和异常结果的控制平面表

这种分层将摄取、标准化、消费和可观测性的职责清晰地分离开来。

## 管道设计

### 增量与回填策略

管道每小时运行一次，每次 DAG 运行处理一个 Airflow 时间窗口的数据。

具体来说，每次运行会提取 `data_interval_start` 到 `data_interval_end` 范围内的源数据，以幂等的方式重新加载对应的原始数据分区，然后仅重建下游暂存模型和事实模型中受影响的 `observation_date` 分区。小型聚合模型采用全表重建，以在当前数据规模下保持实现的简单性。

系统有意设置了 `max_active_runs=1`，避免并发写入导致的分区冲突，并确保重跑结果的确定性。此外还提供了"样本模式"，使用隔离的数据集和独立的 dbt target 进行轻量级验证。

### 数据质量与可观测性

数据质量通过 dbt 测试、源数据新鲜度检查和构建后异常检查三重保障。

项目将管道新鲜度与数据新鲜度分开追踪，在 meta 表中记录每次运行的指标，并将异常检测结果作为"仅告警"信号存储——异常模式会被记录下来，但不会阻断正常的计划执行。

控制平面的输出包括：

- `meta.pipeline_state`：最新成功处理窗口的状态
- `meta.run_metrics`：单次运行维度的操作性指标
- `meta.freshness_log`：管道与数据的当前新鲜度状态
- `meta.anomaly_results`：关键业务指标上的异常事件汇总

## 接口服务 (API)

API 服务读取预聚合的 `marts.agg_*` 表和 `meta.*` 表，而非在大型事实表上直接执行聚合查询。

对外暴露的接口包括两类：运维接口（健康状态、新鲜度、管道状态）和分析接口（电力负荷趋势、发电结构、区域最高需求等）。

每个响应都附带如下元数据，帮助数据消费方结合运行情况理解返回结果：

- `data_as_of`
- `pipeline_run_id`
- `freshness_status`

## 快速上手

**前置条件**：GCP 账号及 Service Account 凭证、Docker、Terraform、Make、uv。

```bash
cp .env.example .env
make terraform-init
make terraform-apply
make build && make up
make dbt-deps
```

完成上述步骤后，在 Airflow 中触发 `eia_grid_batch` 即可运行管道，随后访问 `http://localhost:8090` 查询 API 返回的数据。

完整的环境配置、凭证处理、冒烟测试、样本模式及故障排查方法，详见 [SETUP_zh.md](/DOCS/Docs_zh/SETUP_zh.md)。

## 项目布局

- `terraform/`：GCP 资源的基础设施即代码 (IaC)
- `airflow/`：DAG 定义与任务编排逻辑
- `dbt/`：数据仓库模型、测试及文档
- `serving-fastapi/`：分析 API 与查询服务层
- `tests/`：单元测试与集成测试
- `DOCS/`：项目开发规范、技术架构、接口定义和测试文档

## 项目依赖与引用

本项目基于以下工具及框架构建：

- [Apache Airflow](https://airflow.apache.org/)：批处理数据摄取、dbt 执行和控制平面更新的工作流编排。
- [BigQuery](https://cloud.google.com/bigquery)：承载 `raw`、`staging`、`marts` 和 `meta` 数据集的分析型数据仓库。
- [dbt Core](https://www.getdbt.com/) 与 [dbt-bigquery](https://docs.getdbt.com/docs/core/connect-data-platform/bigquery-setup)：数据仓库转换、测试、新鲜度检查及文档生成。
- [Docker](https://www.docker.com/) 与 [Docker Compose](https://docs.docker.com/compose/)：Airflow 及其支持服务的本地开发环境。
- [FastAPI](https://fastapi.tiangolo.com/)：分析与运维接口的 API 服务层。
- [GitHub Actions](https://github.com/features/actions)：代码风格检查、dbt 验证和 Terraform 检查的 CI/CD 流水线。
- [Google Cloud Storage (GCS)](https://cloud.google.com/storage)：原始批次数据的落盘区，支持重放和审计。
- [Pydantic](https://docs.pydantic.dev/)：API 层请求与响应的数据校验。
- [ruff](https://docs.astral.sh/ruff/) 与 [sqlfluff](https://docs.sqlfluff.com/)：Python 和 SQL 的代码风格检查。
- [Terraform](https://www.terraform.io/)：GCP 资源和 IAM 配置的基础设施即代码 (IaC)。
- [uv](https://docs.astral.sh/uv/)：Python 依赖管理与本地命令执行。

## 开源协议

该项目采用 Apache License 2.0 授权，详情参见 `LICENSE` 文件。
