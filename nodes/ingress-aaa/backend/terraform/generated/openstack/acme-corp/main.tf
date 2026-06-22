terraform {
  required_providers {
    openstack = {
      source  = "terraform-provider-openstack/openstack"
      version = ">= 2.1.0"
    }
  }
}

provider "openstack" {}

variable "tenant_id" {
  type    = string
  default = "acme-corp"
}

variable "vm_name" {
  type    = string
  default = "web-02"
}

variable "image_name" {
  type    = string
  default = "Ubuntu-20.04"
}

variable "flavor_name" {
  type    = string
  default = "m1.tiny"
}

variable "network_name" {
  type    = string
  default = "public1"
}

variable "private_subnet_cidr" {
  type    = string
  default = "10.0.0.0/24"
}


data "openstack_networking_network_v2" "existing_private_net" {
  count = 1
  name  = "${var.tenant_id}-private-net"
}

data "openstack_networking_subnet_v2" "existing_private_subnet" {
  count      = 1
  name       = "${var.tenant_id}-private-subnet"
  network_id = data.openstack_networking_network_v2.existing_private_net[0].id
}


resource "openstack_networking_secgroup_v2" "tenant_vm_sg" {
  name        = "${var.tenant_id}-${var.vm_name}-sg"
  description = "Security group for ${var.tenant_id} VM"
}

resource "openstack_networking_secgroup_rule_v2" "allow_icmp" {
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "icmp"
  security_group_id = openstack_networking_secgroup_v2.tenant_vm_sg.id
}

resource "openstack_networking_secgroup_rule_v2" "allow_ssh" {
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 22
  port_range_max    = 22
  security_group_id = openstack_networking_secgroup_v2.tenant_vm_sg.id
}

resource "openstack_compute_instance_v2" "tenant_vm" {
  name        = "${var.tenant_id}-${var.vm_name}"
  image_name  = var.image_name
  flavor_name = var.flavor_name

  security_groups = [
    openstack_networking_secgroup_v2.tenant_vm_sg.name
  ]


  network {
    uuid = data.openstack_networking_network_v2.existing_private_net[0].id
  }


  metadata = {
    tenant     = var.tenant_id
    managed_by = "hybrid-cloud-portal"
  }
}

output "vm_id" {
  value = openstack_compute_instance_v2.tenant_vm.id
}

output "vm_name" {
  value = openstack_compute_instance_v2.tenant_vm.name
}

output "access_ip_v4" {
  value = openstack_compute_instance_v2.tenant_vm.access_ip_v4
}