# Local Codex Bridge

The bridge is a development-only adapter. It is not part of the production
Azure request path and must never be exposed to the public internet.

Set `DECISIONFLOW_BRIDGE_TOKEN` and `CODEX_WORKSPACE_ROOT` before starting it:

```bash
uv run uvicorn local_bridge.bridge_server:app --host 127.0.0.1 --port 8787
```

The bridge accepts only allow-listed task types, uses `shell=False`, resolves
paths under the configured workspace, caps output, and never receives an
arbitrary command string from Azure.
