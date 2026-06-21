"""Unified LLM client supporting DeepSeek, Qwen, and OpenAI providers.

Uses httpx for OpenAI-compatible API calls without requiring the openai SDK.
Provider, model, and API keys are configured via environment variables.

Typical usage::

    from workflows.model_client import quick_chat, chat_with_retry

    # One-shot call (uses env LLM_PROVIDER)
    resp = quick_chat("What is LangGraph?")
    print(resp.content)

    # Full control with retries
    resp = chat_with_retry(
        messages=[{"role": "user", "content": "Hello!"}],
        provider="deepseek",
        temperature=0.3,
    )
    print(resp.content, resp.usage)
"""

from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ====================================================================
#  Constants — provider metadata
# ====================================================================

PROVIDER_CONFIGS: dict[str, dict[str, Any]] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "env_key": "DEEPSEEK_API_KEY",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
        "env_key": "QWEN_API_KEY",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "env_key": "OPENAI_API_KEY",
    },
}

# Pricing in USD per 1M tokens (source: provider official pages, 2026-06)
MODEL_PRICING: dict[str, dict[str, float]] = {
    "deepseek-chat": {"input": 0.27, "output": 1.10},
    "qwen-plus": {"input": 0.80, "output": 2.00},
    "qwen-turbo": {"input": 0.30, "output": 0.60},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
}

# Pricing in CNY per 1M tokens (source: provider official pages, 2026-06)
MODEL_PRICING_CNY: dict[str, dict[str, float]] = {
    "deepseek": {"input": 1.0, "output": 2.0},
    "qwen": {"input": 4.0, "output": 12.0},
    "openai": {"input": 150.0, "output": 600.0},
}

DEFAULT_TIMEOUT = 60.0
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0


# ====================================================================
#  Data classes
# ====================================================================


@dataclass
class Usage:
    """Token usage statistics returned by an LLM call.

    Attributes:
        prompt_tokens: Number of tokens in the prompt.
        completion_tokens: Number of tokens in the completion.
        total_tokens: Sum of prompt and completion tokens.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResponse:
    """Structured response from an LLM call.

    Attributes:
        content: The generated text content.
        usage: Token usage statistics.
        model: Model name used for the call.
        provider: Provider name used for the call.
    """

    content: str
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    provider: str = ""


@dataclass
class CostRecord:
    """A single tracked LLM call with its token usage and cost.

    Attributes:
        provider: Provider name (e.g. ``"deepseek"``).
        prompt_tokens: Tokens in the prompt.
        completion_tokens: Tokens in the completion.
        cost_cny: Estimated cost in CNY.
    """

    provider: str
    prompt_tokens: int
    completion_tokens: int
    cost_cny: float


class CostTracker:
    """Track token usage and estimated cost (CNY) across LLM calls.

    Usage::

        tracker = CostTracker()
        tracker.record(usage, "deepseek")
        print(tracker.estimated_cost())
        tracker.report()
    """

    def __init__(self) -> None:
        self._records: list[CostRecord] = []

    def _cny_price(self, provider: str) -> dict[str, float]:
        """Look up CNY pricing for a provider.

        Args:
            provider: Provider name (e.g. ``"deepseek"``).

        Returns:
            Dict with ``"input"`` and ``"output"`` price per 1M tokens.

        Raises:
            ValueError: When pricing data is unavailable.
        """
        pricing = MODEL_PRICING_CNY.get(provider.lower())
        if pricing is None:
            known = ", ".join(sorted(MODEL_PRICING_CNY))
            raise ValueError(
                f"No CNY pricing for provider '{provider}'. Known: {known}"
            )
        return pricing

    def record(self, usage: Usage, provider: str) -> None:
        """Record a single API call's token usage and cost.

        Args:
            usage: Token usage from the LLM response.
            provider: Provider name (e.g. ``"deepseek"``).
        """
        pricing = self._cny_price(provider)
        cost = (
            usage.prompt_tokens / 1_000_000 * pricing["input"]
            + usage.completion_tokens / 1_000_000 * pricing["output"]
        )
        self._records.append(
            CostRecord(
                provider=provider.lower(),
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                cost_cny=round(cost, 6),
            )
        )

    def estimated_cost(self, provider: str | None = None) -> float:
        """Return the total estimated cost (CNY) for all or a specific provider.

        Args:
            provider: If given, only count calls to this provider.

        Returns:
            Total cost in CNY, rounded to 4 decimal places.
        """
        return round(
            sum(
                r.cost_cny
                for r in self._records
                if provider is None or r.provider == provider.lower()
            ),
            4,
        )

    def report(self, provider: str | None = None) -> None:
        """Print a cost summary report via logging.

        Args:
            provider: If given, only show calls to this provider.
        """
        records = (
            self._records
            if provider is None
            else [r for r in self._records if r.provider == provider.lower()]
        )

        if not records:
            logger.info("CostTracker: no calls recorded")
            return

        by_provider: dict[str, list[CostRecord]] = {}
        for r in records:
            by_provider.setdefault(r.provider, []).append(r)

        for prov, rs in by_provider.items():
            total_cost = sum(r.cost_cny for r in rs)
            total_prompt = sum(r.prompt_tokens for r in rs)
            total_completion = sum(r.completion_tokens for r in rs)
            logger.info(
                "CostTracker [%s]  calls=%d  prompt=%d  completion=%d  cost=¥%.4f",
                prov,
                len(rs),
                total_prompt,
                total_completion,
                total_cost,
            )

        overall = sum(r.cost_cny for r in records)
        logger.info("CostTracker total  calls=%d  cost=¥%.4f", len(records), overall)


# Global tracker instance; importable by pipeline.py for final reporting.
tracker = CostTracker()


# ====================================================================
#  Budget guard (lazy singleton)
# ====================================================================


class BudgetExceededError(Exception):
    """预算超限异常，当累计成本超过 budget_yuan 时抛出。"""

    def __init__(self, total_cost: float, budget: float) -> None:
        self.total_cost = total_cost
        self.budget = budget
        super().__init__(f"预算超限: ¥{total_cost:.4f} > ¥{budget:.4f}")


@dataclass
class _GuardRecord:
    """单次 LLM 调用的成本记录（CostGuard 内部使用）。"""

    timestamp: str
    node_name: str
    prompt_tokens: int
    completion_tokens: int
    cost_yuan: float
    model: str = ""


class CostGuard:
    """预算守卫：记录每次 LLM 调用成本并检查是否超预算。"""

    def __init__(
        self,
        budget_yuan: float = 1.0,
        alert_threshold: float = 0.8,
        input_price_per_million: float = 1.0,
        output_price_per_million: float = 2.0,
    ) -> None:
        self.budget_yuan = budget_yuan
        self.alert_threshold = alert_threshold
        self.input_price_per_million = input_price_per_million
        self.output_price_per_million = output_price_per_million
        self.records: list[_GuardRecord] = []

    def record(self, node_name: str, usage: dict, model: str = "") -> _GuardRecord:
        prompt = usage.get("prompt_tokens", 0)
        completion = usage.get("completion_tokens", 0)
        cost = (
            prompt / 1_000_000 * self.input_price_per_million
            + completion / 1_000_000 * self.output_price_per_million
        )
        record = _GuardRecord(
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            node_name=node_name,
            prompt_tokens=prompt,
            completion_tokens=completion,
            cost_yuan=round(cost, 8),
            model=model,
        )
        self.records.append(record)
        return record

    def check(self) -> dict:
        total_cost = sum(r.cost_yuan for r in self.records)
        if total_cost >= self.budget_yuan:
            raise BudgetExceededError(total_cost=total_cost, budget=self.budget_yuan)
        usage_ratio = total_cost / self.budget_yuan if self.budget_yuan > 0 else 0.0
        if usage_ratio >= self.alert_threshold:
            return {
                "status": "warning",
                "total_cost": round(total_cost, 6),
                "budget": self.budget_yuan,
                "usage_ratio": round(usage_ratio, 4),
                "message": f"预算接近上限: ¥{total_cost:.4f} / ¥{self.budget_yuan:.4f} ({usage_ratio:.1%})",
            }
        return {
            "status": "ok",
            "total_cost": round(total_cost, 6),
            "budget": self.budget_yuan,
            "usage_ratio": round(usage_ratio, 4),
            "message": f"预算正常: ¥{total_cost:.4f} / ¥{self.budget_yuan:.4f}",
        }

    def get_report(self) -> dict:
        total_prompt = sum(r.prompt_tokens for r in self.records)
        total_completion = sum(r.completion_tokens for r in self.records)
        total_cost = sum(r.cost_yuan for r in self.records)
        by_node: dict[str, dict] = {}
        for r in self.records:
            node = r.node_name
            if node not in by_node:
                by_node[node] = {
                    "calls": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "cost_yuan": 0.0,
                }
            by_node[node]["calls"] += 1
            by_node[node]["prompt_tokens"] += r.prompt_tokens
            by_node[node]["completion_tokens"] += r.completion_tokens
            by_node[node]["cost_yuan"] = round(
                by_node[node]["cost_yuan"] + r.cost_yuan, 8
            )
        return {
            "summary": {
                "total_calls": len(self.records),
                "total_prompt_tokens": total_prompt,
                "total_completion_tokens": total_completion,
                "total_cost_yuan": round(total_cost, 6),
                "budget_yuan": self.budget_yuan,
            },
            "by_node": by_node,
        }


_COST_GUARD: CostGuard | None = None


def get_cost_guard() -> CostGuard:
    """获取全局 CostGuard 实例（懒加载）。"""
    global _COST_GUARD
    if _COST_GUARD is None:
        budget = float(os.environ.get("BUDGET_YUAN", "1.0"))
        _COST_GUARD = CostGuard(budget_yuan=budget)
    return _COST_GUARD


# ====================================================================
#  Abstract base class
# ====================================================================


class LLMProvider(ABC):
    """Abstract interface for LLM providers.

    All providers must implement ``chat()`` which sends a conversation
    and returns a structured response.
    """

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Send a chat completion request.

        Args:
            messages: List of message dicts with ``role`` and ``content`` keys.
            model:  Model identifier. Falls back to provider default when
                    ``None``.
            temperature: Sampling temperature (0.0 — 2.0).
            max_tokens: Maximum tokens in the response.

        Returns:
            An :class:`LLMResponse` containing the generated text and
            usage statistics.

        Raises:
            httpx.HTTPStatusError: On non-2xx API responses.
            httpx.TimeoutException: On request timeout.
        """


# ====================================================================
#  OpenAI-compatible implementation
# ====================================================================


class OpenAICompatibleProvider(LLMProvider):
    """LLM provider for any OpenAI-compatible API endpoint.

    Uses raw ``httpx`` requests so no external SDK dependency is needed.

    Args:
        api_key: API authentication key.
        base_url: Base URL of the API (e.g. ``https://api.deepseek.com/v1``).
        default_model: Fallback model name.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        default_model: str,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _build_payload(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        return payload

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        resolved_model = model or self._default_model
        url = f"{self._base_url}/chat/completions"

        with httpx.Client(timeout=httpx.Timeout(DEFAULT_TIMEOUT)) as client:
            response = client.post(
                url,
                headers=self._build_headers(),
                json=self._build_payload(
                    messages, resolved_model, temperature, max_tokens
                ),
            )
            response.raise_for_status()
            data = response.json()

        choice = data["choices"][0]
        content = choice["message"]["content"]

        usage_raw = data.get("usage", {})
        usage = Usage(
            prompt_tokens=usage_raw.get("prompt_tokens", 0),
            completion_tokens=usage_raw.get("completion_tokens", 0),
            total_tokens=usage_raw.get("total_tokens", 0),
        )

        return LLMResponse(
            content=content,
            usage=usage,
            model=resolved_model,
            provider="",
        )


# ====================================================================
#  Provider factory
# ====================================================================


def _resolve_provider(name: str | None = None) -> str:
    """Resolve the provider name from argument or environment variable.

    Args:
        name: Explicit provider name. When ``None``, reads ``LLM_PROVIDER``
              from the environment (default ``"deepseek"``).

    Returns:
        Normalised provider name (lowercase).

    Raises:
        ValueError: When the provider is unknown or not configured.
    """
    provider = (name or os.environ.get("LLM_PROVIDER") or "deepseek").lower()

    if provider not in PROVIDER_CONFIGS:
        known = ", ".join(sorted(PROVIDER_CONFIGS))
        raise ValueError(f"Unknown provider '{provider}'. Known: {known}")

    cfg = PROVIDER_CONFIGS[provider]
    api_key = os.environ.get(cfg["env_key"])
    if not api_key:
        raise ValueError(
            f"Missing API key for provider '{provider}': "
            f"set {cfg['env_key']} environment variable"
        )
    return provider


def build_provider(name: str | None = None) -> OpenAICompatibleProvider:
    """Build an :class:`OpenAICompatibleProvider` from environment config.

    Args:
        name: Provider name (``"deepseek"``, ``"qwen"``, ``"openai"``).
              When ``None``, uses ``LLM_PROVIDER`` env var or ``"deepseek"``.

    Returns:
        A configured provider instance.
    """
    provider = _resolve_provider(name)
    cfg = PROVIDER_CONFIGS[provider]
    api_key = os.environ[cfg["env_key"]]

    logger.info("Building provider: %s (model=%s)", provider, cfg["default_model"])
    return OpenAICompatibleProvider(
        api_key=api_key,
        base_url=cfg["base_url"],
        default_model=cfg["default_model"],
    )


# ====================================================================
#  Token estimation
# ====================================================================


def estimate_tokens(text: str) -> int:
    """Roughly estimate the number of tokens in a text string.

    Uses the rule-of-thumb: ~1 token per 4 characters for English,
    ~1 token per 1.5 characters for mixed CJK text.

    Args:
        text: Input string.

    Returns:
        Estimated token count.
    """
    if not text:
        return 0

    # Count CJK characters (approximate range)
    cjk_count = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other_count = len(text) - cjk_count

    return int(cjk_count / 1.5 + other_count / 4.0)


def _build_message_token_count(messages: list[dict[str, str]]) -> int:
    """Count tokens consumed by a message list, including formatting overhead.

    Each message adds ~4 tokens of role/formatting overhead.

    Args:
        messages: List of message dicts.

    Returns:
        Estimated total prompt tokens.
    """
    total = 0
    for msg in messages:
        total += 4  # role + metadata overhead
        for value in msg.values():
            if isinstance(value, str):
                total += estimate_tokens(value)
    return total


# ====================================================================
#  Cost calculation
# ====================================================================


def calculate_cost(
    usage: Usage,
    model: str,
) -> float:
    """Calculate the USD cost of an LLM call based on token usage.

    Args:
        usage: Token usage statistics from the response.
        model: Model name (e.g. ``"deepseek-chat"``).

    Returns:
        Cost in USD.

    Raises:
        ValueError: When pricing data is unavailable for the model.
    """
    pricing = MODEL_PRICING.get(model)
    if pricing is None:
        raise ValueError(f"No pricing data for model '{model}'")

    input_cost = usage.prompt_tokens / 1_000_000 * pricing["input"]
    output_cost = usage.completion_tokens / 1_000_000 * pricing["output"]
    return round(input_cost + output_cost, 6)


# ====================================================================
#  Retry wrapper
# ====================================================================


def chat_with_retry(
    messages: list[dict[str, str]],
    provider: str | None = None,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    max_retries: int = MAX_RETRIES,
) -> LLMResponse:
    """Send a chat completion with automatic retries on failure.

    Retries on any :class:`httpx.HTTPError` or non-2xx status code.
    Uses exponential backoff between attempts.

    Args:
        messages: List of message dicts with ``role`` and ``content`` keys.
        provider: Provider name. Falls back to ``LLM_PROVIDER`` env var.
        model:  Model name. Falls back to provider default when ``None``.
        temperature: Sampling temperature.
        max_tokens: Maximum tokens in the response.
        max_retries: Number of retry attempts (default 3).

    Returns:
        An :class:`LLMResponse` instance.

    Raises:
        httpx.HTTPStatusError: When all retries are exhausted due to
                               persistent HTTP errors.
        RuntimeError: When all retries are exhausted for other reasons.
    """
    resolved_provider = _resolve_provider(provider)
    inst = build_provider(provider)

    last_exception: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            resp = inst.chat(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            tracker.record(resp.usage, resolved_provider)
            return resp
        except httpx.HTTPStatusError as exc:
            last_exception = exc
            logger.warning(
                "HTTP error on attempt %d/%d: %s",
                attempt,
                max_retries,
                exc,
            )
        except httpx.TimeoutException as exc:
            last_exception = exc
            logger.warning(
                "Timeout on attempt %d/%d: %s",
                attempt,
                max_retries,
                exc,
            )
        except httpx.HTTPError as exc:
            last_exception = exc
            logger.warning(
                "Request error on attempt %d/%d: %s",
                attempt,
                max_retries,
                exc,
            )

        if attempt < max_retries:
            delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
            logger.info("Retrying in %.1fs ...", delay)
            time.sleep(delay)

    raise RuntimeError(f"Chat failed after {max_retries} retries") from last_exception


# ====================================================================
#  Convenience helper
# ====================================================================


def quick_chat(
    prompt: str,
    system: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    temperature: float = 0.7,
) -> LLMResponse:
    """One-shot convenience function for a single chat completion.

    Args:
        prompt: User message content.
        system: Optional system message prepended before the user message.
        provider: Provider name (default from ``LLM_PROVIDER`` env var).
        model: Model name (default from provider config).
        temperature: Sampling temperature.

    Returns:
        An :class:`LLMResponse` instance.

    Example::

        resp = quick_chat("Explain RAG in one sentence.")
        print(resp.content)
    """
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    return chat_with_retry(
        messages=messages,
        provider=provider,
        model=model,
        temperature=temperature,
    )


def chat(
    prompt: str,
    system: str | None = None,
    provider: str | None = None,
    temperature: float | None = None,
    max_retries: int = MAX_RETRIES,
    node_name: str = "unknown",
) -> dict[str, Any]:
    """Send a chat prompt and return a plain dict result.

    This is a thin wrapper around :func:`quick_chat` that converts the
    :class:`LLMResponse` object into a plain dict, making it easier to
    use in interactive sessions and quick scripts.

    Args:
        prompt: User message content.
        system: Optional system message prepended before the user message.
        provider: Provider name (default from ``LLM_PROVIDER`` env var).
        temperature: Sampling temperature. Falls back to ``quick_chat`` default
                     (0.7) when ``None``.
        max_retries: Max retry attempts (default 3). Passed directly to
                     ``chat_with_retry``.
        node_name: Node name for cost tracking (default ``"unknown"``).

    Returns:
        A dict with the following keys:

        - **content** (*str*): The generated text.
        - **usage** (*dict*): Token usage with keys ``prompt_tokens``,
          ``completion_tokens``, ``total_tokens``.
        - **model** (*str*): The model used.
        - **provider** (*str*): The provider used.

    Example::

        result = chat("Explain RAG in one sentence.")
        print(result["content"])
        print(result["usage"])
    """
    kwargs = dict(prompt=prompt, system=system, provider=provider)
    if temperature is not None:
        kwargs["temperature"] = temperature
    resp = quick_chat(**kwargs)

    # CostGuard 记录 + 预算检查
    guard = get_cost_guard()
    guard.record(
        node_name=node_name,
        usage={
            "prompt_tokens": resp.usage.prompt_tokens,
            "completion_tokens": resp.usage.completion_tokens,
        },
        model=resp.model,
    )
    guard.check()

    resolved_provider = (
        provider or os.environ.get("LLM_PROVIDER") or "deepseek"
    ).lower()
    return {
        "content": resp.content,
        "usage": {
            "prompt_tokens": resp.usage.prompt_tokens,
            "completion_tokens": resp.usage.completion_tokens,
            "total_tokens": resp.usage.total_tokens,
        },
        "model": resp.model,
        "provider": resp.provider or resolved_provider,
    }


# ====================================================================
#  Self-test
# ====================================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )

    print("=" * 60)
    print("pipeline.model_client 自检")
    print("=" * 60)

    # --- 1. Provider discovery ---
    print("\n[1] 可用的 Provider:")
    for name, cfg in PROVIDER_CONFIGS.items():
        key_present = "✓" if os.environ.get(cfg["env_key"]) else "✗"
        print(f"    {name:12s}  model={cfg['default_model']:20s}  key={key_present}")

    # --- 2. Token estimation ---
    print("\n[2] Token 估算:")
    samples = [
        ("Hello, world!", "纯英文"),
        ("LangGraph 是一个构建有状态多 Agent 编排的框架。", "中英混合"),
    ]
    for text, label in samples:
        estimated = estimate_tokens(text)
        print(f'    {label:12s}  "{text[:40]:40s}"  ≈ {estimated} tokens')

    # --- 3. Cost calculation ---
    print("\n[3] 成本计算 (模拟):")
    dummy_usage = Usage(prompt_tokens=500, completion_tokens=200, total_tokens=700)
    for model in ("deepseek-chat", "qwen-plus", "gpt-4o-mini"):
        cost = calculate_cost(dummy_usage, model)
        print(f"    {model:20s}  500+200 tokens  →  ${cost:.6f}")

    # --- 4. Actual API call (only if key is available) ---
    provider_name = os.environ.get("LLM_PROVIDER", "deepseek").lower()
    cfg = PROVIDER_CONFIGS.get(provider_name)
    if cfg and os.environ.get(cfg["env_key"]):
        print(f"\n[4] 真实 API 调用 (provider={provider_name}):")
        try:
            resp = quick_chat(
                "Say hello in exactly 5 words.",
                temperature=0.0,
            )
            print(f"    回复: {resp.content}")
            print(f"    用量: {resp.usage}")
            cost = calculate_cost(resp.usage, resp.model)
            print(f"    成本: ${cost:.6f}")
        except Exception as e:
            print(f"    调用失败: {e}")
    else:
        print(f"\n[4] 跳过真实调用 (未配置 {provider_name} 的 API key)")

    print("\n" + "=" * 60)
    print("自检完成")
    print("=" * 60)
