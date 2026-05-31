resource "aws_db_instance" "primary" {
  engine                     = "mysql"
  instance_class             = "db.t3.micro"
  allocated_storage          = 20
  username                   = "admin"
  password                   = "password123"
  auto_minor_version_upgrade = false
  backup_retention_period    = 1
}
