# VoltageHub

## Introduction

VoltageHub is an end-to-end data product for US grid analytics, transforming raw EIA data into reliable metrics through idempotent ELT pipelines, layered modeling, and a RESTful serving API.

## Architecture Overview

```
EIA Source (public data interfaces)
    │
    ▼
Extract Batch (time-window-driven)
    │
    ▼
Raw Landing (GCS)
    │
    ▼
BigQuery Raw (source batch records)
    │
    ▼
dbt Staging (canonical metrics)
    │
    ▼
dbt Marts / Aggregates / Meta
    │
    ▼
Consumers
   └── Serving API (Python FastAPI)
```

## License

This project is licensed under the Apache License 2.0. See the `LICENSE` file for details.
