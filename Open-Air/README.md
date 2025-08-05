# OAI 5G Core Deployment Guide

## Overview
This guide describes the complete setup of OAI (Open Air Interface) 5G Core network functions on AWS EC2, including security group configuration, instance creation, and Docker deployment.

## Prerequisites
- AWS CLI configured with appropriate permissions
- Existing VPC with public and private subnets
- NAT Gateway configured for private subnet internet access
- EC2 key pair: `inference_key`

## 1. Security Group Configuration

### Create Security Group for OAI 5GC
```bash
# Create the main 5GC Security Group
aws ec2 create-security-group \
    --group-name OAI-5GC-Security-Group \
    --description "Security group for OAI 5GC network functions" \
    --vpc-id vpc-0463beebd475c520b
```

### Configure Security Group Rules
```bash
# Set the Security Group ID
SG_5GC="sg-038f0b60e6f34ccca"

# Internal 5GC communication rules (SBI - Service Based Interface)
aws ec2 authorize-security-group-ingress \
    --group-id $SG_5GC \
    --protocol tcp \
    --port 80 \
    --source-group $SG_5GC

aws ec2 authorize-security-group-ingress \
    --group-id $SG_5GC \
    --protocol tcp \
    --port 8080 \
    --source-group $SG_5GC

# N4 interface (GTP-C Echo) - internal communication
aws ec2 authorize-security-group-ingress \
    --group-id $SG_5GC \
    --protocol udp \
    --port 2152 \
    --source-group $SG_5GC

# MySQL database access - internal communication
aws ec2 authorize-security-group-ingress \
    --group-id $SG_5GC \
    --protocol tcp \
    --port 3306 \
    --source-group $SG_5GC

# External gNB/UERANSIM access
# N2 interface (NGAP) - SCTP port 38412 (using TCP as AWS doesn't support SCTP)
aws ec2 authorize-security-group-ingress \
    --group-id $SG_5GC \
    --protocol tcp \
    --port 38412 \
    --cidr 0.0.0.0/0

# N3 interface (GTP-U) - UDP port 2152 from external sources
aws ec2 authorize-security-group-ingress \
    --group-id $SG_5GC \
    --protocol udp \
    --port 2152 \
    --cidr 0.0.0.0/0

# SSH access for management
aws ec2 authorize-security-group-ingress \
    --group-id $SG_5GC \
    --protocol tcp \
    --port 22 \
    --cidr 0.0.0.0/0

# Allow all outbound traffic (for updates and Docker pulls)
aws ec2 authorize-security-group-egress \
    --group-id $SG_5GC \
    --protocol -1 \
    --cidr 0.0.0.0/0
```

### Security Group Rules Summary
| Port | Protocol | Source | Purpose |
|------|----------|--------|---------|
| 80/8080 | TCP | Internal SG | SBI Communication |
| 2152 | UDP | Internal SG | N4 Interface |
| 3306 | TCP | Internal SG | MySQL Database |
| 38412 | TCP | 0.0.0.0/0 | N2 Interface (gNB) |
| 2152 | UDP | 0.0.0.0/0 | N3 Interface (gNB) |
| 22 | TCP | 0.0.0.0/0 | SSH Management |
| All | All | 0.0.0.0/0 | Outbound Traffic |

## 2. EC2 Instance Creation

### Launch OAI 5GC Server
```bash
aws ec2 run-instances \
    --image-id ami-021589336d307b577 \
    --instance-type t3.xlarge \
    --key-name inference_key \
    --security-group-ids sg-038f0b60e6f34ccca \
    --subnet-id subnet-0050330fc6ba0e705 \
    --block-device-mappings '[{
        "DeviceName": "/dev/sda1",
        "Ebs": {
            "VolumeSize": 30,
            "VolumeType": "gp3",
            "DeleteOnTermination": true
        }
    }]' \
    --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=OAI-5GC-Server}]'
```

### Instance Configuration Summary
| Component | Specification |
|-----------|---------------|
| **AMI** | Ubuntu 22.04 LTS (ami-021589336d307b577) |
| **Instance Type** | t3.xlarge (4 vCPUs, 16 GiB RAM) |
| **Key Pair** | inference_key |
| **Security Group** | sg-038f0b60e6f34ccca (OAI 5GC configured) |
| **Storage** | 30 GiB GP3 EBS volume |
| **Network** | Private subnet (secure, outbound internet via NAT) |
| **VPC** | vpc-0463beebd475c520b |

## 3. Docker Installation

### Method 1: Official Docker Repository (Recommended)
```bash
# Update package index
sudo apt update

# Install required packages
sudo apt install -y ca-certificates curl gnupg lsb-release

# Add Docker's official GPG key
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

# Set up the repository
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Update package index again
sudo apt update

# Install Docker Engine, containerd, and Docker Compose plugin
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Start and enable Docker
sudo systemctl enable docker
sudo systemctl start docker

# Add user to docker group (so you don't need sudo)
sudo usermod -aG docker $USER

# Apply group membership (or logout/login)
newgrp docker
```

### Method 2: Ubuntu Repository (Alternative)
```bash
# Update and install Docker
sudo apt update
sudo apt install -y docker.io

# Download and install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Start Docker
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -aG docker $USER
newgrp docker
```

### Verify Docker Installation
```bash
# Check Docker version
docker --version

# Check Docker Compose version (new plugin method)
docker compose version

# OR check standalone Docker Compose
docker-compose --version

# Test Docker
docker run hello-world
```

## 4. OAI 5G Core Deployment

### Clone OAI Repository
```bash
# Clone the OAI 5G core repository
git clone https://gitlab.eurecom.fr/oai/cn5g/oai-cn5g-fed.git ~/oai-cn5g-fed
cd ~/oai-cn5g-fed
```

### Deploy OAI 5GC Services
```bash
# Navigate to docker-compose directory
cd ~/oai-cn5g-fed/docker-compose

# Start the basic 5GC
docker compose -f docker-compose-basic-nrf.yaml up -d

# Check all services are running
docker compose -f docker-compose-basic-nrf.yaml ps

# View logs
docker compose -f docker-compose-basic-nrf.yaml logs
```

## 5. Network Architecture

### VPC Configuration
- **VPC**: vpc-0463beebd475c520b (10.0.0.0/16)
- **Public Subnet**: subnet-0a1cd9e1248be09fa (10.0.1.0/24)
- **Private Subnet**: subnet-0050330fc6ba0e705 (10.0.2.0/24)
- **Internet Gateway**: igw-05dde53c121d759b6
- **NAT Gateway**: nat-007a911789451075b

### Security Features
- ✅ **Private Subnet**: EC2 instances protected from direct internet access
- ✅ **NAT Gateway**: Outbound internet access for updates and Docker pulls
- ✅ **Security Group**: All OAI 5GC network function ports configured
- ✅ **Route Tables**: Properly configured for internal and external communication

## 6. OAI 5GC Network Functions

### Deployed Services
| Service | Container Name | Purpose |
|---------|----------------|---------|
| **MySQL** | mysql | Database for subscriber data |
| **NRF** | oai-nrf | Network Repository Function |
| **AMF** | oai-amf | Access and Mobility Management Function |
| **SMF** | oai-smf | Session Management Function |
| **UPF** | oai-upf | User Plane Function |
| **UDM** | oai-udm | Unified Data Management |
| **UDR** | oai-udr | Unified Data Repository |
| **AUSF** | oai-ausf | Authentication Server Function |
| **External DN** | oai-ext-dn | External Data Network |

### Network Interfaces
- **N2**: AMF ↔ gNB (SCTP port 38412)
- **N3**: UPF ↔ gNB (GTP-U port 2152)
- **N4**: SMF ↔ UPF (GTP-C port 2152)
- **SBI**: Internal communication (HTTP/HTTPS ports 80/8080)

## 7. Access and Management

### SSH Access
```bash
# Using Session Manager (recommended for private subnet)
aws ssm start-session --target i-xxxxxxxxx

# Direct SSH (if bastion host available)
ssh -i inference_key.pem ubuntu@<PRIVATE_IP>
```

### Service Management
```bash
# Check service status
docker compose -f docker-compose-basic-nrf.yaml ps

# View specific service logs
docker compose -f docker-compose-basic-nrf.yaml logs oai-amf

# Restart services
docker compose -f docker-compose-basic-nrf.yaml restart

# Stop all services
docker compose -f docker-compose-basic-nrf.yaml down
```

## 8. Monitoring and Logs

### Export Logs to S3
```bash
# Export logs with timestamps
docker compose -f docker-compose-basic-nrf.yaml logs --timestamps > oai-5gc-logs-$(date +%Y%m%d-%H%M%S).txt

# Upload to S3
aws s3 cp oai-5gc-logs-$(date +%Y%m%d-%H%M%S).txt s3://your-bucket-name/oai-5gc-logs/
```

## 9. Backup and Recovery

### Create Snapshots and AMI
```bash
# Get instance information
INSTANCE_ID="i-xxxxxxxxx"
VOLUME_ID=$(aws ec2 describe-instances --instance-ids $INSTANCE_ID --query 'Reservations[0].Instances[0].BlockDeviceMappings[0].Ebs.VolumeId' --output text)

# Create EBS snapshot
aws ec2 create-snapshot --volume-id $VOLUME_ID --description "OAI-5GC-Server backup"

# Create AMI
aws ec2 create-image --instance-id $INSTANCE_ID --name "OAI-5GC-Server-AMI-$(date +%Y%m%d-%H%M%S)"
```

## Summary

This deployment provides a complete OAI 5G Core network with:
- ✅ **Secure Architecture**: Private subnet with NAT Gateway
- ✅ **Complete Network Functions**: All 5GC components deployed
- ✅ **Scalable Infrastructure**: AWS EC2 with proper security groups
- ✅ **Monitoring Capabilities**: Log export and backup solutions
- ✅ **Production Ready**: Proper networking and security configuration

The OAI 5G Core is now ready for integration with external gNB/UERANSIM components for end-to-end 5G network testing and development.