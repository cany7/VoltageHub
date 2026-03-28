variable "project_id" {
  description = "GCP project ID where infrastructure resources are provisioned."
  type        = string
}

variable "region" {
  description = "Primary GCP region for bucket placement and regional resources."
  type        = string
}

variable "bucket_name" {
  description = "Name of the GCS bucket used for raw EIA grid data landing."
  type        = string
}

variable "bq_dataset_raw" {
  description = "BigQuery dataset ID for raw landed source data."
  type        = string
  default     = "raw"
}

variable "bq_dataset_staging" {
  description = "BigQuery dataset ID for staging models."
  type        = string
  default     = "staging"
}

variable "bq_dataset_marts" {
  description = "BigQuery dataset ID for mart and aggregate models."
  type        = string
  default     = "marts"
}

variable "bq_dataset_meta" {
  description = "BigQuery dataset ID for pipeline metadata tables."
  type        = string
  default     = "meta"
}
