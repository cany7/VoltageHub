terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  common_labels = {
    app        = "voltage-hub"
    managed_by = "terraform"
  }
}

resource "google_storage_bucket" "raw_landing" {
  name                        = var.bucket_name
  location                    = var.region
  force_destroy               = true
  uniform_bucket_level_access = true
  labels                      = local.common_labels
}

resource "google_bigquery_dataset" "raw" {
  dataset_id                 = var.bq_dataset_raw
  location                   = var.region
  delete_contents_on_destroy = true
  labels                     = local.common_labels
}

resource "google_bigquery_dataset" "staging" {
  dataset_id                 = var.bq_dataset_staging
  location                   = var.region
  delete_contents_on_destroy = true
  labels                     = local.common_labels
}

resource "google_bigquery_dataset" "marts" {
  dataset_id                 = var.bq_dataset_marts
  location                   = var.region
  delete_contents_on_destroy = true
  labels                     = local.common_labels
}

resource "google_bigquery_dataset" "meta" {
  dataset_id                 = var.bq_dataset_meta
  location                   = var.region
  delete_contents_on_destroy = true
  labels                     = local.common_labels
}

resource "google_service_account" "airflow_runtime" {
  account_id   = "voltage-hub-runtime"
  display_name = "Voltage Hub Runtime"
  description  = "Runtime identity for Voltage Hub warehouse and orchestration access."
}

resource "google_project_iam_member" "airflow_bigquery_data_editor" {
  project = var.project_id
  role    = "roles/bigquery.dataEditor"
  member  = "serviceAccount:${google_service_account.airflow_runtime.email}"
}

resource "google_project_iam_member" "airflow_bigquery_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.airflow_runtime.email}"
}

resource "google_project_iam_member" "airflow_storage_object_admin" {
  project = var.project_id
  role    = "roles/storage.objectAdmin"
  member  = "serviceAccount:${google_service_account.airflow_runtime.email}"
}
