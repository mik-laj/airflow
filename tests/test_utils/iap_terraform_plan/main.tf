# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

/**
 * Copyright 2017 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

provider "google" {
  project = var.project
}

provider "google-beta" {
  project = var.project
}

resource "random_id" "unique_suffix" {
  byte_length = 4
  prefix      = "iap-test"

  keepers = {
    domains = var.domain
  }
}

locals {
  network_name = "${random_id.unique_suffix.hex}-network"
}

resource "google_compute_network" "default" {
  name                    = local.network_name
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "default" {
  name                     = local.network_name
  ip_cidr_range            = "10.127.0.0/20"
  network                  = google_compute_network.default.self_link
  region                   = var.region
  private_ip_google_access = true
}

resource "google_compute_router" "default" {
  name    = "${random_id.unique_suffix.hex}-router"
  network = google_compute_network.default.self_link
  region  = var.region
}

module "cloud-nat" {
  source     = "terraform-google-modules/cloud-nat/google"
  version    = "1.0.0"
  router     = google_compute_router.default.name
  project_id = var.project
  region     = var.region
  name       = "${random_id.unique_suffix.hex}-cloud-nat"
}

locals {
  group-startup-script = file(format("%s/gceme.sh", path.module))
}

module "mig_template" {
  source     = "terraform-google-modules/vm/google//modules/instance_template"
  version    = "1.0.0"
  network    = google_compute_network.default.self_link
  subnetwork = google_compute_subnetwork.default.self_link

  source_image = "debian-10-buster-v20210122"
  source_image_project = "debian-cloud"
  source_image_family = "debian-10"
  service_account = {
    email  = ""
    scopes = ["cloud-platform"]
  }
  name_prefix    = local.network_name
  startup_script = local.group-startup-script
  tags = [
    local.network_name,
    module.cloud-nat.router_name
  ]
  metadata = {
    enable-oslogin = "TRUE"
  }
}

module "mig" {
  source            = "terraform-google-modules/vm/google//modules/mig"
  version           = "1.0.0"
  instance_template = module.mig_template.self_link
  region            = var.region
  hostname          = local.network_name
  target_size       = 1
  named_ports = [{
    name = "http",
    port = 80
  }]
  network    = google_compute_network.default.self_link
  subnetwork = google_compute_subnetwork.default.self_link
}

module "gce-lb-http" {
  source               = "GoogleCloudPlatform/lb-http/google"
  name                 = "${random_id.unique_suffix.hex}-https-redirect"
  project              = var.project
  target_tags          = [local.network_name]
  firewall_networks    = [google_compute_network.default.name]
  ssl                  = true
  ssl_certificates     = [google_compute_ssl_certificate.example.self_link]
  use_ssl_certificates = true
  https_redirect       = true

  backends = {
    default = {
      description                     = null
      protocol                        = "HTTP"
      port                            = 80
      port_name                       = "http"
      timeout_sec                     = 10
      connection_draining_timeout_sec = null
      enable_cdn                      = false
      security_policy                 = null
      session_affinity                = null
      affinity_cookie_ttl_sec         = null
      custom_request_headers          = null

      health_check = {
        check_interval_sec  = null
        timeout_sec         = null
        healthy_threshold   = null
        unhealthy_threshold = null
        request_path        = "/"
        port                = 80
        host                = null
        logging             = null
      }

      log_config = {
        enable      = true
        sample_rate = 1.0
      }

      groups = [
        {
          group                        = module.mig.instance_group
          balancing_mode               = "UTILIZATION"
          capacity_scaler              = null
          description                  = null
          max_connections              = null
          max_connections_per_instance = null
          max_connections_per_endpoint = null
          max_rate                     = null
          max_rate_per_instance        = null
          max_rate_per_endpoint        = null
          max_utilization              = null
        }
      ]
      iap_config = {
        enable               = true
        oauth2_client_id     = var.oauth2_client_id
        oauth2_client_secret = var.oauth2_client_secret
      }
    }
  }

}

resource "google_compute_firewall" "allow_from_iap_to_instances" {
  project = var.project
  name    = "allow-ssh-from-iap-to-tunnel"
  network = google_compute_network.default.name

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  # https://cloud.google.com/iap/docs/using-tcp-forwarding#before_you_begin
  # This is the netblock needed to forward to the instances
  source_ranges = ["35.235.240.0/20"]

  target_tags = [local.network_name]
}
