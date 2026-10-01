---
name: director-studio-ops
description: Use when starting, stopping, restarting, redeploying, checking logs, verifying, or troubleshooting the Director Studio service on this Linux host (systemd user service, port 8790, ComfyUI/LLM integration). Trigger on keywords like systemctl, service, start/stop backend, start/stop frontend, redeploy, journalctl, 8790, health check.
---

# Director Studio Ops (this host)

Director Studio runs as a **systemd user service** named `director-studio`. The backend (FastAPI/uvicorn) also serves the built frontend itself, so there is **no separate frontend service**. UI and API share port **8790**.

## Service commands

```bash
systemctl --user start director-studio
systemctl --user stop director-studio
systemctl --user restart director-studio
systemctl --user status director-studio --no-pager
journalctl --user -u director-studio -f          # live logs
```

- Unit file: `~/.config/systemd/user/director-studio.service`
- Enabled at boot; user lingering is already on (`loginctl show-user $USER -p Linger`).
- Unit runs: `backend/.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8790` with `WorkingDirectory=/home/steven/repos/Director-Studio/backend`, `Restart=on-failure`.
- The unit MUST set `Environment=PATH=/home/steven/repos/Director-Studio/backend/.venv/bin:/usr/local/bin:/usr/bin:/bin`. Without the venv on PATH, the backend cannot spawn `comfy-mcp` (see Troubleshooting).

## Verify after start

```bash
curl -s http://127.0.0.1:8790/api/health   # expect "ok":true, comfy_reachable, llm reachable
curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8790/   # 200 = UI served
```

- UI (LAN): http://192.168.66.68:8790 · API docs: `/docs`
- Health reports ComfyUI version info and LLM provider reachability.

## Configuration

- `backend/.env` (git-ignored, prefix `DS_`) is read by pydantic-settings at startup. Current setup:
  - `DS_HOST=0.0.0.0` (LAN-exposed, no auth — trusted network only)
  - `DS_LLM_PROVIDER=openai-compatible`, `DS_LLM_BASE_URL=http://192.168.66.99:8731/v1` (no API key required)
  - `DS_COMFY_BASE_URL=http://127.0.0.1:8188`
- After editing `.env`: `systemctl --user restart director-studio`.

## External dependencies (NOT managed by this unit)

- **ComfyUI**: host process at `:8188` (`/home/steven/repos/ComfyUI/main.py --listen 0.0.0.0`). Must be running for image/video jobs.
- **LLM provider**: remote OpenAI-compatible server at `192.168.66.99:8731`. Check with `curl http://192.168.66.99:8731/v1/models`.
- Backend spawns `comfy-mcp` (from `backend/.venv`) as a persistent subprocess for ComfyUI jobs; VRAM coordination with ComfyUI/LLM is pure HTTP.

## Redeploying code changes

```bash
# Backend: no build step; just restart
systemctl --user restart director-studio

# Frontend: must rebuild dist first (backend serves frontend/dist statically)
cd frontend && npm run build && systemctl --user restart director-studio
```

## Firewall

`ufw` is currently inactive; no port rules needed. If ufw gets enabled, allow 8790 for LAN access.

## Troubleshooting

- Service failing: `journalctl --user -u director-studio -n 50`.
- Port busy: `ss -tlnp | grep 8790`, stop the conflicting process or change `DS_PORT` in `backend/.env` and the unit's `--port`.
- ComfyUI unreachable in health check: confirm `:8188` is listening and `DS_COMFY_BASE_URL` is correct.
- Empty model picker: confirm the LLM `/v1/models` endpoint is reachable **from this host** (backend-side, not browser-side).
- `queue_actor_design failed: MCP tool upload_file failed: [Errno 2] No such file or directory` (or any MCP spawn ENOENT): the service is missing the venv on `PATH`. `_resolve_command` in `backend/app/integrations/comfy_mcp.py` resolves `sys.executable` with `.resolve()`, which follows the venv symlink chain to `/usr/bin`, so the "beside the running Python" fallback misses the venv's `bin`. Fix: keep the `Environment=PATH=...venv/bin...` line in the unit, then `systemctl --user daemon-reload && systemctl --user restart director-studio`. Verify: `journalctl --user -u director-studio -n 50` shows no spawn errors; smoke test with `ComfyMcpClient().call_tool("server_info", {})`.
- Do not run a second instance manually while the service is up — single writer on `data/`.
- H3 submit warning `dialogue line must appear exactly once (found N): '<full line>'`: the validator (`backend/app/core/h3/prompt.py`) requires each dialogue line to appear in the composed prompt exactly once per occurrence in `shot.dialogue`. A deterministic backstop `enforce_dialogue_occurrences_in_sections(sections, dialogue, exempt_text=global)` (same file) now auto-fixes this: it keeps the spoken copy in `detailed_description`, strips surplus mentions from other sections (deleting quoted spans), adds a spoken clause if missing, and never touches the GLOBAL DIRECTION. It runs in the writer (`service.py` `parse_and_validate`, so `write_prompt`/`rewrite_prompt` save a clean prompt) and as a submit healer (`projects.py` `submit_shot_endpoint`, and `json_production.py`). If you still see this error, the running service is STALE — it started before the fix landed. Confirm with `stat -c '%y' backend/app/core/h3/prompt.py` vs `systemctl --user show director-studio -p ActiveEnterTime`, then `systemctl --user restart director-studio`. To clean already-stored shots without re-running the LLM, PATCH each shot with the normalized sections: `fixed = enforce_dialogue_occurrences_in_sections(load_shot(pid,sid).prompt_sections, dialogue, exempt_text=effective_global_prompt(pid))` then `PATCH /api/shots/{sid}` `{"prompt_sections": fixed.model_dump()}`. Verify by mirroring the submit check: `compose_h3_prompt` + `validate_h3_prompt` with `audio_count=0 if source_audio_path else len(voice_refs)`, required Picture indices from the shot's refs.
