# ADR-001: Claude Code + Ollama Hybrid Agent Architecture

**Status:** Accepted  
**Date:** 2026-05-11  
**Authors:** sam@nicheworxs.com  
**Platforms:** macOS (Apple M3) · Windows 11 Pro

---

## Table of Contents

1. [Context](#1-context)
2. [Decision](#2-decision)
3. [Consequences](#3-consequences)
4. [Architecture](#4-architecture)
5. [Prerequisites](#5-prerequisites)
6. [File Structure](#6-file-structure)
7. [Implementation](#7-implementation)
   - 7.1 [Ollama Setup](#71-ollama-setup)
   - 7.2 [MCP Server](#72-mcp-server)
   - 7.3 [Claude Code Configuration](#73-claude-code-configuration)
   - 7.4 [Verification](#74-verification)
8. [Input Prompts & Usage Patterns](#8-input-prompts--usage-patterns)
9. [Troubleshooting](#9-troubleshooting)
10. [Repeatability Checklist](#10-repeatability-checklist)

---

## 1. Context

Claude Code requires cloud API calls for all model inference — there is no local Claude runtime. However, certain workloads are either:

- **Cost-sensitive** — bulk summarization, repetitive inference across many files
- **Privacy-sensitive** — internal code, unreleased IP, PII-adjacent data that should not leave the machine
- **Latency-tolerant but volume-heavy** — batch analysis where API cost accumulates fast

A local Ollama instance running **Qwen3-235B-A22B** (a 235B MoE model with 22B active parameters per forward pass) is already available. This model is competitive with frontier models on coding and reasoning tasks and runs acceptably on M3 MacBook Air and high-RAM Windows 11 workstations.

The question is: can Claude Code act as the intelligent orchestrator while delegating appropriate workloads to the local model?

---

## 2. Decision

**Expose Ollama as a set of MCP tools.** Claude Code connects to a local MCP server (Python, stdio transport) that wraps the Ollama REST API. Claude decides when to delegate to Qwen3 based on task type. No Ollama traffic ever leaves the machine.

### What Claude handles (cloud)
- High-stakes reasoning and planning
- Cross-file architectural decisions
- Tool orchestration and sequencing
- Final output synthesis

### What Qwen3/Ollama handles (local)
- Bulk text/code summarization
- Sensitivity-flagged code analysis
- High-volume cheap inference (linting explanations, doc generation)
- Speculative drafts Claude then refines

### What was rejected and why

| Option | Rejected Because |
|--------|-----------------|
| Replace Claude with Qwen3 entirely | Loses Claude Code's orchestration, tool use, and reasoning quality |
| Use LangChain as top-level orchestrator | Adds complexity; Claude Code already provides the agentic loop |
| Call Ollama directly from Claude Code hooks | Hooks are fire-and-forget; can't return structured results to Claude |
| OpenAI-compatible proxy (LiteLLM) | Adds a network hop and a process; MCP is simpler and already supported |

---

## 3. Consequences

### Positive
- Sensitive code never leaves the machine for the Ollama leg
- Ollama calls are free after hardware cost; reduces API spend on bulk tasks
- Claude retains full orchestration authority — quality of decisions doesn't degrade
- MCP server is stateless and restartable with no data loss

### Negative / Risks
- Qwen3 output quality is lower than Claude on complex reasoning — Claude must validate critical Qwen3 outputs
- Ollama must be running before Claude Code sessions start (no auto-launch)
- M3 MacBook Air RAM (16–24 GB) limits Qwen3-235B throughput; expect ~3–8 tok/s
- Windows: Ollama service must be configured to survive reboots

### Neutral
- The MCP server adds a Python process (~30 MB RAM) that stays resident during Claude Code sessions
- Tool schemas are defined once in the MCP server; no changes needed in Claude Code config when tools evolve

---

## 4. Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  Developer Machine                       │
│                                                         │
│  ┌─────────────────────┐    stdio    ┌───────────────┐  │
│  │    Claude Code CLI  │◄──────────►│  MCP Server   │  │
│  │   (orchestrator)    │            │  (Python)     │  │
│  └────────┬────────────┘            └───────┬───────┘  │
│           │                                 │           │
│    ┌──────▼──────┐               ┌──────────▼────────┐  │
│    │  Local FS   │               │  Ollama REST API  │  │
│    │  Git / Bash │               │  localhost:11434  │  │
│    │  MCP servers│               └──────────┬────────┘  │
│    └─────────────┘                          │           │
│                                   ┌─────────▼─────────┐ │
│                                   │ Qwen3-235B-A22B   │ │
│                                   │ (local weights)   │ │
│                                   └───────────────────┘ │
│                                                         │
└─────────────────────────────────────────────────────────┘
         │
         │ HTTPS (model inference only)
         ▼
  api.anthropic.com
```

**Data flow for a delegated task:**
1. User prompt → Claude Code
2. Claude decides task is bulk/sensitive → emits `ollama_*` tool call
3. MCP server receives call via stdio, forwards to `localhost:11434`
4. Qwen3 generates response — stays on machine
5. MCP server returns result to Claude via stdio
6. Claude synthesizes final answer → user

---

## 5. Prerequisites

### All Platforms

| Requirement | Min Version | Check Command |
|-------------|-------------|---------------|
| Python | 3.11+ | `python --version` |
| pip | 23+ | `pip --version` |
| Ollama | 0.3+ | `ollama --version` |
| Claude Code CLI | latest | `claude --version` |
| Qwen3-235B-A22B pulled | — | `ollama list` |

### macOS (Apple M3)

```bash
# Install Homebrew if needed
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Ollama
brew install ollama

# Install Python 3.11+ (if not present)
brew install python@3.11

# Install Claude Code CLI
npm install -g @anthropic-ai/claude-code
```

### Windows 11 Pro

```powershell
# Install Ollama (download installer from ollama.com or use winget)
winget install Ollama.Ollama

# Install Python 3.11+ from python.org or winget
winget install Python.Python.3.11

# Install Claude Code CLI (requires Node.js 18+)
winget install OpenJS.NodeJS.LTS
npm install -g @anthropic-ai/claude-code
```

> **Windows Note:** After installing Ollama, it registers as a background service.  
> Verify it auto-starts: `Get-Service -Name "Ollama" | Select-Object Status, StartType`

---

## 6. File Structure

```
hybrid-agent/
├── ADR-001-claude-ollama-hybrid.md     ← this file
├── mcp_ollama_server.py                ← MCP server (the bridge)
├── requirements.txt                    ← Python dependencies
├── .env.example                        ← environment variable template
└── prompts/
    ├── summarize.md                    ← reusable summarization prompt
    ├── analyze_code.md                 ← code analysis prompt
    └── bulk_infer.md                   ← general inference prompt
```

Place this folder anywhere on your machine. The path will be referenced in Claude Code's MCP config.

---

## 7. Implementation

### 7.1 Ollama Setup

**Pull the model (both platforms — identical command):**

```bash
ollama pull qwen3:235b-a22b
```

> This downloads ~140 GB. Run once; model persists across reboots.  
> On M3 MacBook Air with 24 GB RAM, Ollama will offload layers to CPU — expect mixed GPU/CPU inference.  
> On Windows with a discrete GPU (16+ GB VRAM), performance will be significantly higher.

**Verify Ollama is responding:**

```bash
curl http://localhost:11434/api/tags
# Should return JSON listing qwen3:235b-a22b
```

**Windows PowerShell equivalent:**

```powershell
Invoke-RestMethod http://localhost:11434/api/tags | ConvertTo-Json
```

---

### 7.2 MCP Server

Create `hybrid-agent/mcp_ollama_server.py`:

```python
"""
MCP server that exposes Ollama/Qwen3 as tools for Claude Code.
Transport: stdio (Claude Code spawns this process directly).
Platform: macOS / Windows 11 (no platform-specific code required).
"""

import json
import sys
import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

OLLAMA_BASE = "http://localhost:11434"
DEFAULT_MODEL = "qwen3:235b-a22b"
# Increase for longer documents; Qwen3 supports 32k–128k context
DEFAULT_CONTEXT = 8192

app = Server("ollama-bridge")


def _chat(system: str, user: str, model: str = DEFAULT_MODEL, num_ctx: int = DEFAULT_CONTEXT) -> str:
    """Single-turn chat against the local Ollama instance."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {"num_ctx": num_ctx},
    }
    with httpx.Client(timeout=300) as client:
        resp = client.post(f"{OLLAMA_BASE}/api/chat", json=payload)
        resp.raise_for_status()
        return resp.json()["message"]["content"]


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="ollama_summarize",
            description=(
                "Summarize a large block of text or code using the local Qwen3 model. "
                "Use this for bulk summarization tasks where content is too long for efficient "
                "cloud processing, or when the content is sensitive and must not leave the machine."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The text or code to summarize.",
                    },
                    "instructions": {
                        "type": "string",
                        "description": "Specific summarization instructions (e.g. 'focus on API surface', 'extract TODOs').",
                        "default": "Provide a concise, accurate summary.",
                    },
                    "max_words": {
                        "type": "integer",
                        "description": "Approximate target length in words.",
                        "default": 200,
                    },
                },
                "required": ["content"],
            },
        ),
        Tool(
            name="ollama_analyze_code",
            description=(
                "Analyze source code locally using Qwen3. Suitable for sensitive or proprietary code "
                "that should not be sent to external APIs. Returns a structured analysis."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "The source code to analyze.",
                    },
                    "language": {
                        "type": "string",
                        "description": "Programming language (e.g. python, typescript, go).",
                    },
                    "focus": {
                        "type": "string",
                        "description": "What to focus on: 'bugs', 'security', 'performance', 'style', or 'all'.",
                        "default": "all",
                    },
                },
                "required": ["code", "language"],
            },
        ),
        Tool(
            name="ollama_infer",
            description=(
                "Run a general-purpose prompt against the local Qwen3 model. "
                "Use for high-volume, cost-sensitive, or privacy-sensitive inference where "
                "Claude's full reasoning capability is not required."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "The user-facing prompt.",
                    },
                    "system": {
                        "type": "string",
                        "description": "Optional system prompt to frame Qwen3's behavior.",
                        "default": "You are a helpful, precise assistant.",
                    },
                    "num_ctx": {
                        "type": "integer",
                        "description": "Context window size in tokens (default 8192, max ~32768).",
                        "default": 8192,
                    },
                },
                "required": ["prompt"],
            },
        ),
        Tool(
            name="ollama_health",
            description="Check whether the local Ollama server is reachable and Qwen3 is loaded.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "ollama_health":
            with httpx.Client(timeout=10) as client:
                resp = client.get(f"{OLLAMA_BASE}/api/tags")
                models = [m["name"] for m in resp.json().get("models", [])]
            available = DEFAULT_MODEL in models or any(DEFAULT_MODEL in m for m in models)
            status = "healthy" if available else "Ollama running but Qwen3 not found"
            return [TextContent(type="text", text=json.dumps({"status": status, "models": models}))]

        if name == "ollama_summarize":
            content = arguments["content"]
            instructions = arguments.get("instructions", "Provide a concise, accurate summary.")
            max_words = arguments.get("max_words", 200)
            system = (
                f"You are a precise summarizer. {instructions} "
                f"Target length: approximately {max_words} words. "
                "Return only the summary — no preamble, no meta-commentary."
            )
            result = _chat(system, content)
            return [TextContent(type="text", text=result)]

        if name == "ollama_analyze_code":
            code = arguments["code"]
            language = arguments["language"]
            focus = arguments.get("focus", "all")
            focus_map = {
                "bugs": "Identify logic errors, off-by-one errors, null/undefined risks, and incorrect assumptions.",
                "security": "Identify injection risks, hardcoded secrets, insecure defaults, and authentication flaws.",
                "performance": "Identify algorithmic inefficiencies, redundant operations, and memory issues.",
                "style": "Identify naming inconsistencies, dead code, and readability issues.",
                "all": "Provide a comprehensive analysis covering bugs, security, performance, and style.",
            }
            focus_instruction = focus_map.get(focus, focus_map["all"])
            system = (
                f"You are an expert {language} code reviewer. {focus_instruction} "
                "Format your response as:\n"
                "## Summary\n[1-2 sentence overview]\n\n"
                "## Findings\n[numbered list, each with severity: CRITICAL/HIGH/MEDIUM/LOW]\n\n"
                "## Recommendations\n[actionable fixes]"
            )
            result = _chat(system, f"```{language}\n{code}\n```")
            return [TextContent(type="text", text=result)]

        if name == "ollama_infer":
            prompt = arguments["prompt"]
            system = arguments.get("system", "You are a helpful, precise assistant.")
            num_ctx = arguments.get("num_ctx", DEFAULT_CONTEXT)
            result = _chat(system, prompt, num_ctx=num_ctx)
            return [TextContent(type="text", text=result)]

        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except httpx.ConnectError:
        return [TextContent(type="text", text="ERROR: Cannot connect to Ollama at localhost:11434. Is Ollama running?")]
    except Exception as e:
        return [TextContent(type="text", text=f"ERROR: {type(e).__name__}: {e}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

Create `hybrid-agent/requirements.txt`:

```
mcp>=1.0.0
httpx>=0.27.0
```

**Install dependencies:**

```bash
# macOS / Linux
cd hybrid-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

```powershell
# Windows
cd hybrid-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

---

### 7.3 Claude Code Configuration

Claude Code reads MCP server config from `.claude/settings.json` (project-level) or the global user settings.

**Option A — Project-level** (recommended; checked into repo):

Create `.claude/settings.json` in `hybrid-agent/`:

```json
{
  "mcpServers": {
    "ollama-bridge": {
      "command": "python",
      "args": ["mcp_ollama_server.py"],
      "cwd": "${workspaceFolder}",
      "env": {}
    }
  }
}
```

> **macOS note:** If `python` resolves to Python 2, use `"python3"` as the command,  
> or use the full venv path: `".venv/bin/python"`.

**Option B — Global user settings** (available in all projects):

- **macOS:** `~/.claude/settings.json`
- **Windows:** `%USERPROFILE%\.claude\settings.json`

```json
{
  "mcpServers": {
    "ollama-bridge": {
      "command": "python",
      "args": ["C:/Projects/hybrid-agent/mcp_ollama_server.py"],
      "env": {}
    }
  }
}
```

> Use forward slashes in JSON paths on Windows — both PowerShell and Python handle them correctly.

**macOS with venv (explicit path):**

```json
{
  "mcpServers": {
    "ollama-bridge": {
      "command": "/Users/YOU/Projects/hybrid-agent/.venv/bin/python",
      "args": ["/Users/YOU/Projects/hybrid-agent/mcp_ollama_server.py"],
      "env": {}
    }
  }
}
```

---

### 7.4 Verification

**Step 1 — Test MCP server standalone:**

```bash
# macOS
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | \
  python3 mcp_ollama_server.py

# Windows PowerShell
'{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | python mcp_ollama_server.py
```

Expected: JSON response listing `ollama_summarize`, `ollama_analyze_code`, `ollama_infer`, `ollama_health`.

**Step 2 — Verify from inside Claude Code:**

Start a Claude Code session in the `hybrid-agent/` directory:

```bash
claude
```

Then type:

```
/mcp
```

You should see `ollama-bridge` listed as a connected server with 4 tools.

**Step 3 — Health check prompt:**

```
Use the ollama_health tool and tell me the result.
```

Expected response: Ollama is healthy, Qwen3-235B-A22B is listed.

---

## 8. Input Prompts & Usage Patterns

These prompts are designed to trigger Claude to delegate to the appropriate tool. They can be used verbatim or adapted.

---

### 8.1 Bulk Summarization

**Use when:** You have many files, logs, or documents to process cheaply.

```
I need summaries of all the markdown files in ./docs/. 
For each file, use the ollama_summarize tool — this content is internal 
and should stay local. Focus each summary on: key decisions, open questions, 
and action items. Limit each to 150 words.
```

```
Summarize the following error log locally using ollama_summarize. 
Extract: error types, frequency, first/last occurrence, and affected components.

[paste log here]
```

---

### 8.2 Sensitive / Private Code Analysis

**Use when:** Code contains business logic, credentials context, or unreleased IP.

```
Analyze the following proprietary code using ollama_analyze_code. 
It must not leave this machine. Language is TypeScript. Focus on security issues only.

[paste code here]
```

```
Run a full code review on src/auth/tokenService.ts using ollama_analyze_code 
with focus=security. Read the file first, then pass the content to the tool.
```

```
I need you to review all files in ./src/billing/ for bugs. 
This is sensitive financial logic — use ollama_analyze_code for each file 
so the code stays local. Compile the findings into a single report.
```

---

### 8.3 High-Volume Cheap Inference

**Use when:** You need many similar inferences and API cost is a concern.

```
For each function in the attached file, use ollama_infer to generate 
a one-sentence JSDoc description. Do this locally — there are 40+ functions 
and I want to keep API usage low.
```

```
Use ollama_infer to generate commit message suggestions for the following diff. 
Give me 3 options (conventional commits format). Keep it local.

[paste git diff here]
```

```
I have 200 customer support tickets in tickets.json. 
Use ollama_infer to classify each one as: bug / feature-request / billing / other.
Process them locally in batches. Return a CSV with ticket_id, category, confidence.
```

---

### 8.4 Hybrid Orchestration (Claude reasons, Qwen3 does bulk work)

**Use when:** You want Claude's judgment on what to delegate.

```
Review the entire ./src directory for code quality issues. 
Use ollama_analyze_code for the initial pass on each file to keep costs low. 
After you have all the raw findings, synthesize them yourself and identify 
the top 5 issues that need immediate attention.
```

```
I need a technical spec for refactoring the authentication module. 
First use ollama_summarize on each file in ./src/auth/ to understand the current state. 
Then use your own reasoning to design the refactoring plan — don't delegate that part.
```

---

### 8.5 Explicitly Routing to Local vs Cloud

You can tell Claude your routing preference explicitly:

```
For this task, treat ollama_infer as your default inference engine 
and only use your own reasoning when the task requires multi-step planning 
or cross-file synthesis. I want to minimize API usage today.
```

```
Everything in the ./private/ directory is confidential. 
For any task involving those files, always use the ollama_* tools 
so content stays local. For everything else, use your judgment.
```

---

## 9. Troubleshooting

### Ollama not reachable

```bash
# Check Ollama is running
curl http://localhost:11434/api/tags

# macOS — start manually if brew service failed
ollama serve

# Windows — check service status
Get-Service -Name "*ollama*"
Start-Service -Name "Ollama"
```

### MCP server not appearing in `/mcp`

1. Confirm `python` (or `python3`) resolves correctly in the shell Claude Code uses
2. Check the `cwd` path in settings.json points to the folder containing `mcp_ollama_server.py`
3. Run the server manually and look for import errors:
   ```bash
   python mcp_ollama_server.py
   # Should block silently waiting for stdio input — that's correct
   # Ctrl+C to exit
   ```
4. Verify the `mcp` package is installed in the same Python env:
   ```bash
   python -c "import mcp; print(mcp.__version__)"
   ```

### Slow responses on M3 MacBook Air

- Qwen3-235B-A22B with 16 GB RAM will be slow (~1–3 tok/s); 24 GB is more usable (~3–6 tok/s)
- Consider using `qwen3:30b` or `qwen3:32b` as a faster local alternative for less complex tasks
- Set `"num_ctx": 4096` in your prompts to reduce memory pressure

### Windows: PowerShell execution policy blocking venv activation

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

---

## 10. Repeatability Checklist

Run through this list on each new machine setup:

- [ ] Ollama installed and `ollama serve` (or service) is running
- [ ] `ollama pull qwen3:235b-a22b` completed
- [ ] `curl http://localhost:11434/api/tags` returns the model
- [ ] Python 3.11+ available (`python --version` or `python3 --version`)
- [ ] `hybrid-agent/` directory created with both files
- [ ] `.venv` created and `pip install -r requirements.txt` succeeded
- [ ] `python mcp_ollama_server.py` starts without import errors
- [ ] `.claude/settings.json` created with correct `command` and `args` paths
- [ ] Claude Code session started in `hybrid-agent/`
- [ ] `/mcp` shows `ollama-bridge` as connected
- [ ] `Use the ollama_health tool` returns healthy status
- [ ] Test summarization prompt returns a response from Qwen3

---

*This document is self-contained. Repeat from Section 5 on any new machine.*
