resource "aws_instance" "vulnerable_ec2" {
  ami           = "ami-0c55b159cbfafe1f0"
  instance_type = "t2.micro"
  
  root_block_device {
    encrypted = true
  }
}