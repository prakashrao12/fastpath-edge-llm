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
- [Environment & Setup (Edge vs Cloud Inference)](#environment--setup-edge-vs-cloud-inference)
- [KPIs & Bench Rules](#kpis--bench-rules)
- [Latency Benchmarks (Scripts)](#latency-benchmarks-scripts)
- [Troubleshooting JSON (Both Engines)](#troubleshooting-json-both-engines)
- [Edge Log Triage & Auto-Remediation (oai-guard)](#edge-log-triage--auto-remediation-oai-guard)
  - [Overview](#overview)
  - [Installation](#installation)
  - [Configuration](#configuration)
  - [Usage Examples](#usage-examples)
  - [Auto-Remediation](#auto-remediation)
- [Repository Layout](#repository-layout)
- [Allow-List & Demo Service](#allow-list--demo-service)
- [Demo Runbook (Copy/Paste)](#demo-runbook-copypaste)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## Overall Solution

With 5G's rollout, delivering AI services in milliseconds has never been more critical. This session demonstrates how to deploy large language models (LLMs) on edge infrastructure leveraging OAI 5G Core for network functions and **llama.cpp**/**Ollama** for local inference to **reduce latency and cloud costs**.

You’ll learn how to:
- Optimize workload placement at the network edge  
- Enable CPU-only inference using `llama.cpp`/`Ollama`  
- Implement automated log triage and remediation with a strict allow-list  
- Balance reliability and resource constraints for real-time AI delivery in telecom networks

By the end, you'll have a practical blueprint for bringing real-time intelligence to users and unlocking new edge-driven innovation.

---

## System Architecture

```
5G UE → gNB → 5G Core (OAI/Open5GS) → /var/log/openair.log
                                            │
                                      [oai_guard.cli]
                                            │
                              Build prompt {error_line}
                                            │
                     ┌───────────────────────┴───────────────────────┐
                     │                                               │
             Local Inference (Ollama)                       Cloud Inference (OpenAI)
                     │                                               │
                     └─────────────── Structured JSON ───────────────┘
                              { summary, steps[], risk }
                                            │
                            /var/log/oai_incidents/incident_*.json
                                            │
                                 [optional] allow-listed executor
                                 e.g., `systemctl restart demo-svc`
```

> For the demo we can run **LLM-only** (skip heuristics/history) to showcase pure model behavior. The **same JSON contract** allows engine swap (edge ↔ cloud) without code changes.

---

## Inference Server Configuration at 5G Edge

This section guides you through setting up an LLM inference server at the 5G edge using a **CPU-based EC2 instance** running `llama.cpp`. The configuration ensures low-latency AI responses suitable for edge scenarios.

### Phase 1: EC2 Instance Setup

Provision an EC2 instance with the following specifications:

- **Instance Type:** `t3.large` (for dev) / `c7i.4xlarge` (for demo benchmarks)  
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

## Environment & Setup (Edge vs Cloud Inference)

**Host**: `c7i.4xlarge` (16 vCPU), Amazon Linux (for demo numbers)  
**Ollama**: running and warmed (`keep_alive:-1`)  
**Local model**: `phi3:mini` (fast micro-prompt baseline)  
**Cloud model**: `gpt-4o` (optionally `gpt-5` to highlight WAN/tails)  
**Python**: 3.9+

### Install
```bash
pip3 install -r requirements.txt
# requirements.txt:
# requests>=2.31.0
```

### Environment Variables
```bash
export OLLAMA_MODEL=phi3:mini
export OLLAMA_OPTS='{"temperature":0,"top_k":1,"top_p":0,"num_predict":8,"num_ctx":96,"num_thread":16,"keep_alive":-1}'

export OPENAI_MODEL=gpt-4o         # or gpt-5 if desired
export OPENAI_API_KEY=sk-...       # required for cloud path
```

### Warmup (avoid cold starts)
```bash
ollama list && systemctl status ollama
curl -sS http://localhost:11434/api/generate \
  -d '{"model":"'"$OLLAMA_MODEL"'","prompt":"ping","stream":false,"keep_alive":-1}' >/dev/null
python3 scripts/smoke_once.py --prompt OK --openai-model "$OPENAI_MODEL" --timeout 10 >/dev/null
```

---

## KPIs & Bench Rules

**Latency KPIs**
- **Total latency (E2E)**: request → last token
- **TTFB**: request → first token (perceived snappiness)
- **Distribution**: p50 / p90 / mean / std-dev

**Auto-Resolution KPIs**
- **Time-to-Diagnosis (TTD)**: error → JSON plan ready  
- **Time-to-Action (TTA)**: execution start → commands finished  
- **Success rate**: % incidents with successful allowed actions  
- **Audit completeness**: inputs + outputs + exit codes captured

**Bench Rules**
- Same prompt & token budget across engines
- Warm both engines
- Small `num_ctx`, limit `num_predict`
- ≥10 runs, with warmups; report p50 & p90

---

## Latency Benchmarks (Scripts)

All scripts are under `scripts/`.

### 1) Single run (total latency)
```bash
python3 scripts/smoke_once.py \
  --prompt 'Respond with only: OK' \
  --ollama-model "$OLLAMA_MODEL" --ollama-opts "$OLLAMA_OPTS" \
  --openai-model "$OPENAI_MODEL" --openai-max-tokens 8 --timeout 30
```

### 2) TTFB (streaming)
```bash
python3 scripts/ttfb_once.py \
  --prompt 'Respond with only: OK' \
  --ollama-model "$OLLAMA_MODEL" --ollama-opts "$OLLAMA_OPTS" \
  --openai-model "$OPENAI_MODEL" --openai-max-tokens 8 --timeout 30
```

### 3) Batch stats (p50/p90/mean/std)
```bash
python3 scripts/bench_latency.py \
  --prompt 'Respond with only: OK' \
  --runs 12 --warmup 2 --timeout 30 \
  --ollama-model "$OLLAMA_MODEL" --ollama-opts "$OLLAMA_OPTS" \
  --openai-model "$OPENAI_MODEL" --openai-max-tokens 8 \
  --csv bench_results.csv
```

---

## Troubleshooting JSON (Both Engines)

**Prompt contract** (save as `prompts/speed_prompt.json.txt`):
```
Return ONLY a JSON object with keys exactly:
- summary (<=20 words)
- steps (array of <=5 short shell commands; read-only where possible)
- risk ("low"|"medium"|"high")

ERROR:
{error_line}
```

**Compare engines** on the same error (no context for speed):
```bash
python3 scripts/diag_compare.py \
  --log /var/log/openair.log --window 0 \
  --prompt-template prompts/speed_prompt.json.txt \
  --ollama-model "$OLLAMA_MODEL" --ollama-opts "$OLLAMA_OPTS" \
  --openai-model "$OPENAI_MODEL" --openai-max-tokens 64 \
  --ttfb --runs 3 --timeout 30
```

Notes:
- Uses Ollama `format:"json"` and OpenAI `response_format` where supported.
- Auto-fallbacks for OpenAI (e.g., swap `max_tokens`→`max_completion_tokens` if needed; drop `response_format` if model rejects it).
- Logs raw model text if JSON is malformed.

---

## Edge Log Triage & Auto-Remediation (oai-guard)

### Overview

The `oai-guard` module provides production-ready log monitoring that:
- Extracts structured context from OAI/Open5GS logs
- Triages errors with **LLM-only** (or heuristics/history if enabled)
- Optionally auto-remediates common issues under strict guardrails
- Optimized for CPU-only edge deployments

**Features:**
- **LLM-only path** available (`--no-heur`, or `OAI_USE_HEUR=0`)
- Structured JSON: `{summary, steps[], risk}`
- **Auto-remediation**: allow-listed commands + audit logging

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

For LLM-based analysis, install and configure Ollama (optional if using OpenAI only):

```bash
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Pull a lightweight model
ollama pull llama3.2:1b

# Configure environment
export OLLAMA_MODEL=llama3.2:1b
export OLLAMA_OPTS='{"temperature":0,"num_ctx":128,"num_predict":32,"keep_alive":-1}'
```

### Usage Examples

**LLM-only, last error:**
```bash
python3 -m oai_guard.cli /var/log/openair.log --last --engine ollama --no-heur
# or
python3 -m oai_guard.cli /var/log/openair.log --last --engine openai --openai-model "$OPENAI_MODEL" --no-heur
```

**Comparison mode handled by diag script:** see [Troubleshooting JSON](#troubleshooting-json-both-engines).

### Auto-Remediation

Configure safe auto-restart policies (allow-list + audit):

```bash
# Example allow-list file
cat > allowlist/commands.allow <<'EOF'
/usr/bin/systemctl status demo-svc
/usr/bin/systemctl restart demo-svc
/bin/journalctl -u demo-svc -n 50
EOF

# Run with auto-remediation enabled (LLM-only)
python3 -m oai_guard.cli /var/log/openair.log \
  --last --engine openai --openai-model "$OPENAI_MODEL" \
  --auto --no-heur
```

**Systemd service setup (optional):**
```bash
sudo tee /etc/systemd/system/oai-guard.service << 'EOF'
[Unit]
Description=OAI Guard (edge triage & auto-remediation)
After=network-online.target

[Service]
WorkingDirectory=/path/to/repo
Environment=OLLAMA_MODEL=llama3.2:1b
Environment=OAI_USE_HEUR=0
ExecStart=/usr/bin/python3 -m oai_guard.cli /var/log/openair.log --last --engine ollama --auto --no-heur
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now oai-guard
```

---

## Repository Layout

```
.
├── README.md
├── requirements.txt
├── scripts/
│   ├── smoke_once.py          # single E2E latency (edge vs cloud)
│   ├── ttfb_once.py           # time-to-first-byte comparator
│   ├── bench_latency.py       # batch stats + CSV
│   └── diag_compare.py        # troubleshooting JSON + latency/TTFB
├── prompts/
│   └── speed_prompt.json.txt  # JSON contract prompt (fast, minimal context)
├── oai_guard/
│   ├── __init__.py
│   ├── cli.py                 # entrypoint; --no-heur flag; auto-exec
│   ├── model.py               # Ollama/OpenAI adapters (JSON modes, fallbacks)
│   ├── triage.py              # LLM-only triage; incident JSON builder
│   └── utils.py               # parsing, file I/O, allowlist runner
├── allowlist/
│   └── commands.allow         # whitelisted commands for auto-exec (demo-svc)
├── systemd/
│   └── demo-svc.service       # harmless demo service for restart demo
├── logs/
    └── sample_openair.log     # sample ERROR lines (for offline testing)

```

---

## Allow-List & Demo Service

**Allow list** (`allowlist/commands.allow`):
```
/usr/bin/systemctl status demo-svc
/usr/bin/systemctl restart demo-svc
/bin/journalctl -u demo-svc -n 50
```

**Demo service** (`systemd/demo-svc.service`):
```ini
[Unit]
Description=Demo Service (safe to restart)
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/sleep infinity
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
```

Enable:
```bash
sudo cp systemd/demo-svc.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now demo-svc
```

---

## Demo Runbook (Copy/Paste)

**1) Snapshot environment**
```bash
echo $OLLAMA_MODEL
echo $OPENAI_MODEL
ollama list
systemctl status ollama
```

**2) Warm both engines**
```bash
curl -sS http://localhost:11434/api/generate \
  -d '{"model":"'"$OLLAMA_MODEL"'","prompt":"ping","stream":false,"keep_alive":-1}' >/dev/null
python3 scripts/smoke_once.py --prompt OK --openai-model "$OPENAI_MODEL" --timeout 10 >/dev/null
```

**3) Micro-prompt (total latency)**
```bash
python3 scripts/smoke_once.py \
  --prompt 'Respond with only: OK' \
  --ollama-model "$OLLAMA_MODEL" --ollama-opts "$OLLAMA_OPTS" \
  --openai-model "$OPENAI_MODEL" --openai-max-tokens 8 --timeout 30
```

**4) TTFB**
```bash
python3 scripts/ttfb_once.py \
  --prompt 'Respond with only: OK' \
  --ollama-model "$OLLAMA_MODEL" --ollama-opts "$OLLAMA_OPTS" \
  --openai-model "$OPENAI_MODEL" --openai-max-tokens 8 --timeout 30
```

**5) Batch stats**
```bash
python3 scripts/bench_latency.py \
  --prompt 'Respond with only: OK' \
  --runs 12 --warmup 2 --timeout 30 \
  --ollama-model "$OLLAMA_MODEL" --ollama-opts "$OLLAMA_OPTS" \
  --openai-model "$OPENAI_MODEL" --openai-max-tokens 8 \
  --csv bench_results.csv
```

**6) Troubleshooting JSON (both engines)**
```bash
python3 scripts/diag_compare.py \
  --log /var/log/openair.log --window 0 \
  --prompt-template prompts/speed_prompt.json.txt \
  --ollama-model "$OLLAMA_MODEL" --ollama-opts "$OLLAMA_OPTS" \
  --openai-model "$OPENAI_MODEL" --openai-max-tokens 64 \
  --ttfb --runs 3 --timeout 30
```

**7) Auto-Resolution (LLM-only)**
```bash
export OAI_USE_HEUR=0
export OAI_USE_HISTORY=0
python3 -m oai_guard.cli /var/log/openair.log \
  --last --engine openai --auto --openai-model "$OPENAI_MODEL" --no-heur
tail -n +1 /var/log/oai_incidents/incident_*.json | tail -200
systemctl status demo-svc
```

---

## Troubleshooting

- **Ollama slow/timeout**
  - Pre-warm (`keep_alive:-1`), reduce `num_ctx` & `num_predict`
  - Set `num_thread ≈ vCPU`, ensure enough RAM (avoid swap)
- **OpenAI 400**
  - Scripts auto-swap `max_tokens`→`max_completion_tokens` where required
  - Some models reject `response_format`; fallback to plain text parsing
- **Heuristics accidentally ON**
  - Use `--no-heur` (CLI flag overrides env)
- **JSON malformed**
  - Ollama uses `format:"json"`; OpenAI uses `response_format` then fallback
  - Raw model text is logged alongside incident JSON

