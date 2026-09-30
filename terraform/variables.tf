variable "enable_aws" {
  description = "When true, provision an EC2 host for remote Stella. Keep false for local-only."
  type        = bool
  default     = false
}

variable "aws_region" {
  description = "AWS region for the Stella host."
  type        = string
  default     = "us-east-1"
}

variable "name_prefix" {
  description = "Name prefix for AWS resources."
  type        = string
  default     = "atari-keyboard"
}

variable "instance_type" {
  description = "EC2 instance type."
  type        = string
  default     = "t3.small"
}

variable "key_name" {
  description = "Existing EC2 key pair name (required when enable_aws=true)."
  type        = string
  default     = ""
}

variable "ssh_ingress_cidr" {
  description = "CIDR allowed to SSH (and optional VNC) to the Stella host."
  type        = string
  default     = "0.0.0.0/0"
}

variable "enable_vnc" {
  description = "Open VNC ports on the security group for remote desktop streaming."
  type        = bool
  default     = false
}
