# Millisecond AI: LLM Inference at the 5G Edge

## Global Data & AI Virtual Tech Conference 2025

This repository supports the "Millisecond AI" session from the Global Data & AI Virtual Tech Conference 2025. It demonstrates how to deploy a production-grade AI inference pipeline at the 5G edge using open-source technologies and CPU-based infrastructure.

---

## Table of Contents

1. [Overall Solution](#overall-solution)
2. [System Architecture](#system-architecture)
3. [Inference Server Configuration at 5G Edge](#inference-server-configuration-at-5g-edge)
   - [Phase 1: EC2 Instance Setup](#phase-1-ec2-instance-setup)
   - [Phase 2: System Dependencies Installation](#phase-2-system-dependencies-installation)
   - [Phase 3: Building llama.cpp from Source](#phase-3-building-llamacpp-from-source)
   - [Phase 4: Downloading the LLM Model](#phase-4-downloading-the-llm-model)
   - [Phase 5: Running Inference](#phase-5-running-inference)
4. [Results](#results)
5. [Conclusions & Takeaways](#conclusions--takeaways)

---

## Overall Solution

With 5G’s rollout, delivering AI services in milliseconds has never been more critical. This session shows how to deploy large language models (LLMs) on edge infrastructure leveraging **Open5GS** for a virtualized 5G core and **Ollama** for local inference to slash latency and cloud expenses.

We walk through a production-grade architecture and demo a simulated 5G device calling an edge-hosted AI endpoint. You’ll learn how to:

- Optimize workload placement at the network edge.
- Enable CPU-only inference using llama.cpp.
- Balance reliability and resource constraints for real-time AI delivery in telecom networks.

By the end, you’ll have a **practical blueprint** for bringing real-time intelligence to users and unlocking **new edge-driven innovation** in the AI & Data Innovations track.

---

## System Architecture


## Inference Server Configuration at 5G Edge

This section guides you through setting up an LLM inference server at the 5G edge using a CPU-based EC2 instance running `llama.cpp`. The configuration ensures low-latency AI responses suitable for edge scenarios.

---

### Phase 1: EC2 Instance Setup

Provision an EC2 instance with the following specifications:

- **Instance Type**: `t3.large`
- **Storage**: At least 40 GB
- **AMI**: Amazon Linux 2023 or compatible RHEL-based OS

Connect to your EC2 instance via SSH:

```bash
ssh -i <your-key>.pem ec2-user@<your-ec2-public-ip>

```

### Phase 2: System Dependencies Installation

Install all the required system tools and dependencies for building and running `llama.cpp` on a CPU-based EC2 instance:

```bash
# Update all system packages
sudo yum update -y

# Install Python 3, pip, and Git
sudo yum install -y python3-pip git

# Install Development Tools (gcc, g++, make, etc.)
sudo yum groupinstall "Development Tools" -y

# Optionally install llama-cpp Python bindings (useful for server integration)
pip3 install 'llama-cpp-python[server]' --user

# Install cURL development library (used by C++ tools)
sudo yum install libcurl-devel -y

# Install CMake 3 (required to build llama.cpp)
sudo yum install cmake3 -y

# Set cmake3 as the default 'cmake' command
sudo alternatives --install /usr/bin/cmake cmake /usr/bin/cmake3 1
```

### Phase 3: Building llama.cpp from Source

With all dependencies installed, now compile the `llama.cpp` library optimized for your EC2 CPU instance:

```bash
# Clone the official llama.cpp GitHub repository
git clone https://github.com/ggml-org/llama.cpp
cd llama.cpp

# (Optional) Clean up any previous build artifacts
rm -rf build

# Create a new build directory and move into it
mkdir build && cd build

# Configure the build to include the server and example binaries
cmake .. -DLLAMA_CURL=OFF -DLLAMA_BUILD_EXAMPLES=ON -DLLAMA_BUILD_SERVER=ON

# Compile the project using all available CPU cores
cmake --build . --config Release -j$(nproc)
```

### Phase 4: Downloading the LLM Model

With the inference server compiled, the next step is to download a quantized LLM in GGUF format from Hugging Face.

#### Step 1: Configure Git and Hugging Face CLI

```bash
# Configure Git to store your Hugging Face credentials
git config --global credential.helper store

# Install or upgrade the Hugging Face Hub CLI tool
pip install --upgrade huggingface_hub

# Log in to Hugging Face (you will be prompted to paste your access token)
huggingface-cli login

# Download a quantized GGUF model to the models directory in your llama.cpp setup
huggingface-cli download QuantFactory/Meta-Llama-3-8B-Instruct-GGUF \
  --include "Meta-Llama-3-8B-Instruct.Q4_K_M.gguf" \
  --local-dir ~/llama.cpp/models
```

### Phase 5: Running Inference

Now that everything is set up, you can run the compiled LLM inference binary using your downloaded model.

#### Step 1: Navigate to the compiled binaries

```bash
cd ~/llama.cpp/build/bin


./llama-run ../../models/Meta-Llama-3-8B-Instruct.Q4_K_M.gguf \
  "Write a haiku about the Amazon cloud."

```