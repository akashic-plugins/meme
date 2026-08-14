from __future__ import annotations

import json
import importlib.util
import os
import shutil
from datetime import datetime, timezone
from types import SimpleNamespace
from pathlib import Path
import sys

import pytest

from agent.core.response_parser import ResponseMetadata
from agent.lifecycle.composition import (
    AFTER_REASONING_CLEANUP_EVENT,
    AFTER_REASONING_PREPROCESS_EVENT,
    PROMPT_RENDER_EVENT,
)
from agent.lifecycle.types import AfterReasoningCtx, PromptRenderCtx
from agent.plugin_composition import (
    PLUGIN_ASSETS,
    CompositionRoot,
    PluginAssets,
    PluginRuntime,
)
from agent.plugins.composable import ComposablePlugin
from agent.plugins.context import PluginContext, PluginKVStore
from agent.plugins.dashboard_host import PluginDashboardHost
from agent.plugins.manager import PluginManager
from bus.event_bus import EventBus
from runtime import MemeCatalog, MemeDecorator


def _load_meme_plugin_module():
    path = Path(__file__).parents[1] / "plugin.py"
    spec = importlib.util.spec_from_file_location(
        "test_meme_plugin",
        path,
        submodule_search_locations=[str(path.parent)],
    )
    if spec is None or spec.loader is None:
        raise ImportError(str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_meme_plugin_module = _load_meme_plugin_module()
MemePlugin = _meme_plugin_module.MemePlugin
MemePromptModule = _meme_plugin_module.MemePromptModule
CITATION_PROTOCOL_SERVICE = _meme_plugin_module.CITATION_PROTOCOL_SERVICE
apply = _meme_plugin_module.apply
inject = _meme_plugin_module.inject


def _write_meme_workspace(workspace: Path) -> Path:
    memes = workspace / "memes"
    (memes / "shy").mkdir(parents=True)
    image = memes / "shy" / "001.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    (memes / "manifest.json").write_text(
        json.dumps(
            {"categories": {"shy": {"desc": "害羞", "enabled": True}}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return image


async def _make_plugin(tmp_path: Path) -> MemePlugin:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir(parents=True)
    plugin = MemePlugin()
    plugin.context = PluginContext(
        event_bus=None,
        tool_registry=None,
        plugin_id="meme",
        plugin_dir=plugin_dir,
        data_dir=tmp_path,
        kv_store=PluginKVStore(plugin_dir / ".kv.json"),
        workspace=tmp_path,
    )
    await plugin.prepare()
    return plugin


def test_catalog_builds_prompt_block(tmp_path: Path) -> None:
    _write_meme_workspace(tmp_path)
    block = MemeCatalog(tmp_path / "memes").build_prompt_block()
    assert block is not None
    assert "<meme:shy>" in block
    assert "只有当你真的要发这个表情时" in block
    assert "代码样式的 `<meme:category>`" in block


def test_decorator_picks_image_for_tag(tmp_path: Path) -> None:
    image = _write_meme_workspace(tmp_path)
    result = MemeDecorator(MemeCatalog(tmp_path / "memes")).decorate(
        "好的", meme_tag="shy"
    )
    assert result.content == "好的"
    assert result.media == [str(image)]


@pytest.mark.asyncio
async def test_meme_prompt_module_injects_bottom_section(tmp_path: Path) -> None:
    _write_meme_workspace(tmp_path)
    plugin = await _make_plugin(tmp_path)
    module = plugin.prompt_render_modules()[0]
    assert isinstance(module, MemePromptModule)
    ctx = PromptRenderCtx(
        session_key="telegram:1",
        channel="telegram",
        chat_id="1",
        content="你好",
        media=None,
        timestamp=datetime.now(timezone.utc),
        history=[],
        skill_names=[],
        retrieved_memory_block="",
        disabled_sections=set(),
        turn_injection_prompt="",
    )
    frame = SimpleNamespace(slots={"prompt:ctx": ctx})
    await module.run(frame)
    assert ctx.system_sections_bottom[0].name == "memes"


@pytest.mark.asyncio
async def test_meme_plugin_decorates_after_reasoning(tmp_path: Path) -> None:
    image = _write_meme_workspace(tmp_path)
    plugin = await _make_plugin(tmp_path)
    ctx = AfterReasoningCtx(
        session_key="telegram:1",
        channel="telegram",
        chat_id="1",
        tools_used=(),
        thinking=None,
        response_metadata=ResponseMetadata(raw_text="好的 <meme:shy>"),
        streamed=False,
        tool_chain=(),
        context_retry={},
        reply="好的 <meme:shy>",
    )
    out = await plugin.decorate_meme(ctx)
    assert out.reply == "好的"
    assert out.media == [str(image)]
    assert out.meme_tag == "shy"


@pytest.mark.asyncio
async def test_meme_plugin_accepts_inline_tag(tmp_path: Path) -> None:
    image = _write_meme_workspace(tmp_path)
    plugin = await _make_plugin(tmp_path)
    ctx = AfterReasoningCtx(
        session_key="telegram:1",
        channel="telegram",
        chat_id="1",
        tools_used=(),
        thinking=None,
        response_metadata=ResponseMetadata(raw_text="快了 <meme:shy>\n\n马上到了"),
        streamed=False,
        tool_chain=(),
        context_retry={},
        reply="快了 <meme:shy>\n\n马上到了",
    )
    out = await plugin.decorate_meme(ctx)
    assert out.reply == "快了\n\n马上到了"
    assert out.media == [str(image)]
    assert out.meme_tag == "shy"


@pytest.mark.asyncio
async def test_meme_plugin_ignores_code_tag(tmp_path: Path) -> None:
    _write_meme_workspace(tmp_path)
    plugin = await _make_plugin(tmp_path)
    ctx = AfterReasoningCtx(
        session_key="telegram:1",
        channel="telegram",
        chat_id="1",
        tools_used=(),
        thinking=None,
        response_metadata=ResponseMetadata(
            raw_text="应该是 `<meme:shy>`。\n\n<æm>shy</æm>"
        ),
        streamed=False,
        tool_chain=(),
        context_retry={},
        reply="应该是 `<meme:shy>`。\n\n<æm>shy</æm>",
    )
    out = await plugin.decorate_meme(ctx)
    assert out.reply == "应该是 `<meme:shy>`。\n\n<æm>shy</æm>"
    assert out.media == []
    assert out.meme_tag is None


@pytest.mark.asyncio
async def test_v3_named_exports_match_legacy_behavior(tmp_path: Path) -> None:
    image = _write_meme_workspace(tmp_path)
    legacy = await _make_plugin(tmp_path)
    ComposablePlugin.from_module(_meme_plugin_module)
    root = CompositionRoot("meme-parity")
    assets = PluginAssets()
    _ = await root.context.provide(PLUGIN_ASSETS, assets)
    _ = await root.context.provide(CITATION_PROTOCOL_SERVICE, object())

    async def mount(ctx) -> None:
        await apply(ctx, object())

    plugin_dir = Path(__file__).parents[1]
    _ = await root.mount(
        mount,
        name="meme",
        inject=inject,
        runtime=PluginRuntime(
            plugin_id="meme",
            plugin_dir=plugin_dir,
            data_dir=tmp_path / "plugin-data",
            workspace=tmp_path,
            config=object(),
        ),
    )
    assert root.receipt().ready is True
    declared = assets.freeze()["meme"]
    assert declared.skill_roots == (plugin_dir / "skills",)
    assert declared.dashboard_module == plugin_dir / "dashboard.py"

    legacy_prompt = PromptRenderCtx(
        session_key="telegram:1",
        channel="telegram",
        chat_id="1",
        content="你好",
        media=None,
        timestamp=datetime.now(timezone.utc),
        history=[],
        skill_names=[],
        retrieved_memory_block="",
        disabled_sections=set(),
        turn_injection_prompt="",
    )
    await legacy.prompt_render_modules()[0].run(
        SimpleNamespace(slots={"prompt:ctx": legacy_prompt})
    )
    v3_prompt = PromptRenderCtx(
        session_key="telegram:1",
        channel="telegram",
        chat_id="1",
        content="你好",
        media=None,
        timestamp=legacy_prompt.timestamp,
        history=[],
        skill_names=[],
        retrieved_memory_block="",
        disabled_sections=set(),
        turn_injection_prompt="",
    )
    await root.context.serial(PROMPT_RENDER_EVENT, v3_prompt)
    assert v3_prompt.system_sections_bottom == legacy_prompt.system_sections_bottom

    legacy_answer = AfterReasoningCtx(
        session_key="telegram:1",
        channel="telegram",
        chat_id="1",
        tools_used=(),
        thinking=None,
        response_metadata=ResponseMetadata(raw_text="好的 <meme:shy>"),
        streamed=False,
        tool_chain=(),
        context_retry={},
        reply="好的 <meme:shy>",
    )
    await legacy.decorate_meme(legacy_answer)
    v3_answer = AfterReasoningCtx(
        session_key="telegram:1",
        channel="telegram",
        chat_id="1",
        tools_used=(),
        thinking=None,
        response_metadata=ResponseMetadata(raw_text="好的 <meme:shy>"),
        streamed=False,
        tool_chain=(),
        context_retry={},
        reply="好的 <meme:shy>",
    )
    await root.context.serial(AFTER_REASONING_PREPROCESS_EVENT, v3_answer)

    assert v3_answer.reply == legacy_answer.reply == "好的"
    assert v3_answer.media == legacy_answer.media == [str(image)]
    assert v3_answer.meme_tag == legacy_answer.meme_tag == "shy"
    await root.dispose()


@pytest.mark.asyncio
async def test_v3_plugin_loads_assets_through_real_manager(tmp_path: Path) -> None:
    _write_meme_workspace(tmp_path / "workspace")
    plugin_home = tmp_path / "plugins"
    citation_dir = plugin_home / "citation"
    citation_dir.mkdir(parents=True)
    (citation_dir / "plugin.py").write_text(
        "from agent.plugin_composition import ServiceKey\n"
        "api_version = 3\n"
        "name = 'citation'\n"
        "version = '1.0.0'\n"
        "SERVICE = ServiceKey('citation.protocol')\n"
        "async def apply(ctx, config):\n"
        "    await ctx.provide(SERVICE, object())\n",
        encoding="utf-8",
    )
    shutil.copytree(
        Path(__file__).parents[1],
        plugin_home / "meme",
        ignore=shutil.ignore_patterns(".git", ".pytest_cache", "__pycache__"),
    )
    workspace = tmp_path / "workspace"
    manager = PluginManager(
        plugin_dirs=[plugin_home],
        event_bus=EventBus(),
        tool_registry=None,
        workspace=workspace,
        installed_cache_root=tmp_path / "plugin-home" / "cache",
    )

    await manager.load_all()

    generation = manager.generation("meme")
    snapshot = manager.current_snapshot
    assert generation is not None and snapshot is not None
    assert isinstance(generation.instance, ComposablePlugin)
    assert generation.contributions.skill_roots == (plugin_home / "meme" / "skills",)
    assert generation.contributions.dashboard_module == (
        plugin_home / "meme" / "dashboard.py"
    )
    assert snapshot.plugin_skill_index is not None
    assert "meme-manage" in snapshot.plugin_skill_index.records
    dashboard = PluginDashboardHost(
        workspace=workspace,
        memory_admin=object(),
        memory_store=object(),
        core_routes=(),
    )
    dashboard.prepare_snapshot(snapshot)
    assert tuple(binding.plugin_id for binding in snapshot.dashboard_bindings) == (
        "meme",
    )
    await manager.terminate_all()


@pytest.mark.asyncio
async def test_citation_meme_cross_repository_parity(tmp_path: Path) -> None:
    raw_citation_root = os.environ.get("AKASHIC_CITATION_ROOT", "").strip()
    if not raw_citation_root:
        pytest.skip("set AKASHIC_CITATION_ROOT to run the pinned cross-repository gate")
    citation_root = Path(raw_citation_root)
    citation_spec = importlib.util.spec_from_file_location(
        "test_citation_plugin",
        citation_root / "plugin.py",
    )
    if citation_spec is None or citation_spec.loader is None:
        raise ImportError(str(citation_root / "plugin.py"))
    citation_module = importlib.util.module_from_spec(citation_spec)
    sys.modules[citation_spec.name] = citation_module
    citation_spec.loader.exec_module(citation_module)

    workspace = tmp_path / "workspace"
    image = _write_meme_workspace(workspace)
    legacy_meme = await _make_plugin(workspace)
    legacy_prompt = PromptRenderCtx(
        session_key="telegram:1",
        channel="telegram",
        chat_id="1",
        content="你好",
        media=None,
        timestamp=datetime.now(timezone.utc),
        history=[],
        skill_names=[],
        retrieved_memory_block="",
        disabled_sections=set(),
        turn_injection_prompt="",
    )
    await citation_module.CitationPromptModule().run(
        SimpleNamespace(slots={"prompt:ctx": legacy_prompt})
    )
    await legacy_meme.prompt_render_modules()[0].run(
        SimpleNamespace(slots={"prompt:ctx": legacy_prompt})
    )
    reply = "答复正文\n§cited:[mem_1]§ <meme:shy>"
    legacy_answer = AfterReasoningCtx(
        session_key="telegram:1",
        channel="telegram",
        chat_id="1",
        tools_used=(),
        thinking=None,
        response_metadata=ResponseMetadata(raw_text=reply),
        streamed=False,
        tool_chain=(),
        context_retry={},
        reply=reply,
    )
    legacy_frame = SimpleNamespace(slots={"reasoning:ctx": legacy_answer})
    await citation_module.CitationAfterReasoningModule().run(legacy_frame)
    await legacy_meme.decorate_meme(legacy_answer)
    await citation_module.ProtocolTagCleanupModule().run(legacy_frame)

    plugin_home = tmp_path / "plugins"
    shutil.copytree(
        citation_root,
        plugin_home / "citation",
        ignore=shutil.ignore_patterns(".git", ".pytest_cache", "__pycache__"),
    )
    shutil.copytree(
        Path(__file__).parents[1],
        plugin_home / "meme",
        ignore=shutil.ignore_patterns(".git", ".pytest_cache", "__pycache__"),
    )
    manager = PluginManager(
        plugin_dirs=[plugin_home],
        event_bus=EventBus(),
        tool_registry=None,
        workspace=workspace,
        installed_cache_root=tmp_path / "plugin-home" / "cache",
    )
    await manager.load_all()
    snapshot = manager.current_snapshot
    assert snapshot is not None and snapshot.composition_root is not None

    v3_prompt = PromptRenderCtx(
        session_key="telegram:1",
        channel="telegram",
        chat_id="1",
        content="你好",
        media=None,
        timestamp=legacy_prompt.timestamp,
        history=[],
        skill_names=[],
        retrieved_memory_block="",
        disabled_sections=set(),
        turn_injection_prompt="",
    )
    await snapshot.composition_root.context.serial(PROMPT_RENDER_EVENT, v3_prompt)
    v3_answer = AfterReasoningCtx(
        session_key="telegram:1",
        channel="telegram",
        chat_id="1",
        tools_used=(),
        thinking=None,
        response_metadata=ResponseMetadata(raw_text=reply),
        streamed=False,
        tool_chain=(),
        context_retry={},
        reply=reply,
    )
    await snapshot.composition_root.context.serial(
        AFTER_REASONING_PREPROCESS_EVENT,
        v3_answer,
    )
    await snapshot.composition_root.context.serial(
        AFTER_REASONING_CLEANUP_EVENT,
        v3_answer,
    )

    assert v3_prompt.system_sections_bottom == legacy_prompt.system_sections_bottom
    assert v3_answer.reply == legacy_answer.reply == "答复正文"
    assert v3_answer.persist_assistant_metadata["cited_memory_ids"] == (
        legacy_frame.slots["persist:assistant:cited_memory_ids"]
    )
    assert v3_answer.media == legacy_answer.media == [str(image)]
    assert v3_answer.meme_tag == legacy_answer.meme_tag == "shy"
    await manager.terminate_all()
