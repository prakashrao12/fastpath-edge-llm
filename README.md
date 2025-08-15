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
  - [What You Get](#what-you-get)
  - [Install (Project Layout)](#install-project-layout)
  - [Configure Ollama (Edge LLM)](#configure-ollama-edge-llm)
  - [Quickstart (90 Seconds)](#quickstart-90-seconds)
  - [Common Modes](#common-modes)
  - [Decision Pipeline & Execution Order](#decision-pipeline--execution-order)
  - [Auto-Restart (Safe by Default)](#auto-restart-safe-by-default)
  - [End-to-End Demo: Auto-Restart a Service](#end-to-end-demo-auto-restart-a-service)
  - [Run as a Systemd Service](#run-as-a-systemd-service)
  - [Tuning & Tips](#tuning--tips)
  - [Troubleshooting](#troubleshooting)

---

## Overall Solution

With 5G’s rollout, delivering AI services in milliseconds has never been more critical. This session shows how to deploy large language models (LLMs) on edge infrastructure leveraging Open5GS for a virtualized 5G core and **Ollama** (or `llama.cpp`) for local inference to slash latency and cloud expenses.

You’ll learn how to:

- Optimize workload placement at the network edge.  
- Enable CPU-only inference using `llama.cpp`.  
- Balance reliability and resource constraints for real-time AI delivery in telecom networks.

By the end, you’ll have a practical blueprint for bringing real-time intelligence to users and unlocking new edge-driven innovation.

---

## System Architecture

*(High-level diagram omitted for brevity: 5G UE → gNB → 5G Core (Open5GS/OAI) → Edge Inference (llama.cpp/Ollama) → Backhaul/Analytics)*

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

# Optionally install llama-cpp Python bindings (useful for server integration)
pip3 install 'llama-cpp-python[server]' --user

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

# (Optional) Clean up any previous build artifacts
rm -rf build

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
# Configure Git to store your Hugging Face credentials
git config --global credential.helper store

# Install or upgrade the Hugging Face Hub CLI tool
pip3 install --upgrade huggingface_hub --user

# Log in to Hugging Face (paste your access token when prompted)
~/.local/bin/huggingface-cli login

# Download a quantized GGUF model to the models directory
~/.local/bin/huggingface-cli download QuantFactory/Meta-Llama-3-8B-Instruct-GGUF   --include "Meta-Llama-3-8B-Instruct.Q4_K_M.gguf"   --local-dir ~/llama.cpp/models
```

### Phase 5: Running Inference

```bash
cd ~/llama.cpp/build/bin

./llama-run ../../models/Meta-Llama-3-8B-Instruct.Q4_K_M.gguf   "Write a haiku about the Amazon cloud."
```

---

# Edge Log Triage & Auto-Remediation (oai-guard)

This module adds a production-ready log watcher that (a) extracts structured context from Open5GS/OAI-style logs, (b) triages errors via **Ollama** *or* fast **heuristics**, and (c) can **auto-restart** systemd services under strict guardrails. Optimized for CPU-only edge nodes.

## What You Get

- **Fast path**: regex heuristics for common telecom errors → instant triage (no LLM call).  
- **Smart path**: LLM (via Ollama) produces structured JSON: `summary`, `causes`, `diagnostics_cmds`, `fix_cmds`, `risk_level`, `need_human_review`.  
- **Auto-remediation**: optional `systemctl restart <service>` with whitelist/policy + active-state verification.  
- **History cache**: reuses prior triage for identical errors (instant).  
- **Prove-it mode**: embed the structured JSON & prompt preview in each incident file.

---

## Install (Project Layout)

From the **repo root**:

```bash
# Package files:
# oai_guard/
#   actions.py   cli.py    config.py  history.py  model.py
#   parsing.py   sources.py triage.py  __init__.py
# requirements.txt

python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt   # minimal: requests

# Output directory
sudo mkdir -p /var/log/oai_incidents
sudo chown "$USER":"$USER" /var/log/oai_incidents
```

> If not using a venv on Amazon Linux, ensure `requests>=2.25.1` is available.

---

## Configure Ollama (Edge LLM)

Ensure the daemon is running and a model is available:

```bash
ollama pull llama3.2              # or smaller: llama3.2:1b
export OLLAMA_MODEL=llama3.2
export KEEP_ALIVE=-1              # keep model hot in RAM
```

---

## Quickstart (90 Seconds)

Process only the **last** error in your log (fast, heuristic-only, no diagnostics):

```bash
export CONTEXT_LINES=10
export WINDOW=120
export FAST_FIRST=1
export SKIP_DIAG=1

python3 -m oai_guard.cli /var/log/openair.log   --last --fast --fast-only --no-diagnostics -v
```

An incident JSON is written to `/var/log/oai_incidents/incident_<timestamp>.json`.

---

## Common Modes

- **Heuristic only (instant):**
  ```bash
  python3 -m oai_guard.cli /var/log/openair.log --last --fast --fast-only
  ```

- **LLM only (always use the model):**
  ```bash
  python3 -m oai_guard.cli /var/log/openair.log --last --no-fast -v
  ```

- **Heuristic → then verify/augment with LLM:**
  ```bash
  python3 -m oai_guard.cli /var/log/openair.log --last --fast --llm-verify -v
  # or
  python3 -m oai_guard.cli /var/log/openair.log --last --fast --llm-augment -v
  ```

- **Prove JSON input to the model (embed in incident):**
  ```bash
  python3 -m oai_guard.cli /var/log/openair.log --last --prove-json
  ```

- **Feed pure JSON instead of a text log:**
  ```bash
  python3 -m oai_guard.cli --json-file ./events.json --last --fast
  ```

---

## Decision Pipeline & Execution Order

**Goal:** turn a log line into a structured incident (and optionally auto-remediate) with the fastest safe path.

### Inputs
- **Log input:** last error (`--last`), full scan (`--once`), live tail (default), or JSON events (`--json-file`).
- **Context:** last `CONTEXT_LINES` lines (env) around the error.
- **Config knobs:** `--fast/--no-fast/--fast-only`, `--llm-verify/--llm-augment`, `--no-history`, `--auto`, `--no-diagnostics`, plus env (e.g., `FAST_FIRST`, `KEEP_ALIVE`, `AUTO_POLICY`, etc.).

### Execution Order

1) **History Cache (instant reuse)**
   - **When:** enabled by default; disable with `--no-history`.
   - **How:** build a normalized *signature* of the error line (strip timestamps/IPs/IDs).
   - **Outcome:** if signature is in SQLite cache, **reuse** the stored triage JSON and continue to step 6.
   - **Source tag:** `source = "history"`.

2) **Heuristic Fast-Path (regex recipes)**
   - **When:** on if `--fast` (or `FAST_FIRST=1`); off with `--no-fast`.
   - **How:** match error line against `_HEUR` (and any dynamic rules). If matched, emit a complete triage dict *without calling the model*.
   - **Outcome:** triage is ready; proceed to step 3 (and possibly step 4 if you requested LLM verify/augment).
   - **Source tag:** `source = "heuristic"`.

3) **LLM Fallback (or Always, if `--no-fast`)**
   - **When:** 
     - Run if **no** history & **no** heuristic **and** not `--fast-only`, **or**
     - After a heuristic match **if** you asked for `--llm-verify` or `--llm-augment`.
   - **How:** send prompt with (a) raw context text and (b) **structured JSON** context; parse **strict JSON** reply.
   - **Outcome:**
     - **Fallback:** fills triage from model. `source = "llm"`.
     - **Verify:** replace heuristic output with LLM output. `source = "llm"`.
     - **Augment:** merge LLM details into heuristic output. `source = "heuristic+llm"`.
   - **Note:** `--fast-only` prevents any LLM call.

4) **Cache Save (for future instant hits)**
   - **When:** if you produced new triage (heuristic or LLM) and history is enabled.
   - **Outcome:** store triage by signature in SQLite.

5) **Diagnostics (optional)**
   - **When:** unless `--no-diagnostics` or `SKIP_DIAG=1`.
   - **How:** run `diagnostics_cmds` (filtered by `ALLOWLIST`).
   - **Outcome:** capture command results in the incident file.

6) **Auto-Remediation (guardrailed)**
   - **When:** only if `--auto` and triage indicates **`risk_level: "low"`** AND **`need_human_review: false`**.
   - **Policy:**
     - Command must pass `ALLOWLIST` (e.g., `systemctl restart`).
     - Then pass `AUTO_POLICY`:
       - `oai_only` (default): service name must start with `oai-`
       - `whitelist`: service must appear in `WHITELIST_FILE`
       - `any`: allow any service (⚠️ risky)
   - **Verification:** after `systemctl restart <svc>`, poll `systemctl is-active <svc>` until `active` or timeout (`AUTO_VERIFY_TIMEOUT`, `AUTO_VERIFY_INTERVAL`).
   - **Outcome:** results appended to incident; `auto_ran = true` if at least one fix executed.

7) **Incident Persistence**
   - **Path:** `/var/log/oai_incidents/incident_<timestamp>.json`
   - **Contents:** 
     - `source` (`history` | `heuristic` | `llm` | `heuristic+llm` | `none`)
     - `summary`, `causes`, `diagnostics_cmds`, `fix_cmds`, `risk_level`, `need_human_review`
     - `results` (diagnostic/fix outputs), `auto_ran`
     - *(optional)* `structured_context`, `prompt_preview` if `--prove-json`


### Flag Cheat-Sheet

- **Speed:** `--fast --fast-only` (instant if heuristic/history matches), `KEEP_ALIVE=-1`, small `CONTEXT_LINES`.
- **Model behavior:** `--no-fast` (always LLM), `--llm-verify` / `--llm-augment` (after heuristic).
- **History:** `--no-history` disables reuse; otherwise enables instant repeats.
- **Auto-fix:** `--auto` + `AUTO_POLICY` (`oai_only` | `whitelist` | `any`) + `ALLOWLIST`.
- **Proof:** `--prove-json` embeds the structured JSON input and prompt preview in incidents.

---

## Auto-Restart (Safe by Default)

Decide which services can be auto-restarted.

**Policy knobs (env):**
```bash
export ALLOWLIST="systemctl status,systemctl restart,journalctl -u,grep,tail"
export AUTO_POLICY=oai_only                # 'oai_only' | 'whitelist' | 'any'
export WHITELIST_FILE=/etc/oai-guard-whitelist.txt
export AUTO_VERIFY_TIMEOUT=20             # seconds to wait for 'active'
export AUTO_VERIFY_INTERVAL=2
```

Run with auto-remediation enabled:

```bash
python3 -m oai_guard.cli /var/log/openair.log   --last --fast --auto -v   --auto-policy whitelist --whitelist-file /etc/oai-guard-whitelist.txt
```

Auto-restart executes **only** when triage marks `risk_level: "low"` and `need_human_review: false`. The incident contains verification:

```json
{
  "cmd": "systemctl restart oai-smf",
  "rc": 0,
  "verify_state": "active",
  "verify_rc": 0
}
```

---

## End-to-End Demo: Auto-Restart a Service

Create a tiny service and emit a demo error line; the guard restarts it and verifies state.

```bash
# 1) Whitelist our demo service
echo "demo-svc" | sudo tee /etc/oai-guard-whitelist.txt

# 2) Minimal service that runs forever
cat | sudo tee /etc/systemd/system/demo-svc.service >/dev/null <<'UNIT'
[Unit]
Description=Demo long-running service
[Service]
Type=simple
ExecStart=/usr/bin/sleep infinity
[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now demo-svc
systemctl is-active demo-svc

# 3) Simulate failure and emit a demo error line recognized by heuristics
sudo systemctl stop demo-svc
printf "[DEMO] ERROR service demo-svc down\n" | sudo tee -a /var/log/openair.log

# 4) Run guard: fast triage + auto restart + whitelist policy
python3 -m oai_guard.cli /var/log/openair.log   --last --fast --fast-only --auto --no-diagnostics -v   --auto-policy whitelist --whitelist-file /etc/oai-guard-whitelist.txt

# 5) Confirm
systemctl is-active demo-svc
# expect: active
```

Inspect the latest incident:

```bash
jq '{ts:.timestamp, source, summary:.summary, fixes:.fix_cmds, auto:.auto_ran, results:.results}'   $(ls -1 /var/log/oai_incidents/incident_*.json | tail -n1)
```

---

## Run as a Systemd Service

Keep the guard hot on boot and persist defaults:

```ini
# /etc/systemd/system/oai-guard.service
[Unit]
Description=OAI Guard (edge triage & auto-remediation)
After=network-online.target

[Service]
WorkingDirectory=/path/to/repo
Environment=PYTHONPATH=/path/to/repo
Environment=OLLAMA_MODEL=llama3.2
Environment=KEEP_ALIVE=-1
Environment=CONTEXT_LINES=10
Environment=WINDOW=120
Environment=FAST_FIRST=1
Environment=SKIP_DIAG=1
Environment=HISTORY_DB=/var/log/oai_incidents/triage_cache.sqlite3
Environment=AUTO_POLICY=whitelist
Environment=WHITELIST_FILE=/etc/oai-guard-whitelist.txt
ExecStart=/usr/bin/python3 -m oai_guard.cli /var/log/openair.log
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Enable:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now oai-guard
sudo journalctl -u oai-guard -f
```

---

## Tuning & Tips

- **Speed on CPU:** prefer smaller models like `llama3.2:1b` for ultra-fast responses.  
- **Warm model:** `KEEP_ALIVE=-1` keeps it resident; `ollama ps` to confirm.  
- **Context size:** keep `CONTEXT_LINES` small (10–20) for snappy calls.  
- **Heuristics:** add your real error signatures to `oai_guard/triage.py` for instant results.  
- **History:** enable `oai_guard/history.py` + `HISTORY_DB` to reuse triage across runs.  
- **Proof:** use `--prove-json` to embed `structured_context` and `prompt_preview` into incidents.

---

## Troubleshooting

- **No output with `-m`:** ensure `oai_guard/cli.py` ends with:
  ```python
  if __name__ == "__main__":
      main()
  ```
- **Ollama 400 errors:** ensure the model is pulled (`ollama list`). The client auto-falls back from streaming if needed.
- **pip/RPM conflicts (Amazon Linux):** use a **virtualenv** to avoid system `requests` package issues.
- **Permissions:** incident dir is `/var/log/oai_incidents`. Ensure the running user can write to it.
