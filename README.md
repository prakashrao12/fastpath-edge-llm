# Millisecond AI: LLM Inference at the 5G Edge  
**Global Data & AI Virtual Tech Conference 2025**

This repository supports the "Millisecond AI" session from the Global Data & AI Virtual Tech Conference 2025. It demonstrates how to deploy a production-grade AI inference pipeline at the 5G edge using open-source technologies and CPU-based infrastructure.

---

## Table of Contents
- [Overall Solution](#overall-solution)
- [System Architecture](#system-architecture)
- [Inference Server Configuration at 5G Edge](#inference-server-configuration-at-5g-edge)
  - [Phase 1: EC2 Instance Setup](#phase-1-ec2-instance-setup)
  - [Phase 2: System Dependencies Installation](#phase-2-system-dependencies-installation)
  - [Phase 3: Building llama.cpp from Source](#phase-3-building-llamacpp-from-source)
  - [Phase 4: Downloading the LLM Model](#phase-4-downloading-the-llm-model)
  - [Phase 5: Running Inference](#phase-5-running-inference)
- [Edge Log Triage & Auto-Remediation (oai-guard)](#edge-log-triage--auto-remediation-oai-guard)
  - [Overview](#overview)
  - [Installation](#installation)
  - [Configuration](#configuration)
  - [Usage Examples](#usage-examples)
  - [Auto-Remediation](#auto-remediation)

---

## Overall Solution

With 5G's rollout, delivering AI services in milliseconds has never been more critical. This session demonstrates how to deploy large language models (LLMs) on edge infrastructure leveraging OAI 5G Core for network functions and **llama.cpp** for local inference to slash latency and cloud expenses.

You'll learn how to:

- Optimize workload placement at the network edge  
- Enable CPU-only inference using `llama.cpp`  
- Implement automated log triage and remediation
- Balance reliability and resource constraints for real-time AI delivery in telecom networks

By the end, you'll have a practical blueprint for bringing real-time intelligence to users and unlocking new edge-driven innovation.

---

## System Architecture

*(High-level diagram: 5G UE → gNB → 5G Core (OAI) → Edge Inference (llama.cpp) → Log Triage & Auto-Remediation → Backhaul/Analytics)*

---

## Inference Server Configuration at 5G Edge

This section guides you through setting up an LLM inference server at the 5G edge using a **CPU-based EC2 instance** running `llama.cpp`. The configuration ensures low-latency AI responses suitable for edge scenarios.

### Phase 1: EC2 Instance Setup

Provision an EC2 instance with the following specifications:

- **Instance Type:** `t3.large`  
- **Storage:** ≥ **40 GB**  
- **AMI:** **Amazon Linux 2023** or compatible RHEL-based OS

Connect via SSH:
```bash
ssh -i <your-key>.pem ec2-user@<your-ec2-public-ip>
```

### Phase 2: System Dependencies Installation

Install required tools and dependencies:

```bash
# Update all system packages
sudo yum update -y

# Install Python 3, pip, and Git
sudo yum install -y python3-pip git

# Install Development Tools (gcc, g++, make, etc.)
sudo yum groupinstall "Development Tools" -y

# Install cURL development library (used by C++ tools)
sudo yum install -y libcurl-devel

# Install CMake 3 (required to build llama.cpp)
sudo yum install -y cmake3

# Set cmake3 as the default 'cmake' command
sudo alternatives --install /usr/bin/cmake cmake /usr/bin/cmake3 1
```

### Phase 3: Building llama.cpp from Source

```bash
# Clone the official llama.cpp GitHub repository
git clone https://github.com/ggml-org/llama.cpp
cd llama.cpp

# Create a new build directory and move into it
mkdir build && cd build

# Configure the build to include the server and example binaries
cmake .. -DLLAMA_CURL=OFF -DLLAMA_BUILD_EXAMPLES=ON -DLLAMA_BUILD_SERVER=ON

# Compile the project using all available CPU cores
cmake --build . --config Release -j"$(nproc)"
```

### Phase 4: Downloading the LLM Model

Download a quantized **GGUF** model from Hugging Face:

```bash
# Install the Hugging Face Hub CLI tool
pip3 install --upgrade huggingface_hub --user

# Log in to Hugging Face (paste your access token when prompted)
~/.local/bin/huggingface-cli login

# Download a quantized GGUF model to the models directory
~/.local/bin/huggingface-cli download QuantFactory/Meta-Llama-3-8B-Instruct-GGUF \
  --include "Meta-Llama-3-8B-Instruct.Q4_K_M.gguf" \
  --local-dir ~/llama.cpp/models
```

### Phase 5: Running Inference

```bash
cd ~/llama.cpp/build/bin

./llama-run ../../models/Meta-Llama-3-8B-Instruct.Q4_K_M.gguf \
  "Write a haiku about the Amazon cloud."
```

**For convenience, add to PATH:**
```bash
echo 'export PATH="$HOME/llama.cpp/build/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc

# Now run from anywhere
llama-run ~/llama.cpp/models/Meta-Llama-3-8B-Instruct.Q4_K_M.gguf "Your prompt here"
```

---

## Edge Log Triage & Auto-Remediation (oai-guard)

### Overview

The `oai-guard` module provides production-ready log monitoring that:
- Extracts structured context from OAI/Open5GS logs
- Triages errors using fast heuristics or LLM analysis
- Automatically remediates common issues under strict guardrails
- Optimized for CPU-only edge deployments

**Features:**
- **Fast path**: Regex heuristics for instant triage (no LLM call)
- **Smart path**: LLM analysis with structured JSON output
- **Auto-remediation**: Controlled service restarts with verification
- **History cache**: Reuses prior analysis for identical errors

### Installation

```bash
# From repository root
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt

# Create output directory
sudo mkdir -p /var/log/oai_incidents
sudo chown "$USER":"$USER" /var/log/oai_incidents
```

### Configuration

For LLM-based analysis, install and configure Ollama:

```bash
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Pull a lightweight model
ollama pull llama3.2:1b

# Configure environment
export OLLAMA_MODEL=llama3.2:1b
export KEEP_ALIVE=-1  # Keep model hot in RAM
```

### Usage Examples

**Fast heuristic-only triage (instant):**
```bash
python3 -m oai_guard.cli /var/log/openair.log --last --fast --fast-only
```

**LLM analysis for complex issues:**
```bash
python3 -m oai_guard.cli /var/log/openair.log --last --no-fast -v
```

**Combined approach (heuristic → LLM verification):**
```bash
python3 -m oai_guard.cli /var/log/openair.log --last --fast --llm-verify -v
```

### Auto-Remediation

Configure safe auto-restart policies:

```bash
# Set environment variables
export AUTO_POLICY=oai_only  # Only restart OAI services
export ALLOWLIST="systemctl status,systemctl restart,journalctl -u"
export AUTO_VERIFY_TIMEOUT=20

# Run with auto-remediation enabled
python3 -m oai_guard.cli /var/log/openair.log --last --fast --auto -v
```

**Systemd service setup:**
```bash
# Create service file
sudo tee /etc/systemd/system/oai-guard.service << 'EOF'
[Unit]
Description=OAI Guard (edge triage & auto-remediation)
After=network-online.target

[Service]
WorkingDirectory=/path/to/repo
Environment=OLLAMA_MODEL=llama3.2:1b
Environment=KEEP_ALIVE=-1
Environment=AUTO_POLICY=oai_only
ExecStart=/usr/bin/python3 -m oai_guard.cli /var/log/openair.log
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable --now oai-guard
```

---

## Additional Resources

- **OAI 5G Core Setup**: See `Open-Air/README.md` for complete OAI 5G Core deployment guide
- **Network Architecture**: Detailed AWS VPC and security group configurations
- **Performance Tuning**: CPU optimization and model quantization techniques

---

## Contributing

This project demonstrates edge AI deployment for the Global Data & AI Virtual Tech Conference 2025. For questions or improvements, please refer to the session materials or contact the maintainers.
