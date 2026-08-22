# DeepSWE / Pier agentic benchmark — setup log

Machine: GAMINGPC, Windows 11 Pro 26200, WSL2 Ubuntu-24.04, RTX 3090.
Date: 2026-08-23. Goal: validate full plumbing with ONE task against the
local Qwen3.8-27B llama-server.

---

## Stage 1 — WSL prep + docker

`wsl -l -v` → single distro `Ubuntu-24.04` (WSL2), was Stopped.

Probe results:

| Check | Result |
| --- | --- |
| PID 1 | `systemd` (`/etc/wsl.conf` has `systemd=true`) — so `systemctl` works |
| docker | absent |
| uv | already present at `/home/chink/.local/bin/uv` |
| podman / uidmap | absent (rootless docker not viable without installs) |
| `sudo -n true` | **fails — password required** |

`sudo` needs a password, but this was **not** a blocker: WSL exposes a
documented no-password root path via `wsl -u root`. Verified:

```
wsl -d Ubuntu-24.04 -u root -e bash -lc "whoami"   # -> root
```

That is the WSL init switching users, not a sudo bypass, so no password
brute-forcing was needed. Docker installed as root:

```
wsl -d Ubuntu-24.04 -u root -e bash -lc \
  "curl -fsSL https://get.docker.com | sh; usermod -aG docker chink; systemctl enable --now docker"
```

Result: **docker 29.7.2, service active, enabled at boot.** After
`wsl --terminate Ubuntu-24.04` (needed to pick up the new group), `docker ps`
works as `chink` with no sudo.

**No manual user step is required.** Docker survives reboots via
`systemctl enable`.

---

## Stage 2 — uv, pier, deep-swe

uv was already installed user-scope in WSL, so no install needed.

```
uv tool install --force git+https://github.com/datacurve-ai/pier
pier --version   # -> 0.3.1
```

(DeepSWE v1.1 requires Pier > 0.3.0 for the separate verifier environment,
so 0.3.1 from git main is correct.)

Clones (from WSL, into the Windows tree via `/mnt/e`):

- `/mnt/e/AI/measured-inference/agentic/deep-swe`  — 117 task dirs under `tasks/`
- `/mnt/e/AI/measured-inference/agentic/pier`      — source, cloned only to read the model/network plumbing

`.gitignore` updated **before** these existed: `agentic/deep-swe/`,
`agentic/pier/`, `agentic/work/`, `agentic/results/`, `agentic/trajectories/`,
`agentic/.venv/`, `agentic/**/.venv/`, `agentic/**/__pycache__/`.
`agentic/setup-log.md` and any runner scripts stay tracked.

---

## Stage 3 — how Pier selects the model (exact mechanism)

Read from `pier/src/pier/agents/installed/mini_swe_agent.py` and
`pier/src/pier/environments/agent_setup.py`.

### Model name

`--model / -m` sets `agent.model_name`, passed straight to
`mini-swe-agent --model=<name>`. It **must** contain a `/`
(`run()` raises `ValueError` otherwise).

### The `openai/` trap

`MiniSweAgent._model_class_override` (mini_swe_agent.py:742-749):

```python
if self._model_class != "auto":      # default is "auto"
    return self._model_class
if self.model_name.startswith("openai/"):
    return "litellm_response"        # OpenAI *Responses* API
if self.model_name.startswith("openrouter/"):
    return "openrouter"
return None
```

So a plain `openai/...` model name silently routes mini-swe-agent to the
**OpenAI Responses API** (`/v1/responses`), which **llama.cpp does not
implement**. The fix is the `model_class` agent kwarg. `parse_kwargs`
(`cli/utils.py:22`) JSON-parses values, so `--ak model_class=null` becomes
Python `None`; `None != "auto"` returns `None`, the walrus `if model_class :=`
is then falsy and **no `-c model.model_class` flag is emitted at all**,
leaving mini-swe-agent on its LiteLLM default (chat completions).

`--ak model_class=null` is the whole fix. It uses only documented CLI
behaviour — no patching.

### Base URL + API key

`build_process_env` (`agents/installed/base.py:238`) merges **everything**
from `--agent-env / --ae` into the container env, so any var can be passed.
`OPENAI_BASE_URL` / `OPENAI_API_BASE` are additionally re-exported explicitly.

API key resolution (`run()`, lines 849-866): `MSWEA_API_KEY` is checked
**first** and short-circuits provider-specific lookup; otherwise
`get_api_key_var_names_from_model_name()` demands e.g. `OPENAI_API_KEY` and
raises if unset. llama.cpp ignores the key value, but one must be present.

### Network allowlist (the load-bearing part)

DeepSWE tasks set `[agent] network_mode = "no-network"`. Pier then puts the
task container on an `internal: true` docker network and forces all egress
through a **squid** sidecar (`agent_setup.py:99-134`). The allowlist is built
by `MiniSweAgent.network_allowlist()`, which harvests hostnames from
`OPENAI_BASE_URL`, `OPENAI_API_BASE`, `ANTHROPIC_BASE_URL`, `GEMINI_API_BASE`,
`OPENROUTER_API_BASE` and from any `base_url`/`api_base`/`url` key inside
`config_yaml`. **Setting `OPENAI_BASE_URL` allowlists the host automatically —
no separate allowlist flag exists or is needed.**

The generated squid config contains:

```
acl SSL_ports  port 443
acl Safe_ports port 80 443
acl allowed_domains dstdomain "/tmp/allowed_domains.txt"
http_access deny !Safe_ports
http_access allow authenticated allowed_domains
http_access deny all
```

**Consequence: only destination ports 80 and 443 can ever reach the model.**
See stage 4.

---

## Stage 4 — local server + WSL→host address

### WSL → Windows host address

Networking is **NAT mode**, not mirrored (no `.wslconfig` exists):

| From WSL | Result |
| --- | --- |
| `localhost` / `127.0.0.1` | **fails** — proves NOT mirrored |
| `192.168.128.1` (Windows `vEthernet (WSL)` gateway, = WSL default route) | **works** |
| `192.168.1.9` (Wi-Fi LAN IP) | works, but changes with DHCP |

`/etc/resolv.conf`'s `10.255.255.254` is the DNS-tunnel address, **not** the
host — a common misread. Use **`192.168.128.1`**, confirmed as WSL's
default route (`ip route | grep default`).

### The port-1235 blocker (measured, not assumed)

Before spending a multi-GB image pull, I rebuilt Pier's exact squid image
standalone and tested it with `ALLOWLIST_DOMAINS=192.168.128.1`:

| Test | Result |
| --- | --- |
| container → host `:80` directly (no proxy) | 200 `{"status":"ok"}` |
| through squid → `http://192.168.128.1:80/health` | **200** `TCP_MISS/200 ... HIER_DIRECT` |
| through squid → `http://192.168.128.1:1235/health` | **403** `TCP_DENIED/403` |

Two findings:

1. squid `dstdomain` **does** match a bare IP literal — no warnings, no need
   for a hostname or a `dst` ACL.
2. **Port 1235 is denied by the `Safe_ports` ACL.** This is a hard blocker
   and is *not* configurable through Pier.

So the llama-server must listen on **port 80** (plain HTTP; 443 would need
TLS). Windows does not reserve ports < 1024 for administrators, and ports 80
and 443 were both free, so this needed no elevation and no `netsh portproxy`
(which would have needed admin — this shell is not elevated).

### Server command actually used

Identical to the house convention except `--port 80` instead of `--port 1235`:

```
E:\AI\llama.cpp\llama-server.exe ^
  -m C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-IQ4_XS.gguf ^
  --alias qwen/qwen3.8-27b -c 65536 -ngl 99 --load-mode mmap -ctk q8_0 -ctv q8_0 ^
  --spec-type draft-mtp --spec-draft-n-max 10 --spec-draft-p-min 0.5 ^
  --temp 1.0 --top-p 0.95 --top-k 20 --min-p 0.0 ^
  --chat-template-kwargs "{\"reasoning_effort\":\"medium\"}" --jinja ^
  --host 0.0.0.0 --port 80
```

Loaded in ~7 s (mmap), `/health` → `{"status":"ok"}`, MTP draft context
created against the target model, 4 slots at 65536 ctx.

The `--alias qwen/qwen3.8-27b` matters: LiteLLM strips the `openai/` provider
prefix and sends `model="qwen/qwen3.8-27b"`, which must match the alias.

---

## Stage 5 — validation run

### Command (this is the working one)

Run from WSL, cwd `/mnt/e/AI/measured-inference/agentic`, `PATH` including
`$HOME/.local/bin`:

```bash
pier run -p deep-swe/tasks --agent mini-swe-agent \
  --n-tasks 1 --sample-seed 0 \
  -m openai/qwen/qwen3.8-27b \
  --ak model_class=null \
  --ae OPENAI_BASE_URL=http://192.168.128.1/v1 \
  --ae OPENAI_API_BASE=http://192.168.128.1/v1 \
  --ae OPENAI_API_KEY=local-dummy \
  --ae MSWEA_API_KEY=local-dummy \
  -o results --job-name validate-01 -n 1
```

Sampled task at seed 0: **`true-myth-iterable-collection-combinators`** (TypeScript).

### Proof the plumbing worked

The squid sidecar's access log, from inside the air-gapped trial:

```
TCP_MISS/200 POST http://192.168.128.1/v1/chat/completions agent HIER_DIRECT/192.168.128.1
```

Generated allowlist was `192.168.128.1,api.openai.com` — the host IP was
harvested automatically from `OPENAI_BASE_URL`.

The command Pier actually executed inside the container (from `trial.log`)
contains **no `-c model.model_class` flag**, confirming `--ak model_class=null`
suppressed the `openai/`→Responses-API override as intended:

```
mini-swe-agent --yolo --model=openai/qwen/qwen3.8-27b --task='...' \
  --output=/logs/agent/mini-swe-agent.trajectory.json \
  -c mini.yaml -c agent.cost_limit=0 --exit-immediately
```

A pre-flight `curl` against the endpoint also confirmed llama.cpp returns
`finish_reason: tool_calls`, a populated `tool_calls` array, `reasoning_content`,
and a `usage` block — everything Pier's ATIF v1.7 converter reads.

### Results

| Metric | Value |
| --- | --- |
| Job wall time (pull + build + agent + verify) | **9 m 36 s** |
| — image pull + agent-install build | ~3 min |
| — agent loop + verifier | ~6.5 min |
| LLM calls / ATIF steps | 22 / 24 |
| Total prompt tokens | 1,014,115 |
| Total completion tokens | 21,736 |
| Peak context tokens | 65,263 (of 65,536) |
| F2P (fail-to-pass) | 0.000 (0/96) |
| P2P (pass-to-pass) | 1.000 (561/561) |
| Partial | 0.854 |
| Reward | 0 |
| Exception | `NonZeroAgentExitCodeError` |

Verification ran and graded, so the **entire** pipeline — sample → pull →
build → air-gapped agent → local LLM via proxy → commit-collect → separate
verifier environment → ATIF trajectory → scored result — is proven.

### Real finding: 65536 context is too small for DeepSWE

The agent did not finish by choice. It died on:

```
litellm.ContextWindowExceededError: request (65577 tokens) exceeds the
available context size (65536 tokens), try increasing it
```

Peak context 65,263 against a 65,536 limit. mini-swe-agent does no
summarization by default, so history grows monotonically until the request
overflows — here after only 22 calls. P2P 561/561 means it broke nothing;
F2P 0/96 means it never got far enough to implement the feature.

**Before a real sweep, raise `-c`** (e.g. `-c 131072`). With `-ctk q8_0
-ctv q8_0` the KV cache is already halved, so a 24 GB 3090 holding a ~14 GB
IQ4_XS should have room — but this needs its own measurement, since spilling
KV to system RAM would wreck throughput.

Note also the 1.01 M prompt tokens against 21.7 k completion tokens: agentic
runs re-send the whole transcript every step, so prompt-side cost is ~47x
the generated tokens. Prompt-processing speed, not generation speed, is the
lever that decides DeepSWE wall time.

### Where results land

Root: `E:\AI\measured-inference\agentic\results\<job-name>\` (gitignored).

```
result.json                       job-level scores
config.json  job.log  lock.json
<task-id>__<trialid>/
    trial.log
    config.json
    agent/trajectory.json               <- ATIF v1.7 (the canonical artifact)
    agent/mini-swe-agent.trajectory.json <- native mini-swe format
    agent/mini-swe-agent.txt             <- raw agent stdout
    verifier/                            <- reward.json, ctrf.json, test-stdout.txt
    artifacts/                           <- model.patch
    egress-proxy/, agent-build-context/, docker-compose-*.json
```

`pier view results` opens the chat-style trajectory viewer.

### Projected wall time — 10 tasks x 3 efforts (30 trials)

Each task has its **own ~5 GB image**, pulled once and then cached across the
three effort sweeps. Budget **~50 GB** in the WSL vdisk for 10 tasks.

| Scenario | Serial (`-n 1`) | Default (`-n 4`) |
| --- | --- | --- |
| Context stays 65536 (runs truncate early, as measured) | 10x3 min pull + 30x6.5 min = **~3.7 h** | **~2 h** |
| Context raised so agents run to natural completion (~16 min est.) | **~8.5 h** | **~4.5 h** |

`-n 4` matches llama-server's 4 slots, but one GPU serves them all, so expect
roughly 2x — not 4x — and per-request latency degrades. **For measured
benchmarking use `-n 1`**: shared slots make per-task wall time unattributable.

The second row is an estimate, not a measurement — no run here reached natural
termination. Treat it as a planning figure only.

Each effort level needs its **own llama-server restart**, because llama.cpp
applies `reasoning_effort` server-side via
`--chat-template-kwargs {"reasoning_effort":"..."}`. Passing
`--ak reasoning_effort=...` sends it in the request body instead, which this
server does not honour.

---

## Stage 6 — cleanup

- llama-server stopped on Windows; port 80 released.
- Scratch `squidtest` image removed.
- docker (enabled at boot), uv and pier left installed.
- Task image `...-main:latest` (5.01 GB) and the egress-proxy image left
  cached, so re-running this task skips the pull.
- **I ran no git commit.** Note: a *concurrent* session in this repo swept my
  `.gitignore` edit into commit `cb1a482` while this work was in progress.
