"""Per-model enrollment: fingerprint response format, persist composed adapter profiles.

Profiles are keyed by provider::model and list shared normalizer step ids — not
one Python module per model. Soft gate: missing profile → DEFAULT_STEPS.

Offline:
  python -m enrollment enroll openrouter inclusionai/ling-3.0-flash:free
  python -m enrollment list
  python -m enrollment check

Staging tip: set ROUTER_PROFILES_FILE=./model_profiles.staging.json
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore

BATTERY_VERSION = 1
DEFAULT_STEPS = ["promote_reasoning", "strip_template_junk"]

PROFILES_FILE = Path(os.environ.get("ROUTER_PROFILES_FILE", "./model_profiles.json"))

# Same leading junk as router.py — keep in sync when adding tokens.
# Literals used for incomplete-prefix hold across SSE deltas (streaming).
_JUNK_TOKEN_LITERALS = (
    "</role>",
    "<|im_end|>",
    "<|im_start|>",
    "<|endoftext|>",
    "</s>",
    "<end_of_turn>",
    "<eos>",
    "<arg_value>",
    "</arg_value>",
    "<arg_key>",
    "</arg_key>",
    '">',
    "》《",  # occasional fullwidth debris seen in contaminated replies
)

_LEADING_TEMPLATE_JUNK = re.compile(
    r"^(?:\s*(?:"
    r"</role>|<\|im_end\|>|<\|im_start\|>\s*assistant\s*|"
    r"<\|endoftext\|>|"
    r"</s>|<end_of_turn>|<eos>|"
    r"</?arg_value>|</?arg_key>|"
    r'">|》《'
    r"))+",
    re.IGNORECASE,
)


def is_incomplete_junk_prefix(text: str) -> bool:
    """True if `text` may still be a split leading junk token (hold in SSE)."""
    if not text:
        return False
    t = text.lstrip()
    if not t:
        return True
    low = t.lower()
    for tok in _JUNK_TOKEN_LITERALS:
        tl = tok.lower()
        if tl.startswith(low) and low != tl:
            return True
    # <|im_start|> optionally followed by whitespace + assistant (no payload yet)
    if low.startswith("<|im_start|>"):
        rest = t[len("<|im_start|>"):]
        if re.match(r"^\s*(assistant)?\s*$", rest, re.I):
            return True
    return False


class LeadingJunkStreamFilter:
    """Accumulate streamed content and emit only the sanitized suffix.

    Leading template junk may arrive split across SSE deltas (`</` + `role>…`).
    Per-delta strip misses that; joining then stripping then emitting the new
    suffix does not.
    """

    def __init__(self):
        self._raw = ""
        self._emitted = 0

    def push(self, piece: str) -> str:
        if not piece:
            return ""
        self._raw += piece
        cleaned = sanitize_content_text(self._raw)
        if self._emitted == 0 and is_incomplete_junk_prefix(cleaned):
            return ""
        out = cleaned[self._emitted:]
        self._emitted = len(cleaned)
        return out

    def flush(self) -> str:
        cleaned = sanitize_content_text(self._raw)
        if self._emitted == 0 and is_incomplete_junk_prefix(cleaned):
            self._raw = ""
            self._emitted = 0
            return ""
        out = cleaned[self._emitted:]
        self._raw = cleaned
        self._emitted = len(cleaned)
        return out

_TOOL_XML_RE = re.compile(
    r"<(?:arg_value|arg_key|tool_call|function_call|parameter|invoke)\b|"
    r"<\|tool_call\|>|"
    r"<｜DSML｜",
    re.IGNORECASE,
)

_TOOL_PROBE = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get the current weather for a city",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
}]

_warned_unenrolled: set[tuple[str, str]] = set()
_profiles_cache: dict | None = None


def profile_key(provider: str, model: str) -> str:
    return f"{provider}::{model}"


def load_profiles(path: Path | None = None) -> dict:
    global _profiles_cache
    p = path or PROFILES_FILE
    if path is None and _profiles_cache is not None:
        return _profiles_cache
    if not p.exists():
        doc: dict = {}
    else:
        try:
            doc = json.loads(p.read_text())
            if not isinstance(doc, dict):
                doc = {}
        except Exception:
            doc = {}
    if path is None:
        _profiles_cache = doc
    return doc


def reload_profiles() -> dict:
    global _profiles_cache
    _profiles_cache = None
    return load_profiles()


def save_profile(provider: str, model: str, entry: dict, path: Path | None = None) -> Path:
    global _profiles_cache
    p = path or PROFILES_FILE
    doc = load_profiles(p)
    doc[profile_key(provider, model)] = entry
    p.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    if path is None:
        _profiles_cache = doc
    return p


def is_enrolled(provider: str, model: str) -> bool:
    return profile_key(provider, model) in load_profiles()


def detect_leading_junk(text: str) -> list[str]:
    if not text:
        return []
    found: list[str] = []
    if re.match(r"^\s*</role>", text, re.I):
        found.append("role_close")
    if re.match(r"^\s*<arg_value>", text, re.I):
        found.append("arg_value")
    if re.match(r"^\s*<arg_key>", text, re.I):
        found.append("arg_key")
    if re.match(r"^\s*<\|im_(end|start)\|>", text, re.I):
        found.append("im_token")
    if re.match(r'^\s*">', text):
        found.append("quote_gt")
    if re.match(r"^\s*<\|endoftext\|>", text, re.I):
        found.append("endoftext")
    if re.match(r"^\s*》《", text):
        found.append("fullwidth_junk")
    return found


def compose_steps(traits: dict) -> list[str]:
    """Table-driven: traits → shared step ids. Always include strip for safety."""
    steps = ["strip_template_junk"]
    if traits.get("reasoning_field"):
        steps.insert(0, "promote_reasoning")
    else:
        # still promote if content empty — cheap and matches default Hermes needs
        steps.insert(0, "promote_reasoning")
    if traits.get("tool_shape") == "content_xml":
        steps.append("strip_dsml_tool_xml")  # no-op stub until a real parser lands
    if traits.get("supports_tools") and traits.get("tool_shape") == "openai_native":
        steps.append("passthrough_tools")
    # de-dupe preserving order
    out, seen = [], set()
    for s in steps:
        if s not in seen:
            out.append(s)
            seen.add(s)
    return out


def resolve_steps(provider: str, model: str, *, warn: bool = True) -> list[str]:
    """Return enrolled steps or DEFAULT_STEPS. Soft gate: never raises."""
    entry = load_profiles().get(profile_key(provider, model))
    if entry and isinstance(entry.get("steps"), list) and entry["steps"]:
        return list(entry["steps"])
    if warn:
        k = (provider, model)
        if k not in _warned_unenrolled:
            _warned_unenrolled.add(k)
            print(
                f"[enrollment] unenrolled model {provider}/{model} — using default adapter",
                file=sys.stderr,
            )
    return list(DEFAULT_STEPS)


def _content_is_empty(content) -> bool:
    if content is None:
        return True
    if isinstance(content, str):
        return not content.strip()
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict):
                text = part.get("text") or part.get("content")
                if isinstance(text, str) and text.strip():
                    return False
            elif isinstance(part, str) and part.strip():
                return False
        return True
    return True


def _reasoning_text(msg: dict) -> str:
    for field in ("reasoning", "reasoning_content", "thinking"):
        r = msg.get(field)
        if isinstance(r, str) and r.strip():
            return r
    rd = msg.get("reasoning_details")
    if isinstance(rd, list):
        parts = [
            b["text"] for b in rd
            if isinstance(b, dict) and isinstance(b.get("text"), str) and b["text"].strip()
        ]
        if parts:
            return "\n".join(parts)
    return ""


def sanitize_content_text(text: str) -> str:
    if not text:
        return text
    return _LEADING_TEMPLATE_JUNK.sub("", text)


def _sanitize_message_content(msg: dict) -> None:
    content = msg.get("content")
    if isinstance(content, str):
        cleaned = sanitize_content_text(content)
        if cleaned != content:
            msg["content"] = cleaned
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                part["text"] = sanitize_content_text(part["text"])


def _step_promote_reasoning(msg: dict, *, promote: bool) -> None:
    if promote and _content_is_empty(msg.get("content")):
        r = _reasoning_text(msg)
        if r:
            msg["content"] = r


def _step_strip_template_junk(msg: dict) -> None:
    _sanitize_message_content(msg)


def _step_strip_dsml_tool_xml(msg: dict) -> None:
    # ponytail: ceiling = leading-only strip already covers <arg_value>; mid-content
    # DSML→tool_calls upgrade when battery starts seeing it as visible replies.
    _sanitize_message_content(msg)


def _step_passthrough_tools(msg: dict) -> None:
    return  # marker step: apply_steps skips content rewrite when tool_calls set


def apply_steps(msg: dict, steps: list[str] | None, *, promote_reasoning: bool = True) -> None:
    """Normalize an assistant/delta message in-place using composed steps."""
    steps = list(steps or DEFAULT_STEPS)
    if msg.get("tool_calls") and "passthrough_tools" in steps:
        # still drop reasoning fields so Hermes doesn't store CoT;
        # still strip leading junk — models often emit </role>/<arg_value>
        # as content alongside native tool_calls (live Hermes + ling).
        for k in ("reasoning_content", "reasoning", "thinking", "think", "reasoning_details"):
            msg.pop(k, None)
        if "strip_template_junk" in steps or "strip_dsml_tool_xml" in steps:
            _step_strip_template_junk(msg)
        return

    if "promote_reasoning" in steps:
        _step_promote_reasoning(msg, promote=promote_reasoning)

    for k in ("reasoning_content", "reasoning", "thinking", "think", "reasoning_details"):
        msg.pop(k, None)
    if isinstance(msg.get("content"), list):
        msg["content"] = [
            b for b in msg["content"]
            if not (isinstance(b, dict) and b.get("type") in ("thinking", "think"))
        ]

    if "strip_template_junk" in steps or "strip_dsml_tool_xml" in steps:
        _step_strip_template_junk(msg)


# ── Battery ───────────────────────────────────────────────────────────────────

def _chat(url: str, headers: dict, body: dict, timeout: float = 60) -> tuple[int, dict | None, str]:
    if requests is None:
        return 0, None, "requests not installed"
    try:
        r = requests.post(url, headers=headers, json=body, timeout=timeout)
    except Exception as e:
        return 0, None, str(e)
    try:
        data = r.json()
    except Exception:
        data = None
    return r.status_code, data if isinstance(data, dict) else None, (r.text or "")[:300]


def run_battery(base_url: str, model: str, key: str, *, extra_headers: dict | None = None) -> dict:
    """Fingerprint one model. Returns traits + steps + snippets (or error)."""
    url = base_url.rstrip("/") + "/chat/completions"
    hdrs = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        **(extra_headers or {}),
    }
    traits: dict = {
        "supports_tools": False,
        "tool_shape": "none",
        "reasoning_field": False,
        "leading_junk": [],
    }
    snippets: dict = {}

    # 1) Plain reply
    code, data, err = _chat(url, hdrs, {
        "model": model,
        "max_tokens": 32,
        "messages": [{"role": "user", "content": "Reply with exactly: pong"}],
    })
    if code != 200 or not data:
        return {"ok": False, "error": f"plain reply HTTP {code}: {err}", "traits": traits}
    msg = ((data.get("choices") or [{}])[0].get("message") or {})
    content = msg.get("content") if isinstance(msg.get("content"), str) else ""
    snippets["plain"] = (content or "")[:120]
    traits["leading_junk"] = detect_leading_junk(content or "")
    if _reasoning_text(msg):
        traits["reasoning_field"] = True

    # 2) Reasoning budget
    code, data, err = _chat(url, hdrs, {
        "model": model,
        "max_tokens": 24,
        "messages": [{"role": "user", "content": "Reply with just the word: ready"}],
    })
    if code == 200 and data:
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        content = (msg.get("content") or "").strip() if isinstance(msg.get("content"), str) else ""
        if _reasoning_text(msg):
            traits["reasoning_field"] = True
        elif not content and choice.get("finish_reason") == "length":
            traits["reasoning_field"] = True
        snippets["reasoning"] = (content or _reasoning_text(msg) or "")[:120]

    # 3) Forced tool
    got = False
    for choice in ("required", "auto"):
        code, data, err = _chat(url, hdrs, {
            "model": model,
            "max_tokens": 64,
            "tools": _TOOL_PROBE,
            "tool_choice": choice,
            "messages": [{"role": "user",
                          "content": "What is the weather in Paris? Use the get_weather tool."}],
        })
        if code != 200 or not data:
            continue
        got = True
        msg = ((data.get("choices") or [{}])[0].get("message") or {})
        content = msg.get("content") if isinstance(msg.get("content"), str) else ""
        snippets["tool"] = (content or json.dumps(msg.get("tool_calls")) or "")[:160]
        if msg.get("tool_calls"):
            traits["supports_tools"] = True
            traits["tool_shape"] = "openai_native"
            break
        if content and _TOOL_XML_RE.search(content):
            traits["supports_tools"] = True
            traits["tool_shape"] = "content_xml"
            break
    if got and traits["tool_shape"] == "none":
        traits["supports_tools"] = False

    steps = compose_steps(traits)
    return {
        "ok": True,
        "battery_version": BATTERY_VERSION,
        "traits": traits,
        "steps": steps,
        "snippets": snippets,
    }


def enroll(provider: str, model: str, *, base_url: str, key: str,
           extra_headers: dict | None = None, path: Path | None = None) -> dict:
    result = run_battery(base_url, model, key, extra_headers=extra_headers)
    if not result.get("ok"):
        return result
    entry = {
        "enrolled_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "battery_version": BATTERY_VERSION,
        "traits": result["traits"],
        "steps": result["steps"],
        "snippets": result.get("snippets") or {},
    }
    out_path = save_profile(provider, model, entry, path=path)
    result["profile_path"] = str(out_path)
    result["provider"] = provider
    result["model"] = model
    result["entry"] = entry
    return result


# ── Provider lookup for offline CLI ───────────────────────────────────────────

def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


def _keys_from_auth(provider: str) -> list[str]:
    auth = Path(os.environ.get("ROUTER_AUTH_FILE", "./auth.json"))
    if not auth.exists():
        return []
    try:
        doc = json.loads(auth.read_text())
        keys = (doc.get("providers") or {}).get(provider) or []
        return [str(k).strip() for k in keys if str(k).strip()]
    except Exception:
        return []


def _keys_from_env(provider: str) -> list[str]:
    env_map = {
        "openrouter": "OPENROUTER_API_KEYS",
        "gemini": "GEMINI_API_KEYS",
        "local": "LOCAL_API_KEY",
        "groq": "GROQ_API_KEYS",
        "cerebras": "CEREBRAS_API_KEYS",
        "mistral": "MISTRAL_API_KEYS",
        "sambanova": "SAMBANOVA_API_KEYS",
        "nvidia": "NVIDIA_API_KEYS",
    }
    var = env_map.get(provider)
    if not var:
        return []
    raw = os.environ.get(var) or os.environ.get(var.removesuffix("S")) or ""
    if provider == "local":
        return [raw or "local"]
    return [k.strip() for k in raw.split(",") if k.strip()]


def provider_endpoint(provider: str) -> tuple[str, dict] | None:
    """(base_url, extra_headers) for known providers."""
    if provider == "openrouter":
        return (
            "https://openrouter.ai/api/v1",
            {
                "HTTP-Referer": os.environ.get("OPENROUTER_SITE_URL", "https://github.com/Shaf2665/hermes-router"),
                "X-Title": os.environ.get("OPENROUTER_APP_NAME", "hermes-router"),
            },
        )
    if provider == "local":
        return (os.environ.get("LOCAL_BASE_URL", "http://localhost:11434/v1"), {})
    if provider == "gemini":
        return ("https://generativelanguage.googleapis.com/v1beta/openai", {})
    if provider == "groq":
        return ("https://api.groq.com/openai/v1", {})
    if provider == "cerebras":
        return ("https://api.cerebras.ai/v1", {})
    if provider == "mistral":
        return ("https://api.mistral.ai/v1", {})
    if provider == "sambanova":
        return ("https://api.sambanova.ai/v1", {})
    if provider == "nvidia":
        return ("https://integrate.api.nvidia.com/v1", {})
    return None


def configured_model_ids() -> list[tuple[str, str]]:
    """Models named in env (default + MAIN list + local)."""
    out: list[tuple[str, str]] = []
    or_models = os.environ.get("OPENROUTER_MODEL", "")
    for m in [x.strip() for x in or_models.split(",") if x.strip()]:
        out.append(("openrouter", m))
    main = os.environ.get("OPENROUTER_MAIN_MODEL", "")
    for m in [x.strip() for x in main.split(",") if x.strip()]:
        out.append(("openrouter", m))
    if os.environ.get("LOCAL_BASE_URL") or os.environ.get("LOCAL_MODEL"):
        out.append(("local", os.environ.get("LOCAL_MODEL", "llama3.1")))
    # de-dupe
    seen, uniq = set(), []
    for item in out:
        if item not in seen:
            uniq.append(item)
            seen.add(item)
    return uniq


def list_status() -> dict:
    profiles = load_profiles()
    configured = configured_model_ids()
    rows = []
    for provider, model in configured:
        key = profile_key(provider, model)
        entry = profiles.get(key)
        rows.append({
            "provider": provider,
            "model": model,
            "enrolled": bool(entry),
            "steps": (entry or {}).get("steps"),
            "traits": (entry or {}).get("traits"),
        })
    extra = []
    configured_keys = {profile_key(p, m) for p, m in configured}
    for k, entry in profiles.items():
        if k not in configured_keys:
            prov, _, mod = k.partition("::")
            extra.append({
                "provider": prov,
                "model": mod,
                "enrolled": True,
                "steps": entry.get("steps"),
                "traits": entry.get("traits"),
                "configured": False,
            })
    return {
        "profiles_file": str(PROFILES_FILE),
        "configured": rows,
        "enrolled_other": extra,
        "unenrolled": [r for r in rows if not r["enrolled"]],
    }


# ── Self-check ────────────────────────────────────────────────────────────────

def self_check() -> None:
    assert sanitize_content_text("<arg_value>🌤️ Warsaw morning") == "🌤️ Warsaw morning"
    assert sanitize_content_text('</role>">ok') == "ok"
    assert sanitize_content_text("<arg_value>\">done") == "done"
    assert sanitize_content_text("<|endoftext|>ok") == "ok"
    assert sanitize_content_text("》《ok") == "ok"
    assert is_incomplete_junk_prefix("</ro")
    assert is_incomplete_junk_prefix("<|im_")
    assert not is_incomplete_junk_prefix("Hello")
    assert not is_incomplete_junk_prefix("<item>x")
    # split across deltas → join then sanitize
    assert sanitize_content_text("</ro" + "le>Hi") == "Hi"

    filt = LeadingJunkStreamFilter()
    assert filt.push("</ro") == ""
    assert filt.push("le>Hi there") == "Hi there"
    assert filt.flush() == ""
    filt2 = LeadingJunkStreamFilter()
    assert filt2.push("<arg_value>") == ""
    assert filt2.push("Wait — ok") == "Wait — ok"
    filt3 = LeadingJunkStreamFilter()
    assert filt3.push("<arg_value>All done") == "All done"


    traits = {
        "supports_tools": True,
        "tool_shape": "openai_native",
        "reasoning_field": True,
        "leading_junk": ["arg_value"],
    }
    steps = compose_steps(traits)
    assert "promote_reasoning" in steps and "strip_template_junk" in steps
    assert "passthrough_tools" in steps

    msg = {"content": "", "reasoning": "hello from CoT"}
    apply_steps(msg, ["promote_reasoning", "strip_template_junk"], promote_reasoning=True)
    assert msg.get("content") == "hello from CoT"
    assert "reasoning" not in msg

    msg2 = {"content": "<arg_value>hi"}
    apply_steps(msg2, DEFAULT_STEPS, promote_reasoning=True)
    assert msg2.get("content") == "hi"

    # tool_calls must not skip leading-junk strip (Hermes live: ling + tools)
    msg3 = {
        "content": "</role>The router process",
        "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "x", "arguments": "{}"}}],
    }
    apply_steps(msg3, ["promote_reasoning", "strip_template_junk", "passthrough_tools"])
    assert msg3.get("content") == "The router process"
    assert msg3.get("tool_calls")

    # resolve without profile → default (suppress warn noise)
    assert resolve_steps("__none__", "__none__", warn=False) == DEFAULT_STEPS
    print("enrollment self-check OK", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    repo = Path(__file__).resolve().parent
    os.chdir(repo)
    _load_dotenv(repo / ".env")

    if not argv or argv[0] in ("check", "self-check"):
        self_check()
        return 0

    cmd = argv[0]
    if cmd == "list":
        print(json.dumps(list_status(), indent=2))
        return 0

    if cmd == "enroll":
        if len(argv) < 3:
            print("usage: python -m enrollment enroll <provider> <model>", file=sys.stderr)
            return 2
        provider, model = argv[1], argv[2]
        ep = provider_endpoint(provider)
        if not ep:
            print(f"unknown provider: {provider}", file=sys.stderr)
            return 2
        base_url, headers = ep
        keys = _keys_from_auth(provider) or _keys_from_env(provider)
        if not keys:
            print(f"no API key for {provider} (auth.json or .env)", file=sys.stderr)
            return 2
        result = enroll(provider, model, base_url=base_url, key=keys[0], extra_headers=headers)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result.get("ok") else 1

    print("usage: python -m enrollment [check|list|enroll <provider> <model>]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
