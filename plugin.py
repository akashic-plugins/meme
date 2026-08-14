from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

from agent.lifecycle.types import AfterReasoningCtx, PromptRenderCtx
from agent.plugin_composition import (
    SKILLS,
    UI_SLOTS,
    Context,
    ServiceKey,
)
from agent.plugins import Plugin, on_after_reasoning
from agent.prompting import PromptSectionRender
from agent.turn_events.after_reasoning import AFTER_REASONING_BEFORE_EVENT_BUS
from agent.turn_events.prompt_render import PROMPT_RENDER_AFTER_EVENT_BUS
from .runtime import MemeCatalog, MemeDecorator

_CTX_SLOT = "prompt:ctx"
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


class MemePromptModule:
    slot = "meme.prompt"
    requires = ("prompt_render.emit", "citation.prompt", _CTX_SLOT)
    produces = (_CTX_SLOT,)

    def __init__(self, plugin: "MemePlugin") -> None:
        self._plugin = plugin

    async def run(self, frame: Any) -> Any:
        ctx = frame.slots.get(_CTX_SLOT)
        if not isinstance(ctx, PromptRenderCtx):
            return frame
        append_meme_prompt(ctx, self._plugin.catalog)
        return frame


api_version = 3
name = "meme"
version = "1.0.0"
inject: tuple[ServiceKey[object], ...] = (
    CITATION_PROTOCOL_SERVICE,
    SKILLS,
    UI_SLOTS,
)


async def apply(ctx: Context, config: object) -> None:
    """Build Meme domain objects and register their Core-hosted adapters."""

    # 1. Domain state remains plugin-owned and reads the assigned workspace.
    _ = config
    catalog = MemeCatalog(ctx.runtime.workspace / "memes")
    decorator = MemeDecorator(catalog)

    # 2. Static capabilities remain separate reversible Fiber effects.
    skills = ctx.require(SKILLS)
    _ = await skills.register(ctx, "skills")
    ui_slots = ctx.require(UI_SLOTS)
    _ = await ui_slots.register_dashboard(ctx, "dashboard.py")

    # 3. Turn behavior remains plugin-owned and ordered by typed events.
    def prompt_listener(prompt: PromptRenderCtx) -> None:
        append_meme_prompt(prompt, catalog)

    def answer_listener(answer: AfterReasoningCtx) -> None:
        decorate_meme_ctx(answer, decorator)

    _ = await ctx.on(PROMPT_RENDER_AFTER_EVENT_BUS, prompt_listener)
    _ = await ctx.on(AFTER_REASONING_BEFORE_EVENT_BUS, answer_listener)


class MemePlugin(Plugin):
    api_version = 2

    @classmethod
    def dashboard_module(cls) -> str | None:
        return "dashboard.py"

    name = "meme"
    version = "1.0.0"

    @classmethod
    def skill_roots(cls) -> tuple[str, ...]:
        return ("skills",)

    _catalog: Any = None
    _decorator: Any = None

    async def prepare(self) -> None:
        memes_dir = (
            _workspace(self.context.plugin_dir, self.context.workspace) / "memes"
        )
        self._catalog = MemeCatalog(memes_dir)
        self._decorator = MemeDecorator(self._catalog)

    def prompt_render_modules(self) -> list[object]:
        return [MemePromptModule(self)]

    @on_after_reasoning()
    async def decorate_meme(self, ctx: AfterReasoningCtx) -> AfterReasoningCtx:
        decorate_meme_ctx(ctx, self.decorator)
        return ctx

    @property
    def catalog(self) -> Any:
        if self._catalog is None:
            raise RuntimeError("meme 插件尚未初始化")
        return self._catalog

    @property
    def decorator(self) -> Any:
        if self._decorator is None:
            raise RuntimeError("meme 插件尚未初始化")
        return self._decorator


def _extract_meme_tag(response: str) -> tuple[str, str | None]:
    match = _MEME_RE.search(response)
    if match is None:
        return response.strip(), None
    cleaned = _MEME_RE.sub("", response)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r" {2,}", " ", cleaned)
    return cleaned.strip(), match.group(1).lower()


def _workspace(plugin_dir: Path, configured: Path | None) -> Path:
    if configured is not None:
        return configured
    return cast(Path, plugin_dir.parent.parent)
