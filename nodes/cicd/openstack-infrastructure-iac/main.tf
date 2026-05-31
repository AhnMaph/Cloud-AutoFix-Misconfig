# tests/terraform/network.tf
# Intentionally misconfigured for testing

# ── Security Groups ───────────────────────────────────────────────────────────

resource "openstack_networking_secgroup_v2" "web_sg" {
  name        = "web-security-group"
  description = "Security group for web servers"
}

# SSH open to world — CKV_OPENSTACK_1
resource "openstack_networking_secgroup_rule_v2" "ssh_open" {
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 22
  port_range_max    = 22
  remote_ip_prefix  = "0.0.0.0/0"
  security_group_id = openstack_networking_secgroup_v2.web_sg.id
}

# RDP open to world — CKV_OPENSTACK_2
resource "openstack_networking_secgroup_rule_v2" "rdp_open" {
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 3389
  port_range_max    = 3389
  remote_ip_prefix  = "0.0.0.0/0"
  security_group_id = openstack_networking_secgroup_v2.web_sg.id
}

# Allow ALL ingress — CKV_OPENSTACK_4
resource "openstack_networking_secgroup_rule_v2" "allow_all_in" {
  direction         = "ingress"
  ethertype         = "IPv4"
  remote_ip_prefix  = "0.0.0.0/0"
  security_group_id = openstack_networking_secgroup_v2.web_sg.id
}

# Allow ALL egress — CKV_OPENSTACK_5
resource "openstack_networking_secgroup_rule_v2" "allow_all_out" {
  direction         = "egress"
  ethertype         = "IPv4"
  remote_ip_prefix  = "0.0.0.0/0"
  security_group_id = openstack_networking_secgroup_v2.web_sg.id
}

# ── Network / Subnet ──────────────────────────────────────────────────────────

resource "openstack_networking_network_v2" "internal" {
  name           = "internal-net"
  admin_state_up = true
}

# Subnet without DNS — CKV_OPENSTACK_8
resource "openstack_networking_subnet_v2" "internal_subnet" {
  name       = "internal-subnet"
  network_id = openstack_networking_network_v2.internal.id
  cidr       = "192.168.100.0/24"
  ip_version = 4
  # dns_nameservers missing
}

# ── Router ────────────────────────────────────────────────────────────────────

# Router without external gateway — CKV_OPENSTACK_7
resource "openstack_networking_router_v2" "main_router" {
  name           = "main-router"
  admin_state_up = true
  # external_network_id missing
}

resource "openstack_networking_router_interface_v2" "router_iface" {
  router_id = openstack_networking_router_v2.main_router.id
  subnet_id = openstack_networking_subnet_v2.internal_subnet.id
}

