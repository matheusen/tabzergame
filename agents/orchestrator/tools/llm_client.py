"""
Unified LLM client supporting multiple providers:
  - anthropic   : Anthropic SDK (ANTHROPIC_API_KEY)
  - claude-code : Claude Code CLI (-p --output-format json)
  - openai      : OpenAI SDK (OPENAI_API_KEY)
  - copilot     : GitHub Copilot CLI (gh copilot)
  - codex       : OpenAI Codex CLI (codex)
  - auto        : detect best available (default)
  - none        : deterministic mode, no LLM
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# ── Candidate Claude Code CLI paths (Windows + Linux/Mac) ────────────────────
def _find_claude_cli() -> str | None:
    # 1. In PATH
    try:
        result = subprocess.run(["claude", "--version"], capture_output=True, timeout=5, shell=False)
        if result.returncode == 0:
            return "claude"
    except FileNotFoundError:
        pass

    # 2. VSCode extension (Windows)
    vscode_ext = Path.home() / ".vscode" / "extensions"
    if vscode_ext.exists():
        candidates = sorted(vscode_ext.glob("anthropic.claude-code-*/resources/native-binary/claude.exe"), reverse=True)
        for c in candidates:
            if c.exists():
                return str(c)

    # 3. Node modules global install
    for candidate in [
        Path.home() / "AppData" / "Roaming" / "npm" / "claude.cmd",
        Path("/usr/local/bin/claude"),
        Path("/usr/bin/claude"),
    ]:
        if candidate.exists():
            return str(candidate)

    return None


def _find_gh_cli() -> str | None:
    try:
        result = subprocess.run(["gh", "--version"], capture_output=True, timeout=5, shell=False)
        if result.returncode == 0:
            return "gh"
    except FileNotFoundError:
        pass
    return None


def _find_codex_cli() -> str | None:
    try:
        result = subprocess.run(["codex", "--version"], capture_output=True, timeout=5, shell=False)
        if result.returncode == 0:
            return "codex"
    except FileNotFoundError:
        pass
    return None


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


# ── JSON extraction ───────────────────────────────────────────────────────────

def extract_json(text: str) -> dict | None:
    """Extract first JSON object from text. Works for CLI providers that return prose + JSON."""
    text = text.strip()

    # 1. Direct parse
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    # 2. Markdown fenced block
    for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", text):
        try:
            return json.loads(match.group(1).strip())
        except (json.JSONDecodeError, ValueError):
            continue

    # 3. First { ... } block (greedy from outermost braces)
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return json.loads(text[start : i + 1])
                except (json.JSONDecodeError, ValueError):
                    start = -1

    return None


def _messages_to_prompt(messages: list[dict]) -> str:
    """Collapse messages list to a single prompt string for CLI providers."""
    parts = []
    for m in messages:
        role = m["role"].upper()
        content = m["content"]
        if role == "SYSTEM":
            parts.append(f"[INSTRUCTIONS]\n{content}")
        elif role == "USER":
            parts.append(f"[REQUEST]\n{content}")
        elif role == "ASSISTANT":
            parts.append(f"[PREVIOUS RESPONSE]\n{content}")
    return "\n\n".join(parts)


# ── Provider implementations ──────────────────────────────────────────────────

class LLMError(Exception):
    pass


@dataclass
class ProviderInfo:
    name: str
    model: str | None
    available: bool
    note: str = ""


class LLMClient:
    """
    Unified LLM client. All agents call `client.complete(messages, json_mode=True)`.
    """

    def __init__(
        self,
        provider: str = "auto",
        model: str | None = None,
        fast_model: str | None = None,
    ) -> None:
        self.requested_provider = provider
        self.model = model
        self.fast_model = fast_model
        self._claude_cli_path: str | None = None

        self.provider, self._note = self._resolve(provider)

    # ── public API ────────────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        return self.provider != "none"

    def describe(self) -> str:
        model_hint = f" ({self.model})" if self.model else ""
        note_hint = f" [{self._note}]" if self._note else ""
        return f"{self.provider}{model_hint}{note_hint}"

    def complete(
        self,
        messages: list[dict],
        json_mode: bool = False,
        max_tokens: int = 1024,
        fast: bool = False,
    ) -> str:
        model = (self.fast_model if fast else self.model) or None
        if self.provider == "anthropic":
            return self._anthropic(messages, json_mode, max_tokens, model)
        if self.provider == "claude-code":
            return self._claude_code(messages, json_mode, max_tokens, model)
        if self.provider == "openai":
            return self._openai(messages, json_mode, max_tokens, model)
        if self.provider == "copilot":
            return self._copilot(messages, max_tokens)
        if self.provider == "codex":
            return self._codex(messages, max_tokens, model)
        raise LLMError(
            "No LLM provider available. Set ANTHROPIC_API_KEY, OPENAI_API_KEY, "
            "install 'anthropic' package, or ensure 'claude' CLI is in PATH."
        )

    # ── auto-detection ────────────────────────────────────────────────────────

    def _resolve(self, provider: str) -> tuple[str, str]:
        p = provider.lower().strip()
        if p in ("auto", ""):
            return self._auto_detect()
        if p == "anthropic":
            return self._check_anthropic()
        if p in ("claude-code", "claude_code", "claude"):
            return self._check_claude_code()
        if p == "openai":
            return self._check_openai()
        if p == "copilot":
            return self._check_copilot()
        if p == "codex":
            return self._check_codex()
        if p == "none":
            return "none", "deterministic mode"
        return "none", f"unknown provider '{provider}'"

    def _auto_detect(self) -> tuple[str, str]:
        p, n = self._check_anthropic()
        if p != "none":
            return p, n + " [auto]"
        p, n = self._check_claude_code()
        if p != "none":
            return p, n + " [auto]"
        p, n = self._check_openai()
        if p != "none":
            return p, n + " [auto]"
        p, n = self._check_copilot()
        if p != "none":
            return p, n + " [auto]"
        p, n = self._check_codex()
        if p != "none":
            return p, n + " [auto]"
        return "none", "no provider detected"

    def _check_anthropic(self) -> tuple[str, str]:
        if not _module_available("anthropic"):
            return "none", "anthropic SDK not installed (pip install anthropic)"
        if not os.getenv("ANTHROPIC_API_KEY"):
            return "none", "ANTHROPIC_API_KEY not set"
        model = self.model or "claude-sonnet-4-6"
        return "anthropic", f"SDK model={model}"

    def _check_claude_code(self) -> tuple[str, str]:
        path = _find_claude_cli()
        if path is None:
            return "none", "claude CLI not found"
        self._claude_cli_path = path
        return "claude-code", f"CLI at {path}"

    def _check_openai(self) -> tuple[str, str]:
        if not _module_available("openai"):
            return "none", "openai SDK not installed"
        if not os.getenv("OPENAI_API_KEY"):
            return "none", "OPENAI_API_KEY not set"
        model = self.model or "gpt-4o"
        return "openai", f"SDK model={model}"

    def _check_copilot(self) -> tuple[str, str]:
        path = _find_gh_cli()
        if path is None:
            return "none", "gh CLI not found"
        # Check copilot extension
        try:
            result = subprocess.run(
                ["gh", "extension", "list"], capture_output=True, timeout=10, shell=False
            )
            if b"copilot" not in (result.stdout + result.stderr).lower():
                return "none", "gh copilot extension not installed"
        except Exception:
            return "none", "gh copilot check failed"
        return "copilot", "gh copilot CLI"

    def _check_codex(self) -> tuple[str, str]:
        path = _find_codex_cli()
        if path is None:
            return "none", "codex CLI not found"
        return "codex", f"CLI at {path}"

    # ── provider implementations ──────────────────────────────────────────────

    def _anthropic(
        self, messages: list[dict], json_mode: bool, max_tokens: int, model: str | None
    ) -> str:
        import anthropic  # type: ignore[import]

        client = anthropic.Anthropic()
        model = model or "claude-sonnet-4-6"

        system_parts: list[Any] = []
        human_messages: list[dict] = []

        for m in messages:
            if m["role"] == "system":
                # Add with prompt caching for long system prompts
                system_parts.append({
                    "type": "text",
                    "text": m["content"],
                    "cache_control": {"type": "ephemeral"},
                })
            else:
                human_messages.append({"role": m["role"], "content": m["content"]})

        if json_mode and human_messages:
            human_messages[-1]["content"] += (
                "\n\nIMPORTANT: Return ONLY valid JSON. No markdown fences, no explanation."
            )

        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": human_messages,
            "betas": ["prompt-caching-2024-07-31"],
        }
        if system_parts:
            kwargs["system"] = system_parts

        resp = client.beta.messages.create(**kwargs)
        return resp.content[0].text  # type: ignore[index]

    def _claude_code(
        self, messages: list[dict], json_mode: bool, max_tokens: int, model: str | None
    ) -> str:
        cli = self._claude_cli_path or "claude"
        has_api_key = bool(os.getenv("ANTHROPIC_API_KEY"))

        system_prompt = next((m["content"] for m in messages if m["role"] == "system"), None)
        user_messages = [m for m in messages if m["role"] != "system"]
        user_prompt = _messages_to_prompt(user_messages)

        if json_mode:
            user_prompt += "\n\nReturn ONLY valid JSON. No markdown fences. No explanation."

        # With ANTHROPIC_API_KEY: use --bare (no OAuth, no hooks, clean)
        # Without: use OAuth session (no --bare, uses stored login)
        cmd = [cli, "-p", user_prompt, "--output-format", "json", "--no-session-persistence"]
        if has_api_key:
            cmd.append("--bare")

        if system_prompt:
            cmd += ["--system-prompt", system_prompt]
        if model:
            cmd += ["--model", model]

        stdout, stderr = self._run_cli(cmd, timeout=120)

        # Try to parse wrapper JSON
        try:
            wrapper = json.loads(stdout)
        except json.JSONDecodeError:
            # Older CLI or raw text response
            if stdout:
                return stdout
            raise LLMError(f"Claude Code CLI returned no parseable output. stderr: {stderr[:300]}")

        # Check for "Not logged in" without API key — try OAuth mode without --bare
        if wrapper.get("is_error") and "Not logged in" in str(wrapper.get("result", "")):
            if has_api_key:
                raise LLMError("Claude Code CLI: Not logged in. Ensure ANTHROPIC_API_KEY is valid.")
            # Try without --bare (uses OAuth keychain)
            cmd_oauth = [c for c in cmd if c != "--bare"]
            stdout2, stderr2 = self._run_cli(cmd_oauth, timeout=120)
            try:
                wrapper = json.loads(stdout2)
            except json.JSONDecodeError:
                if stdout2:
                    return stdout2
                raise LLMError(f"Claude Code CLI (OAuth) returned no output. stderr: {stderr2[:300]}")

        if wrapper.get("is_error"):
            error_msg = wrapper.get("result") or "unknown error"
            raise LLMError(f"Claude Code CLI error: {error_msg}")

        return str(wrapper.get("result", ""))

    @staticmethod
    def _run_cli(cmd: list[str], timeout: int) -> tuple[str, str]:
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=timeout, shell=False)
        except subprocess.TimeoutExpired:
            raise LLMError(f"CLI timed out after {timeout}s")
        except FileNotFoundError:
            raise LLMError(f"CLI not found: {cmd[0]}")
        return (
            result.stdout.decode("utf-8", errors="replace").strip(),
            result.stderr.decode("utf-8", errors="replace").strip(),
        )

    def _openai(
        self, messages: list[dict], json_mode: bool, max_tokens: int, model: str | None
    ) -> str:
        from openai import OpenAI  # type: ignore[import]

        client = OpenAI()
        kwargs: dict[str, Any] = {
            "model": model or "gpt-4o",
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.1,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        resp = client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    def _copilot(self, messages: list[dict], max_tokens: int) -> str:
        # gh copilot is limited to shell suggestions — use as last resort
        last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        prompt = last_user[:500]

        result = subprocess.run(
            ["gh", "copilot", "suggest", "-t", "shell", prompt],
            capture_output=True,
            timeout=60,
            shell=False,
        )
        output = result.stdout.decode("utf-8", errors="replace").strip()
        if not output:
            raise LLMError("gh copilot returned empty response")
        return output

    def _codex(self, messages: list[dict], max_tokens: int, model: str | None) -> str:
        prompt = _messages_to_prompt(messages)

        output_path = Path(tempfile.gettempdir()) / f"tabzer-codex-{os.getpid()}.txt"
        cmd = [
            "codex",
            "exec",
            "--sandbox",
            "read-only",
            "--output-last-message",
            str(output_path),
            prompt,
        ]
        if model:
            cmd[2:2] = ["--model", model]

        result = subprocess.run(cmd, capture_output=True, timeout=120, shell=False)
        if output_path.exists():
            output = output_path.read_text(encoding="utf-8", errors="replace").strip()
            output_path.unlink(missing_ok=True)
            if output:
                return output

        output = result.stdout.decode("utf-8", errors="replace").strip()
        if result.returncode != 0 and not output:
            raise LLMError(f"codex CLI failed: {result.stderr.decode('utf-8', errors='replace')[:300]}")
        return output


# ── factory ───────────────────────────────────────────────────────────────────

_client_cache: LLMClient | None = None


def get_client(
    provider: str = "auto",
    model: str | None = None,
    fast_model: str | None = None,
    force_new: bool = False,
) -> LLMClient:
    """Return a cached LLMClient (or create a new one if provider/model changed)."""
    global _client_cache
    if _client_cache is None or force_new:
        _client_cache = LLMClient(provider=provider, model=model, fast_model=fast_model)
        if _client_cache.available:
            print(f"[LLM] Provider: {_client_cache.describe()}")
        else:
            print(f"[LLM] No provider available ({_client_cache._note}) — deterministic mode")
    return _client_cache


def list_providers() -> list[ProviderInfo]:
    """Detect all providers and their availability status."""
    tmp = LLMClient.__new__(LLMClient)
    tmp.model = None
    tmp.fast_model = None
    tmp._claude_cli_path = None

    def check(p: str) -> ProviderInfo:
        resolved, note = tmp._resolve(p)
        return ProviderInfo(name=p, model=tmp.model, available=resolved != "none", note=note)

    return [
        check("anthropic"),
        check("claude-code"),
        check("openai"),
        check("copilot"),
        check("codex"),
    ]
