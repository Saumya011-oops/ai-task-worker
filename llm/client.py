"""Provider-neutral LLM client with forced native tool calling (gemini / openai / anthropic).

MESSAGE FORMAT (provider-neutral, deliberately minimal):
    messages = [{"role": "user" | "assistant" | "tool", "content": "<text>"}, ...]
  * "user":      task text / controller hints.
  * "assistant": the agent's previous turn as text (e.g. 'Thought: ... Action: goto {"url": ...}').
  * "tool":      a tool result; sent to the provider as a user-role text 'Observation: <content>'.
  Consecutive same-role messages are merged; history must contain at least one user/tool message.
TOOL SPECS: [{"name", "description", "parameters": <JSON-Schema object>}] (tools.base.schemas()).
  An optional string arg `thought` is injected into every tool schema; it is returned as Action.thought
  (any free text the model emits alongside the call is used if `thought` is absent).
"""
from __future__ import annotations

import copy
import json
import os
import time
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

from agent.types import Action

load_dotenv()

_KEYS = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
_THOUGHT = {"type": "string", "description": "One or two sentences: why you are taking this action."}


class LLMError(Exception):
    """Bad/missing tool call, bad config, or provider failure."""


def with_thought(tools: list[dict]) -> list[dict]:
    """Deep-copy tool specs and add an optional `thought` property to each."""
    out = copy.deepcopy(tools)
    for t in out:
        t["parameters"].setdefault("type", "object")
        t["parameters"].setdefault("properties", {})["thought"] = dict(_THOUGHT)
    return out


def normalize_messages(messages: list[dict]) -> list[dict]:
    """-> [{role: 'user'|'assistant', content: str}] with tool->user 'Observation:' and merged runs."""
    out: list[dict] = []
    for m in messages:
        role, text = m["role"], str(m.get("content", ""))
        if role == "tool":
            role, text = "user", f"Observation: {text}"
        if role not in ("user", "assistant"):
            raise LLMError(f"Unknown message role {role!r}")
        if out and out[-1]["role"] == role:
            out[-1]["content"] += "\n\n" + text
        else:
            out.append({"role": role, "content": text})
    if not out or out[0]["role"] != "user":
        out.insert(0, {"role": "user", "content": "(begin)"})
    return out


# --- response parsers: each returns (text, tool_name | None, args dict) ------------------------------

def parse_anthropic(resp: Any) -> tuple[str, str | None, dict]:
    text, name, args = [], None, {}
    for b in resp.content:
        if b.type == "text":
            text.append(b.text)
        elif b.type == "tool_use" and name is None:
            name, args = b.name, dict(b.input or {})
    return " ".join(text).strip(), name, args


def parse_openai(resp: Any) -> tuple[str, str | None, dict]:
    msg = resp.choices[0].message
    calls = getattr(msg, "tool_calls", None) or []
    if not calls:
        return (msg.content or "").strip(), None, {}
    fn = calls[0].function
    try:
        args = json.loads(fn.arguments or "{}")
    except json.JSONDecodeError as e:
        raise LLMError(f"Model returned invalid JSON arguments for {fn.name}: {e}") from e
    return (msg.content or "").strip(), fn.name, args


def parse_gemini(resp: Any) -> tuple[str, str | None, dict]:
    text, name, args = [], None, {}
    cands = getattr(resp, "candidates", None) or []
    parts = (cands[0].content.parts or []) if cands and cands[0].content else []
    for p in parts:
        if getattr(p, "function_call", None) and name is None:
            name, args = p.function_call.name, dict(p.function_call.args or {})
        elif getattr(p, "text", None):
            text.append(p.text)
    return " ".join(text).strip(), name, args


class LLMClient:
    def __init__(self, provider: str | None = None, model: str | None = None, api_key: str | None = None):
        self.provider = (provider or os.getenv("LLM_PROVIDER", "")).strip().lower()
        self.model = model or os.getenv("LLM_MODEL", "")
        if self.provider not in _KEYS:
            raise LLMError(f"LLM_PROVIDER must be one of {list(_KEYS)}, got {self.provider!r}")
        if not self.model:
            raise LLMError("LLM_MODEL is not set")
        self.model = self.model.split("#")[0].strip().split("/")[-1]  # tolerate "gemini/<model>" (litellm style)
        # Key pool: explicit key, else KEY_1..KEY_n, else the single KEY. On quota/rate errors we rotate.
        base = _KEYS[self.provider]
        pool = [api_key] if api_key else [os.getenv(f"{base}_{i}", "") for i in range(1, 11)] + [os.getenv(base, "")]
        self.keys = [k.split("#")[0].strip() for k in pool if k and k.strip()]
        if not self.keys:
            raise LLMError(f"{base} (or {base}_1..n) is not set in .env")
        self._ki = 0
        self.api_key = self.keys[0]
        self._client: Any = None  # created lazily so construction is offline-safe

    # ---- provider plumbing -------------------------------------------------------------------
    def _sdk(self) -> Any:
        if self._client is None:
            if self.provider == "anthropic":
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.api_key)
            elif self.provider == "openai":
                import openai
                self._client = openai.OpenAI(api_key=self.api_key)
            else:
                from google import genai
                self._client = genai.Client(api_key=self.api_key)
        return self._client

    def _call(self, messages: list[dict], tools: list[dict], system: str) -> tuple[str, str | None, dict]:
        """One forced tool call. tools are provider-neutral specs. Returns (text, tool_name, args)."""
        msgs = normalize_messages(messages)
        try:
            if self.provider == "anthropic":
                resp = self._sdk().messages.create(
                    model=self.model, max_tokens=4096, system=system or "You are a helpful agent.",
                    messages=msgs,
                    tools=[{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools],
                    tool_choice={"type": "any"})
                return parse_anthropic(resp)
            if self.provider == "openai":
                oa = ([{"role": "system", "content": system}] if system else []) + msgs
                resp = self._sdk().chat.completions.create(
                    model=self.model, messages=oa,
                    tools=[{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                             "parameters": t["parameters"]}} for t in tools],
                    tool_choice="required")
                return parse_openai(resp)
            from google.genai import types
            contents = [types.Content(role="user" if m["role"] == "user" else "model",
                                      parts=[types.Part(text=m["content"])]) for m in msgs]
            cfg = types.GenerateContentConfig(
                system_instruction=system or None,
                tools=[types.Tool(function_declarations=[
                    types.FunctionDeclaration(name=t["name"], description=t["description"],
                                              parameters_json_schema=t["parameters"]) for t in tools])],
                tool_config=types.ToolConfig(function_calling_config=types.FunctionCallingConfig(
                    mode=types.FunctionCallingConfigMode.ANY)),
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
            return parse_gemini(self._sdk().models.generate_content(model=self.model, contents=contents, config=cfg))
        except LLMError:
            raise
        except Exception as e:
            raise LLMError(f"{self.provider} API call failed: {type(e).__name__}: {e}") from e

    def _raw(self, messages: list[dict], tools: list[dict], system: str) -> tuple[str, str | None, dict]:
        """_call with key rotation: on quota/rate/overload errors switch to the next key (and retry)."""
        last: Exception | None = None
        for _ in range(len(self.keys) + 1):   # one full pass over the key pool
            try:
                return self._call(messages, tools, system)
            except LLMError as e:
                last = e
                if not any(m in str(e) for m in ("429", "RESOURCE_EXHAUSTED", "quota", "503", "UNAVAILABLE", "overloaded")):
                    raise
                self._ki = (self._ki + 1) % len(self.keys)
                self.api_key, self._client = self.keys[self._ki], None
                time.sleep(1.5)
        raise last  # type: ignore[misc]

    # ---- public API --------------------------------------------------------------------------
    def next_action(self, messages: list[dict], tools: list[dict], system: str = "") -> Action:
        """Force exactly one tool call and return it as an Action."""
        text, name, args = self._raw(messages, with_thought(tools), system)
        valid = {t["name"] for t in tools}
        if not name:
            raise LLMError(f"Model made no tool call. Text: {text[:300]!r}")
        if name not in valid:
            raise LLMError(f"Model called unknown tool {name!r}; valid: {sorted(valid)}")
        thought = str(args.pop("thought", "") or text)
        return Action(thought=thought, tool=name, args=args)

    def structured(self, messages: list[dict], schema: type[BaseModel], system: str = "") -> BaseModel:
        """Return a validated `schema` instance by forcing a single 'respond' tool carrying the JSON schema."""
        js = schema.model_json_schema()
        spec = [{"name": "respond", "description": f"Return the final structured answer ({schema.__name__}).",
                 "parameters": js}]
        _, name, args = self._raw(messages, spec, system)
        if name != "respond":
            raise LLMError("Model did not return a structured response")
        try:
            return schema.model_validate(args)
        except ValidationError as e:
            raise LLMError(f"Structured output failed validation: {e}") from e
