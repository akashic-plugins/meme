from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from agent.plugin_composition import Context
from agent.plugin_composition.artifacts import (
    ARTIFACT_IMPORT,
    ArtifactImport,
    AttachmentKind,
)
from agent.plugin_contracts import ContentPart

if __package__:
    from .boundary import CONTENT, Reference, SpanData, TextSource
else:  # test harness imports the entrypoint as a standalone module
    from boundary import CONTENT, Reference, SpanData, TextSource

from .runtime import MemeCatalog, MemeDecorator, MemeSnapshot

_MEME_RE = re.compile(
    r"\s*<meme:([a-zA-Z0-9_-]+)>",
    re.IGNORECASE,
)
_PROTOCOL_SUFFIX_RE = re.compile(
    r"(?:\s*(?:<[a-zA-Z][a-zA-Z0-9_-]*:[^<>\s]+>|§[a-zA-Z][a-zA-Z0-9_-]*:\[[^\]]*\]§))*\s*$",
    re.IGNORECASE,
)


def _meme_prompt(snapshot: MemeSnapshot) -> str:
    block = snapshot.build_prompt_block()
    return "" if block is None else f"# Memes\n\n{block}"


async def decode_meme(
    source: TextSource,
    _references: tuple[Reference, ...],
    *,
    decorator: MemeDecorator,
    artifacts: ArtifactImport,
) -> tuple[Sequence[SpanData], Mapping[str, object]]:
    """清理 Meme 标记，选定并导入至多一张不可变图片。"""
    matches = [
        match
        for match in source.matches(_MEME_RE)
        if _PROTOCOL_SUFFIX_RE.fullmatch(source.text[match.end() :]) is not None
    ]
    if not matches:
        return (), {}

    tag = matches[0].group(1).lower()
    decorated = decorator.decorate("", meme_tag=tag)
    parts: tuple[ContentPart, ...] = ()
    status = "missing"
    if decorated.media:
        attachment = await artifacts.import_source(
            decorated.media[0],
            AttachmentKind.IMAGE,
        )
        parts = (ContentPart("artifact_ref", attachment.artifact_id),)
        status = "selected"

    spans: list[SpanData] = [
        {"start": match.start(), "end": match.end(), "parts": parts if index == 0 else ()}
        for index, match in enumerate(matches)
    ]
    return spans, {
        "version": 1,
        "category": tag,
        "selection": "random",
        "status": status,
    }


def build_protocol(
    catalog: MemeCatalog,
    artifacts: ArtifactImport,
) -> Mapping[str, object]:
    """固定一次请求共用的类别、提示与图片候选。"""
    snapshot = catalog.snapshot()
    decorator = MemeDecorator(snapshot)

    async def decode(source: TextSource, references: tuple[Reference, ...]):
        return await decode_meme(
            source,
            references,
            decorator=decorator,
            artifacts=artifacts,
        )

    return {
        "name": "meme",
        "prompt": _meme_prompt(snapshot),
        "decode": decode,
        "content": {},
    }


api_version = 3
name = "meme"
version = "2.0.0"
inject = (CONTENT, ARTIFACT_IMPORT)
skill_roots = ("skills",)
dashboard_module = "dashboard.py"
web_module = "web_module.js"
web_requires = ("workbench.panels.v2",)
web_provides = ()
web_contract_digests = {
    "workbench.panels.v2": "fb6417c9bf532c1fdb344767d06065d5d3293da85deb64eff1e8088889a33bcb",
}
workspace_roots = ("memes",)


async def apply(ctx: Context, config: object) -> None:
    """注册 Meme 的动态提示、解析器与图片导入贡献。"""
    _ = config
    catalog = MemeCatalog(ctx.workspace_root("memes"))
    artifacts = ctx.require(ARTIFACT_IMPORT)
    _ = await ctx.require(CONTENT).register(
        ctx,
        build_protocol(catalog, artifacts),
        prepare=lambda: build_protocol(catalog, artifacts),
    )
