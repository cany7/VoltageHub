#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from google.cloud import bigquery


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "http://127.0.0.1:8090"
DEFAULT_MISS_REQUESTS = 50
DEFAULT_HIT_REQUESTS = 200
REQUEST_TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class EndpointCase:
    name: str
    path: str
    query_params: dict[str, str]
    cache_mode: str

    @property
    def url(self) -> str:
        if not self.query_params:
            return self.path
        return f"{self.path}?{urlencode(self.query_params)}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark Voltage Hub REST API latency with curl. "
            "Uses real BigQuery data to auto-discover request parameters."
        )
    )
    parser.add_argument("--base-url", default=os.environ.get("BENCHMARK_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--miss-requests", type=int, default=DEFAULT_MISS_REQUESTS)
    parser.add_argument("--hit-requests", type=int, default=DEFAULT_HIT_REQUESTS)
    parser.add_argument(
        "--restart-command",
        help=(
            "Optional shell command used to restart the serving API before cache-miss runs. "
            "If omitted, the script waits for CACHE_TTL_SECONDS + 1 before each cached endpoint."
        ),
    )
    parser.add_argument(
        "--skip-freshness",
        action="store_true",
        help="Skip the uncached /freshness control-plane baseline.",
    )
    parser.add_argument(
        "--output-json",
        help="Optional path to write the raw benchmark result JSON.",
    )
    parser.add_argument(
        "--only",
        action="append",
        help=(
            "Optional endpoint case name to run. Can be passed multiple times. "
            "Known values include freshness, metrics_load_daily, "
            "metrics_generation_mix, and metrics_top_regions."
        ),
    )
    return parser.parse_args()


def load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip("'\"")


def build_bigquery_client() -> tuple[bigquery.Client, str, str]:
    load_env_file(PROJECT_ROOT / ".env")
    project_id = os.environ.get("GCP_PROJECT_ID")
    if not project_id:
        raise SystemExit("GCP_PROJECT_ID is required. Set it in the environment or .env.")

    credentials = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if credentials and not Path(credentials).exists():
        alt_credentials = PROJECT_ROOT / "keys" / "service-account.json"
        if alt_credentials.exists():
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(alt_credentials)

    marts_dataset = os.environ.get("BQ_DATASET_MARTS", "marts")
    client = bigquery.Client(project=project_id)
    return client, project_id, marts_dataset


def query_one_row(client: bigquery.Client, query: str) -> dict[str, Any] | None:
    rows = list(client.query(query).result(max_results=1))
    if not rows:
        return None
    return dict(rows[0].items())


def discover_cases(skip_freshness: bool) -> list[EndpointCase]:
    client, project_id, marts_dataset = build_bigquery_client()
    qualified_marts = f"`{project_id}.{marts_dataset}`"

    load_row = query_one_row(
        client,
        f"""
        select region, observation_date
        from {qualified_marts}.agg_load_daily
        order by observation_date desc, region asc
        limit 1
        """,
    )
    generation_mix_row = query_one_row(
        client,
        f"""
        select region, observation_date
        from {qualified_marts}.agg_generation_mix
        order by observation_date desc, region asc
        limit 1
        """,
    )
    top_regions_row = query_one_row(
        client,
        f"""
        select observation_date
        from {qualified_marts}.agg_top_regions
        order by observation_date desc, rank asc
        limit 1
        """,
    )

    missing_tables: list[str] = []
    if load_row is None:
        missing_tables.append("agg_load_daily")
    if generation_mix_row is None:
        missing_tables.append("agg_generation_mix")
    if top_regions_row is None:
        missing_tables.append("agg_top_regions")
    if missing_tables:
        raise SystemExit(
            "Cannot discover benchmark parameters because these marts tables have no rows: "
            + ", ".join(missing_tables)
        )

    load_date = load_row["observation_date"].isoformat()
    mix_date = generation_mix_row["observation_date"].isoformat()
    top_regions_date = top_regions_row["observation_date"].isoformat()

    cases: list[EndpointCase] = []
    if not skip_freshness:
        cases.append(
            EndpointCase(
                name="freshness",
                path="/freshness",
                query_params={},
                cache_mode="uncached",
            )
        )

    cases.extend(
        [
            EndpointCase(
                name="metrics_load_daily",
                path="/metrics/load",
                query_params={
                    "region": str(load_row["region"]),
                    "start_date": load_date,
                    "end_date": load_date,
                    "granularity": "daily",
                },
                cache_mode="ttl",
            ),
            EndpointCase(
                name="metrics_generation_mix",
                path="/metrics/generation-mix",
                query_params={
                    "region": str(generation_mix_row["region"]),
                    "start_date": mix_date,
                    "end_date": mix_date,
                },
                cache_mode="ttl",
            ),
            EndpointCase(
                name="metrics_top_regions",
                path="/metrics/top-regions",
                query_params={
                    "start_date": top_regions_date,
                    "end_date": top_regions_date,
                    "limit": "5",
                },
                cache_mode="ttl",
            ),
        ]
    )
    return cases


def filter_cases(cases: list[EndpointCase], selected_names: list[str] | None) -> list[EndpointCase]:
    if not selected_names:
        return cases

    requested = set(selected_names)
    available = {case.name for case in cases}
    unknown = sorted(requested - available)
    if unknown:
        raise SystemExit(
            "Unknown endpoint case(s): "
            + ", ".join(unknown)
            + ". Available cases: "
            + ", ".join(sorted(available))
        )

    return [case for case in cases if case.name in requested]


def get_cache_ttl_seconds() -> int:
    load_env_file(PROJECT_ROOT / ".env")
    raw_value = os.environ.get("CACHE_TTL_SECONDS", "300")
    try:
        return max(1, int(raw_value))
    except ValueError as exc:
        raise SystemExit(f"Invalid CACHE_TTL_SECONDS value: {raw_value}") from exc


def ensure_curl_available() -> None:
    if shutil.which("curl") is None:
        raise SystemExit("curl is required but was not found on PATH.")


def wait_for_service(base_url: str, timeout_seconds: int = 60) -> None:
    deadline = time.time() + timeout_seconds
    health_url = f"{base_url.rstrip('/')}/health"
    last_error = "service did not respond"
    while time.time() < deadline:
        try:
            _, status_code, _ = run_curl(health_url)
            if status_code == 200:
                return
            last_error = f"/health returned HTTP {status_code}"
        except RuntimeError as exc:
            last_error = str(exc)
        time.sleep(1)
    raise SystemExit(f"Serving API is not ready at {health_url}: {last_error}")


def restart_service(restart_command: str, base_url: str) -> None:
    completed = subprocess.run(
        restart_command,
        cwd=PROJECT_ROOT,
        shell=True,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise SystemExit(
            "Restart command failed.\n"
            f"Command: {restart_command}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    wait_for_service(base_url)


def run_curl(url: str) -> tuple[float, int, Any]:
    command = [
        "curl",
        "--silent",
        "--show-error",
        "--output",
        "-",
        "--write-out",
        "\n__CURL_STATS__ %{time_total} %{http_code}",
        "--max-time",
        str(REQUEST_TIMEOUT_SECONDS),
        url,
    ]
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or f"curl failed for {url}")

    marker = "\n__CURL_STATS__ "
    if marker not in completed.stdout:
        raise RuntimeError(f"curl output missing timing marker for {url}")
    body, stats = completed.stdout.rsplit(marker, 1)
    stats_parts = stats.strip().split()
    if len(stats_parts) != 2:
        raise RuntimeError(f"curl stats were malformed for {url}: {stats.strip()}")

    latency_seconds = float(stats_parts[0])
    status_code = int(stats_parts[1])
    payload: Any
    try:
        payload = json.loads(body) if body else None
    except json.JSONDecodeError:
        payload = body
    return latency_seconds, status_code, payload


def percentile(values: list[float], pct: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    if len(values) == 1:
        return values[0]

    sorted_values = sorted(values)
    rank = (len(sorted_values) - 1) * pct
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return sorted_values[int(rank)]
    lower_value = sorted_values[lower]
    upper_value = sorted_values[upper]
    return lower_value + (upper_value - lower_value) * (rank - lower)


def summarize_latencies(latencies: list[float]) -> dict[str, float]:
    return {
        "count": float(len(latencies)),
        "avg_ms": statistics.fmean(latencies) * 1000,
        "p50_ms": percentile(latencies, 0.50) * 1000,
        "p95_ms": percentile(latencies, 0.95) * 1000,
        "p99_ms": percentile(latencies, 0.99) * 1000,
        "fastest_ms": min(latencies) * 1000,
        "slowest_ms": max(latencies) * 1000,
    }


def benchmark_uncached_case(base_url: str, case: EndpointCase, request_count: int) -> dict[str, Any]:
    full_url = f"{base_url.rstrip('/')}{case.url}"
    latencies: list[float] = []
    for _ in range(request_count):
        latency, status_code, _ = run_curl(full_url)
        if status_code != 200:
            raise SystemExit(f"{case.name} returned HTTP {status_code} for {full_url}")
        latencies.append(latency)

    return {
        "scenario": "uncached_baseline",
        "url": full_url,
        "summary": summarize_latencies(latencies),
    }


def benchmark_ttl_case(
    base_url: str,
    case: EndpointCase,
    miss_requests: int,
    hit_requests: int,
    restart_command: str | None,
    cache_ttl_seconds: int,
) -> dict[str, Any]:
    full_url = f"{base_url.rstrip('/')}{case.url}"

    if restart_command:
        restart_service(restart_command, base_url)
    else:
        wait_seconds = cache_ttl_seconds + 1
        print(
            f"[wait] {case.name}: sleeping {wait_seconds}s so the next request is a cache miss",
            file=sys.stderr,
        )
        time.sleep(wait_seconds)
        wait_for_service(base_url)

    cold_run_latencies: list[float] = []
    for _ in range(miss_requests):
        latency, status_code, _ = run_curl(full_url)
        if status_code != 200:
            raise SystemExit(f"{case.name} returned HTTP {status_code} for {full_url}")
        cold_run_latencies.append(latency)

    run_curl(full_url)

    warm_latencies: list[float] = []
    for _ in range(hit_requests):
        latency, status_code, _ = run_curl(full_url)
        if status_code != 200:
            raise SystemExit(f"{case.name} returned HTTP {status_code} for {full_url}")
        warm_latencies.append(latency)

    cold_tail = cold_run_latencies[1:] if len(cold_run_latencies) > 1 else cold_run_latencies
    return {
        "scenario": "ttl_cache",
        "url": full_url,
        "mixed_run": {
            "requests": miss_requests,
            "estimated_cache_miss_ms": cold_run_latencies[0] * 1000,
            "cache_hit_tail": summarize_latencies(cold_tail),
            "all_requests": summarize_latencies(cold_run_latencies),
        },
        "warm_run": {
            "requests": hit_requests,
            "summary": summarize_latencies(warm_latencies),
        },
    }


def print_case_report(case: EndpointCase, result: dict[str, Any]) -> None:
    print(f"\n=== {case.name} ===")
    print(f"url: {result['url']}")
    if case.cache_mode == "uncached":
        summary = result["summary"]
        print("mode: uncached baseline (/freshness is not backed by the TTL query cache)")
        print(
            "summary: "
            f"avg={summary['avg_ms']:.1f}ms "
            f"p50={summary['p50_ms']:.1f}ms "
            f"p95={summary['p95_ms']:.1f}ms "
            f"p99={summary['p99_ms']:.1f}ms "
            f"fastest={summary['fastest_ms']:.1f}ms "
            f"slowest={summary['slowest_ms']:.1f}ms"
        )
        return

    mixed_run = result["mixed_run"]
    warm_run = result["warm_run"]
    mixed_tail = mixed_run["cache_hit_tail"]
    warm_summary = warm_run["summary"]
    print("mode: TTL cache benchmark")
    print(
        "mixed run: "
        f"n={mixed_run['requests']} "
        f"estimated_miss={mixed_run['estimated_cache_miss_ms']:.1f}ms "
        f"tail_p50={mixed_tail['p50_ms']:.1f}ms "
        f"tail_p95={mixed_tail['p95_ms']:.1f}ms "
        f"tail_p99={mixed_tail['p99_ms']:.1f}ms "
        f"tail_slowest={mixed_tail['slowest_ms']:.1f}ms"
    )
    print(
        "warm run: "
        f"n={warm_run['requests']} "
        f"avg={warm_summary['avg_ms']:.1f}ms "
        f"p50={warm_summary['p50_ms']:.1f}ms "
        f"p95={warm_summary['p95_ms']:.1f}ms "
        f"p99={warm_summary['p99_ms']:.1f}ms "
        f"fastest={warm_summary['fastest_ms']:.1f}ms "
        f"slowest={warm_summary['slowest_ms']:.1f}ms"
    )


def main() -> int:
    args = parse_args()
    if args.miss_requests < 1:
        raise SystemExit("--miss-requests must be greater than 0")
    if args.hit_requests < 1:
        raise SystemExit("--hit-requests must be greater than 0")

    ensure_curl_available()
    wait_for_service(args.base_url)
    cache_ttl_seconds = get_cache_ttl_seconds()
    cases = filter_cases(
        discover_cases(skip_freshness=args.skip_freshness),
        args.only,
    )

    print(
        f"Benchmarking {len(cases)} endpoint(s) against {args.base_url.rstrip('/')} "
        f"with CACHE_TTL_SECONDS={cache_ttl_seconds}"
    )
    results: list[dict[str, Any]] = []

    for case in cases:
        if case.cache_mode == "uncached":
            result = benchmark_uncached_case(
                base_url=args.base_url,
                case=case,
                request_count=args.miss_requests,
            )
        else:
            result = benchmark_ttl_case(
                base_url=args.base_url,
                case=case,
                miss_requests=args.miss_requests,
                hit_requests=args.hit_requests,
                restart_command=args.restart_command,
                cache_ttl_seconds=cache_ttl_seconds,
            )
        results.append(
            {
                "endpoint": case.name,
                "path": case.path,
                "query_params": case.query_params,
                "cache_mode": case.cache_mode,
                "result": result,
            }
        )
        print_case_report(case, result)

    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"\nWrote raw benchmark data to {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
