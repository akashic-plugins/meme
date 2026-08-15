from __future__ import annotations

import re

from agent.lifecycle.composition import (
    AFTER_REASONING_PREPROCESS_EVENT,
    PROMPT_RENDER_EVENT,
)
from agent.lifecycle.types import AfterReasoningCtx, PromptRenderCtx
from agent.plugin_composition import Context, ServiceKey
from agent.prompting import PromptSectionRender
from .runtime import MemeCatalog, MemeDecorator

_MEME_RE = re.compile(
    r"(?<!`)<meme:([a-zA-Z0-9_-]+)>(?!`)",
    re.IGNORECASE,
)

CITATION_PROTOCOL_SERVICE = ServiceKey[object]("citation.protocol")


def append_meme_prompt(ctx: PromptRenderCtx, catalog: MemeCatalog) -> None:
    block = catalog.build_prompt_block()
    if not block:
        return
    ctx.system_sections_bottom.append(
        PromptSectionRender(
            name="memes",
            content=f"# Memes\n\n{block}",
            is_static=False,
        )
    )


def decorate_meme_ctx(ctx: AfterReasoningCtx, decorator: MemeDecorator) -> None:
    cleaned, tag = _extract_meme_tag(ctx.reply)
    decorated = decorator.decorate(cleaned, meme_tag=tag)
    ctx.reply = decorated.content
    ctx.media.extend(decorated.media)
    ctx.meme_tag = decorated.tag


api_version = 3
name = "meme"
version = "1.0.0"
inject: tuple[ServiceKey[object], ...] = (CITATION_PROTOCOL_SERVICE,)
skill_roots = ("skills",)
dashboard_module = "dashboard.py"
workspace_roots = ("memes",)


async def apply(ctx: Context, config: object) -> None:
    """Build Meme domain objects and register their Core-hosted adapters."""

    # 1. Domain state remains plugin-owned and reads the assigned workspace.
    _ = config
    catalog = MemeCatalog(ctx.workspace_root("memes"))
    decorator = MemeDecorator(catalog)

    # 2. Lifecycle behavior is owned by reversible Fiber effects.
    def prompt_listener(prompt: PromptRenderCtx) -> None:
        append_meme_prompt(prompt, catalog)

    def answer_listener(answer: AfterReasoningCtx) -> None:
        decorate_meme_ctx(answer, decorator)

    _ = await ctx.on(PROMPT_RENDER_EVENT, prompt_listener)
    _ = await ctx.on(AFTER_REASONING_PREPROCESS_EVENT, answer_listener)


def _extract_meme_tag(response: str) -> tuple[str, str | None]:
    match = _MEME_RE.search(response)
    if match is None:
        return response.strip(), None
    cleaned = _MEME_RE.sub("", response)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r" {2,}", " ", cleaned)
    return cleaned.strip(), match.group(1).lower()
