"""LLM 接入层：真实模型 + 本地规则引擎，统一成同一个 parse_text() 接口。

换模型只改 .env 里的 LLM_BASE_URL / LLM_MODEL（OpenAI 兼容协议），代码一行不用动。
"""

import json
import re
import time
from dataclasses import dataclass

import httpx

from . import config, mock_engine, prompt

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


class LLMError(RuntimeError):
    pass


@dataclass
class Outcome:
    data: dict
    provider: str
    elapsed_ms: int
    error: str | None = None
    raw: str | None = None


def _extract_json(content: str) -> dict:
    """模型偶尔会裹一层 ```json，或者前后多一句废话——两种都尽量救回来。"""
    text = content.strip()
    fence = _JSON_FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start: end + 1])
        raise LLMError(f"返回内容不是合法 JSON：{content[:120]}")


def normalize_output(data: dict) -> tuple[dict, str | None]:
    """四道关里的后三道：字段齐全 / 枚举合法 / 长度截断。

    返回 (规范化后的数据, 错误信息)。错误信息非空即判定为解析失败。
    """
    if not isinstance(data, dict):
        return {}, "返回结构不是对象"

    out: dict = {}
    out["phone"] = (str(data.get("phone")).strip() or None) if data.get("phone") else None
    if out["phone"]:
        digits = re.sub(r"\D", "", out["phone"])
        out["phone"] = digits if re.fullmatch(r"1[3-9]\d{9}", digits) else None

    industry = data.get("customer_industry")
    industry = str(industry).strip() if industry else None
    out["customer_industry"] = industry if industry in config.INDUSTRIES else None

    demand = (data.get("demand") or "").strip() if isinstance(data.get("demand"), str) else ""
    out["demand"] = demand[:60]

    budget = data.get("budget_hint")
    out["budget_hint"] = str(budget).strip()[:40] if budget else None

    intent = str(data.get("intent_level") or "").strip()
    if intent not in config.INTENT_LEVELS:
        return out, f"intent_level 非法：{intent or '(空)'}"
    out["intent_level"] = intent

    risk = data.get("risk_note")
    out["risk_note"] = str(risk).strip()[:40] if risk else None

    if not out["demand"]:
        return out, "demand 为空（必填字段缺失）"

    return out, None


async def _call_deepseek(text: str) -> str:
    url = f"{config.LLM_BASE_URL}/chat/completions"
    payload = {
        "model": config.LLM_MODEL,
        "messages": prompt.build_messages(text),
        "temperature": config.LLM_TEMPERATURE,
        "max_tokens": config.LLM_MAX_TOKENS,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {config.LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=config.LLM_TIMEOUT) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        body = resp.json()
    return body["choices"][0]["message"]["content"]


async def parse_text(text: str) -> Outcome:
    """统一入口：有 Key 调模型（失败重试 1 次），无 Key 走规则引擎。"""
    started = time.perf_counter()

    if config.LLM_PROVIDER == "mock":
        data = mock_engine.parse(text)
        normalized, err = normalize_output(data)
        return Outcome(
            data=normalized,
            provider="mock",
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            error=err,
        )

    last_error: str | None = None
    raw: str | None = None
    for attempt in range(2):          # 首次 + 1 次重试（PRD FR-2.5）
        try:
            raw = await _call_deepseek(text)
            normalized, err = normalize_output(_extract_json(raw))
            return Outcome(
                data=normalized,
                provider="deepseek",
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                error=err,
                raw=raw,
            )
        except Exception as exc:      # 超时 / 5xx / 非 JSON / 字段错
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt == 0:
                import asyncio
                await asyncio.sleep(2)   # 退避 2s

    return Outcome(
        data={},
        provider="deepseek",
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        error=last_error or "未知错误",
        raw=raw,
    )
