# Local-first by default. Set enable_aws=true (and provide AWS creds) for EC2.
terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.2"
    }
  }
}

provider "aws" {
  region = var.aws_region

  # When AWS is disabled, use placeholder creds so plan/apply stay local-only.
  access_key = var.enable_aws ? null : "local-only"
  secret_key = var.enable_aws ? null : "local-only"

  skip_credentials_validation = !var.enable_aws
  skip_requesting_account_id  = !var.enable_aws
  skip_metadata_api_check     = true
  skip_region_validation      = !var.enable_aws
}

# Keeps a valid plan when AWS resources are gated off.
resource "null_resource" "local_ready" {
  count = var.enable_aws ? 0 : 1

  triggers = {
    note = "Local smoke path is active; set enable_aws=true to provision EC2."
  }
}

data "aws_ami" "amazon_linux" {
  count       = var.enable_aws ? 1 : 0
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }
}

resource "aws_security_group" "stella" {
  count       = var.enable_aws ? 1 : 0
  name        = "${var.name_prefix}-stella"
  description = "SSH (and optional VNC) for remote Stella host"

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.ssh_ingress_cidr]
  }

  dynamic "ingress" {
    for_each = var.enable_vnc ? [1] : []
    content {
      description = "VNC"
      from_port   = 5900
      to_port     = 5901
      protocol    = "tcp"
      cidr_blocks = [var.ssh_ingress_cidr]
    }
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "${var.name_prefix}-stella"
    Project = "atari-keyboard"
  }
}

resource "aws_instance" "stella" {
  count                  = var.enable_aws ? 1 : 0
  ami                    = data.aws_ami.amazon_linux[0].id
  instance_type          = var.instance_type
  key_name               = var.key_name
  vpc_security_group_ids = [aws_security_group.stella[0].id]

  root_block_device {
    volume_size = 8
    volume_type = "gp3"
  }

  tags = {
    Name    = "${var.name_prefix}-stella"
    Project = "atari-keyboard"
  }
}
