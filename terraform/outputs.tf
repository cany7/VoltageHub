output "bucket_name" {
  description = "Name of the raw landing GCS bucket."
  value       = google_storage_bucket.raw_landing.name
}

output "dataset_raw_id" {
  description = "BigQuery dataset ID for the raw layer."
  value       = google_bigquery_dataset.raw.dataset_id
}

output "dataset_staging_id" {
  description = "BigQuery dataset ID for the staging layer."
  value       = google_bigquery_dataset.staging.dataset_id
}

output "dataset_marts_id" {
  description = "BigQuery dataset ID for the marts layer."
  value       = google_bigquery_dataset.marts.dataset_id
}

output "dataset_meta_id" {
  description = "BigQuery dataset ID for the meta layer."
  value       = google_bigquery_dataset.meta.dataset_id
}

output "service_account_email" {
  description = "Service account email for pipeline runtime access."
  value       = google_service_account.airflow_runtime.email
}
