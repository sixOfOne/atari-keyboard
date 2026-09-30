output "mode" {
  description = "local or aws depending on enable_aws"
  value       = var.enable_aws ? "aws" : "local"
}

output "instance_id" {
  description = "EC2 instance id when AWS is enabled"
  value       = try(aws_instance.stella[0].id, null)
}

output "public_ip" {
  description = "EC2 public IP for Ansible inventory when AWS is enabled"
  value       = try(aws_instance.stella[0].public_ip, null)
}

output "ssh_host" {
  description = "Convenience SSH target when AWS is enabled"
  value       = try(aws_instance.stella[0].public_ip, null)
}
