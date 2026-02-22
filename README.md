

# AI Control Plane

### A Constrained AI Orchestration Layer for Jira-Driven DevOps Automation

---

## Executive Summary

AI Control Plane is an intelligent orchestration system that converts structured Jira tickets into governed, policy-constrained Rundeck automation workflows.

The system uses a Large Language Model (LLM) as a planning engine — not as an executor. All execution remains deterministic, validated, and controlled.

This architecture demonstrates how AI can assist DevOps automation without sacrificing governance, security, or operational safety.

---

## Problem Statement

DevOps teams frequently:

* Interpret Jira tickets manually
* Write repetitive deployment runbooks
* Execute shell commands with risk of human error
* Maintain inconsistent release processes

While AI can generate automation steps, directly allowing AI to execute commands introduces serious risks:

* Command hallucination
* Prompt injection
* Privileged execution
* Environment drift

Organizations need AI-assisted automation that is constrained, auditable, and deterministic.

---

## Solution Overview

AI Control Plane separates planning from execution.

The system operates in five stages:

1. Jira as Source of Truth
   Structured metadata is extracted from Jira tickets.

2. LLM as Planning Engine
   The model generates a structured execution plan under strict schema constraints.

3. Policy Enforcement Layer
   Output is restricted to allowed command sets and path rules.

4. Deterministic YAML Transformation
   The plan is converted into Rundeck-compatible job definitions.

5. Rundeck as Execution Engine
   Execution occurs via authenticated API calls, with monitoring and status polling.

Only one component is probabilistic: the planner.
All execution logic is deterministic.

---

## Architecture

Jira → AI Planner → Policy Constraints → YAML Builder → Rundeck Execution

Design principle:

* AI suggests
* Code validates
* Rundeck executes

This ensures AI remains advisory, not authoritative.

---

## Core Design Principles

### Constrained Intelligence

The LLM is restricted to:

* Fixed step count
* Explicit JSON schema
* Limited shell command whitelist
* Strict directory boundaries
* No privileged/system-level commands

This reduces attack surface and prevents unsafe execution.

---

### Deterministic Execution

All runtime execution occurs inside Rundeck.
No AI-generated command runs outside a validated job definition.

---

### Separation of Concerns

Planning, validation, and execution are separate subsystems.
This enables auditability and replaceable AI backends.

---

### Graceful Degradation

Missing Jira metadata (e.g., fixVersion) defaults safely.
The system remains operational under partial inputs.

---

## System Components

### Jira Integration

* Fetches issue metadata
* Extracts structured fields
* Normalizes version and status data

### AI Planning Engine

* Generates structured JSON plan
* Operates under strict command constraints
* Enforces environment variable path structure

### YAML Builder

* Converts structured plan to Rundeck YAML
* Injects controlled job options
* Ensures API-compatible format

### Rundeck Integration

* Imports or updates jobs
* Executes via API
* Polls execution state
* Provides traceable execution logs

### Interfaces

* CLI Control Plane (main.py)
* Streamlit UI for interactive governance

---

## Governance & Safety Controls

The system enforces:

* Allowed commands: echo, mkdir, touch, ls, date, whoami
* Controlled directory root:
  `${option.environment}/releases/${option.version}`
* No sudo
* No docker
* No systemctl
* No absolute paths
* No destructive operations

These constraints prevent prompt injection escalation and unsafe execution.

---

## Operational Flow

1. User enters Jira Issue Key
2. Extracted Jira metadata is displayed
3. AI-generated runbook preview is shown
4. Manual approval before job creation
5. Controlled execution with monitored status

Human approval remains in the loop.

---

## Project Structure

```
ai-control-plane/
│
├── services/
│   ├── jira.py
│   ├── llm.py
│   ├── rundeck.py
│   ├── jobroute.py
│
├── streamlit_app.py
├── main.py
├── schemas.py
├── requirements.txt
├── Dockerfile
└── .env (local only)
```

---

## Environment Configuration

Create a `.env` file locally:

```
# Jira
JIRA_BASE_URL=
JIRA_EMAIL=
JIRA_API_TOKEN=

# LLM
CEREBRAS_BASE_URL=
CEREBRAS_API_KEY=
CEREBRAS_MODEL=

# Rundeck
RUNDECK_BASE_URL=
RUNDECK_API_TOKEN=
RUNDECK_PROJECT=
```

Never commit `.env` to version control.

---

## Running the Project

### CLI Mode

```
python main.py
```

### Streamlit UI

```
streamlit run streamlit_app.py
```

---

## Security Model

Threat: Prompt Injection
Mitigation: Hard-coded command whitelist + structured schema

Threat: Command Escalation
Mitigation: No privileged commands allowed

Threat: Path Traversal
Mitigation: Forced directory prefix

Threat: Hallucinated Operations
Mitigation: Deterministic YAML transformation

The architecture assumes AI is fallible and designs around that assumption.

---

## Strategic Significance

AI Control Plane demonstrates a second-order automation model:

It automates the creation of automation under constraint.

Rather than replacing DevOps engineers, it augments structured workflow generation while preserving control boundaries.

This serves as a reference architecture for:

* Enterprise AI governance
* AI-in-the-loop orchestration
* Safe LLM-driven infrastructure planning

---

## Roadmap

Planned enhancements:

* JSON schema validation enforcement
* Command token scanning before YAML generation
* Risk scoring based on Jira metadata
* Auto-generated rollback plans
* Execution simulation before run
* Webhook-triggered automation
* Execution audit dashboard

---

## Conclusion

AI Control Plane represents a governance-first approach to AI automation.

Instead of asking:

“Can AI execute commands?”

It asks:

“How can AI propose actions within controlled, deterministic boundaries?”

The result is a constrained orchestration layer where intelligence operates under policy — not instead of it.

---

