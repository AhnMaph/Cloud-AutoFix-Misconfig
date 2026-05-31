resource "aws_cloudtrail" "audit" {
  name                       = "audit-trail"
  s3_bucket_name             = "my-trail-bucket"
  enable_log_file_validation = false
}
