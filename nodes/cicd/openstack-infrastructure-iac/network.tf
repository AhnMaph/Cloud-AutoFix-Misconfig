# tests/terraform/network.tf
# Intentionally misconfigured for testing — correct resource types

terraform {
  required_providers {
    openstack = {
      source  = "terraform-provider-openstack/openstack"
      version = "~> 1.54"
    }
  }
}

# CKV_OPENSTACK_1: hardcoded password in provider block
provider "openstack" {
  user_name   = "admin"
  tenant_name = "demo"
  password    = "super_secret_password"   # hardcoded — should be var
  auth_url    = "http://192.168.154.100:5000/v3"
}

# ── Security Groups ───────────────────────────────────────────────────────────

resource "openstack_networking_secgroup_v2" "web_sg" {
  name        = "web-security-group"
  description = "Security group for web servers"
}

# CKV_OPENSTACK_2: SSH open to world
resource "openstack_networking_secgroup_rule_v2" "ssh_open" {
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 22
  port_range_max    = 22
  remote_ip_prefix  = "0.0.0.0/0"
  security_group_id = openstack_networking_secgroup_v2.web_sg.id
}

# CKV_OPENSTACK_3: RDP open to world
resource "openstack_networking_secgroup_rule_v2" "rdp_open" {
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 3389
  port_range_max    = 3389
  remote_ip_prefix  = "0.0.0.0/0"
  security_group_id = openstack_networking_secgroup_v2.web_sg.id
}

# ── Compute ───────────────────────────────────────────────────────────────────

# CKV_OPENSTACK_4: admin_pass set on instance
resource "openstack_compute_instance_v2" "web_server" {
  name            = "web-server"
  image_id        = "ad091b52-742f-469e-8f3c-fd81cadf0743"
  flavor_id       = "3"
  key_pair        = "my-keypair"
  security_groups = [openstack_networking_secgroup_v2.web_sg.name]
  admin_pass      = "MyInsecurePass123!"

  network {
    name = "internal-net"
  }
}

# ── Network / Subnet ──────────────────────────────────────────────────────────

resource "openstack_networking_network_v2" "internal" {
  name           = "internal-net"
  admin_state_up = true
}

resource "openstack_networking_subnet_v2" "internal_subnet" {
  name       = "internal-subnet"
  network_id = openstack_networking_network_v2.internal.id
  cidr       = "192.168.100.0/24"
  ip_version = 4
  # dns_nameservers not set
}

# ── Router ────────────────────────────────────────────────────────────────────

resource "openstack_networking_router_v2" "main_router" {
  name           = "main-router"
  admin_state_up = true
  # external_network_id not set
}
