variable "deploy_bucket_name" {
  type        = string
  description = "The unique GCS bucket name for deployment artifacts"
}

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
  default     = "cluster2"
}

variable "custom_domain" {
  type        = string
  description = "Base custom domain (e.g., testbed.example.com). Leave empty to use Cloud Run native URLs and GKE LoadBalancer IPs."
  default     = ""
}

variable "root_router_url" {
  type        = string
  description = "The HTTP endpoint URL for the RootRouter Agent Engine deployment. Passed after Agent Engine deploy."
  default     = ""
}

variable "booking_orchestrator_url" {
  type        = string
  description = "The HTTP endpoint URL for the BookingOrchestrator Agent Engine deployment. Passed after Agent Engine deploy."
  default     = ""
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
  description = "The object name of the uploaded zip file in the deploy-artifacts bucket"
}

variable "vpc_subnetwork" {
  type        = string
  description = "The subnetwork to use for Cloud Run Direct VPC egress (e.g., projects/PROJ/regions/REG/subnetworks/SUBNET). Leave empty if not using Direct VPC Egress."
  default     = ""
}

variable "vpc_name" {
  type        = string
  description = "The VPC network name to use for Cloud Run Direct VPC egress. Required if vpc_subnetwork is set."
  default     = ""
}

variable "traffic_schedule" {
  type        = string
  description = "Cron schedule for the traffic generator Cloud Scheduler job (default: every 5 minutes)"
  default     = "*/5 * * * *"
}

variable "deploy_timestamp" {
  type        = string
  description = "Timestamp to force Cloud Run redeploiments on same image tags"
  default     = ""
}
