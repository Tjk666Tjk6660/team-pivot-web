"""EC Gateway LLM Backend.

Calls the local EC Gateway's OpenAI-compatible API (/v1/chat/completions)
to execute LLM steps in pipelines.

Connection info resolution priority:
  1. ENCLAWS_GATEWAY_URL + ENCLAWS_GATEWAY_TOKEN env vars
     (standard path after EC hashSTACS-Global/EnClaws#29)
  2. Default URL + token read from EC's SQLite database
     (temporary workaround, remove after #29 is merged)

TODO(EnClaws#29): Remove _read_token_from_db() and the DB fallback in
resolve_gateway_connection() once EC injects ENCLAWS_GATEWAY_TOKEN into
exec subprocess environment.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol


# ---------------------------------------------------------------------------
# LLM Backend Protocol
# ---------------------------------------------------------------------------

class LLMBackend(Protocol):
    def call(self, prompt: str, step_name: str, schema_path: str | None = None) -> dict:
        """Send prompt to LLM, return parsed JSON response matching schema."""
        ...


# ---------------------------------------------------------------------------
# Gateway connection resolution
# ---------------------------------------------------------------------------

def _read_token_from_db() -> str:
    """Temporary: read gateway auth token from EC's SQLite database.

    TODO(EnClaws#29): Delete this function once EC injects
    ENCLAWS_GATEWAY_TOKEN into exec subprocess environment.
    """
    import sqlite3

    state_dir = os.environ.get("ENCLAWS_STATE_DIR", "")
    candidates: list[Path] = []
    if state_dir:
        candidates.append(Path(state_dir) / "enclaws.db")
    candidates.append(Path.home() / ".enclaws" / "enclaws.db")
    candidates.append(Path.home() / ".openclaw" / "enclaws.db")

    for db_path in candidates:
        if not db_path.exists():
            continue
        try:
            conn = sqlite3.connect(str(db_path))
            row = conn.execute(
                "SELECT json_extract(auth, '$.token') FROM sys_gateway_config LIMIT 1"
            ).fetchone()
            conn.close()
            if row and row[0]:
                return str(row[0])
        except Exception:
            continue

    return ""


def resolve_gateway_connection() -> tuple[str, str]:
    """Resolve gateway URL and auth token.

    Returns:
        (gateway_url, token) tuple.

    Priority:
        1. ENCLAWS_GATEWAY_URL + ENCLAWS_GATEWAY_TOKEN env vars
        2. Default localhost URL + token from EC database
        3. Default localhost URL + empty token (will likely fail on auth)
    """
    url = os.environ.get("ENCLAWS_GATEWAY_URL", "")
    token = os.environ.get("ENCLAWS_GATEWAY_TOKEN", "")

    if not url:
        port = os.environ.get("ENCLAWS_GATEWAY_PORT", "18888")
        url = f"http://127.0.0.1:{port}"

    # TODO(EnClaws#29): Remove this fallback once EC injects the token.
    if not token:
        token = _read_token_from_db()

    return url, token


# ---------------------------------------------------------------------------
# Gateway LLM Backend
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict:
    """Extract JSON from LLM response text.

    Handles both raw JSON and markdown code-block wrapped JSON.
    """
    text = text.strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Cannot parse JSON from LLM response: {text[:300]}")


class GatewayLLMBackend:
    """LLM backend that calls the local EC Gateway's OpenAI-compatible API."""

    def __init__(self, url: str, token: str):
        self.url = url.rstrip("/")
        self.token = token
        # Session attribution headers (EC #29 — pass through if available)
        self.session_key = os.environ.get("ENCLAWS_SESSION_KEY", "")
        self.tenant_id = os.environ.get("ENCLAWS_TENANT_ID", "")

    def call(self, prompt: str, step_name: str, schema_path: str | None = None) -> dict:
        """Call the gateway's /v1/chat/completions endpoint.

        Args:
            prompt: The rendered prompt for the LLM step.
            step_name: Pipeline step name (for error messages).
            schema_path: Optional path to JSON schema (unused by gateway,
                         validation is done by the runner).

        Returns:
            {"output": {...}} dict with the LLM's parsed JSON response.
        """
        endpoint = f"{self.url}/v1/chat/completions"

        body = json.dumps({
            "model": "default",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a helpful assistant. "
                        "Always respond with valid JSON only, no markdown, no explanation."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "stream": False,
        }).encode("utf-8")

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        # Usage attribution (EC #29 — silently ignored if gateway doesn't support yet)
        if self.session_key:
            headers["x-enclaws-session-key"] = self.session_key
        if self.tenant_id:
            headers["x-enclaws-tenant-id"] = self.tenant_id

        req = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = ""
            if e.fp:
                try:
                    error_body = e.read().decode("utf-8", errors="replace")[:300]
                except Exception:
                    pass
            raise RuntimeError(
                f"LLM step '{step_name}': gateway returned HTTP {e.code}. {error_body}"
            ) from e
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"LLM step '{step_name}': cannot connect to gateway at {self.url}. "
                f"Is the EC gateway running? Error: {e.reason}"
            ) from e

        # Extract text content from OpenAI-format response
        choices = result.get("choices", [])
        if not choices:
            raise RuntimeError(
                f"LLM step '{step_name}': gateway returned empty choices. "
                f"Response: {json.dumps(result)[:300]}"
            )
        text = choices[0].get("message", {}).get("content", "")
        if not text:
            raise RuntimeError(
                f"LLM step '{step_name}': gateway returned empty content."
            )

        # Parse JSON from LLM response
        try:
            parsed = _extract_json(text)
        except ValueError as e:
            raise RuntimeError(
                f"LLM step '{step_name}': {e}"
            ) from e

        # Wrap in {"output": ...} if not already wrapped
        if "output" not in parsed:
            parsed = {"output": parsed}

        return parsed
