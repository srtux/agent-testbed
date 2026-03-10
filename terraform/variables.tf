variable "project_id" {
  type        = string
  description = "The GCP Project ID"
}

variable "region" {
  type        = string
  description = "The central GCP region"
  default     = "us-central1"
}

variable "cluster_name" {
  type        = string
  description = "The name of the GKE cluster"
  default     = "default-cluster"
}

# Image references injected by the deploy orchestrator
variable "flight_specialist_image" {
  type        = string
  description = "The built Docker image URI for FlightSpecialist"
}

variable "weather_specialist_image" {
  type        = string
  description = "The built Docker image URI for WeatherSpecialist"
}

variable "profile_mcp_image" {
  type        = string
  description = "The built Docker image URI for Profile_MCP"
}

variable "hotel_specialist_image" {
  type        = string
  description = "The built Docker image URI for HotelSpecialist"
}

variable "car_rental_specialist_image" {
  type        = string
  description = "The built Docker image URI for CarRentalSpecialist"
}

variable "inventory_mcp_image" {
  type        = string
  description = "The built Docker image URI for Inventory_MCP"
}

# Source code reference for Cloud Functions
variable "traffic_generator_source_zip" {
  type        = string
  description = "The GCS URL to the uploaded zip file of the traffic generator source code"
}
