from __future__ import annotations

import importlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from agent.core.response_parser import ResponseMetadata
from agent.lifecycle.composition import (
    AFTER_REASONING_CLEANUP_EVENT,
    AFTER_REASONING_PREPROCESS_EVENT,
    PROMPT_RENDER_EVENT,
)
from agent.lifecycle.types import AfterReasoningCtx, PromptRenderCtx
from agent.plugin_composition import (
    CompositionRoot,
    Context,
    DashboardContext,
    PluginRuntime,
)
from agent.plugins.composable import ComposablePlugin
from agent.plugins.dashboard_host import DashboardBinding, PluginDashboardHost
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
CITATION_PROTOCOL_SERVICE = _meme_plugin_module.CITATION_PROTOCOL_SERVICE
apply = _meme_plugin_module.apply
decorate_meme_ctx = _meme_plugin_module.decorate_meme_ctx
inject = _meme_plugin_module.inject


def _copy_ignore():
    return shutil.ignore_patterns(
        ".akashic-core",
        ".citation",
        ".git",
        ".plugin-contracts",
        ".pytest_cache",
        "__pycache__",
    )


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


def _prompt_ctx() -> PromptRenderCtx:
    return PromptRenderCtx(
        session_key="webui:1",
        channel="webui",
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


def _answer_ctx(reply: str) -> AfterReasoningCtx:
    return AfterReasoningCtx(
        session_key="webui:1",
        channel="webui",
        chat_id="1",
        tools_used=(),
        thinking=None,
        response_metadata=ResponseMetadata(raw_text=reply),
        streamed=False,
        tool_chain=(),
        context_retry={},
        reply=reply,
    )


def test_catalog_builds_prompt_block(tmp_path: Path) -> None:
    _ = _write_meme_workspace(tmp_path)
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


def test_decorate_meme_ctx_updates_answer_metadata(tmp_path: Path) -> None:
    image = _write_meme_workspace(tmp_path)
    ctx = _answer_ctx("好的 <meme:shy>")
    decorate_meme_ctx(ctx, MemeDecorator(MemeCatalog(tmp_path / "memes")))
    assert ctx.reply == "好的"
    assert ctx.media == [str(image)]
    assert ctx.meme_tag == "shy"


def test_decorate_meme_ctx_accepts_inline_tag(tmp_path: Path) -> None:
    image = _write_meme_workspace(tmp_path)
    ctx = _answer_ctx("快了 <meme:shy>\n\n马上到了")
    decorate_meme_ctx(ctx, MemeDecorator(MemeCatalog(tmp_path / "memes")))
    assert ctx.reply == "快了\n\n马上到了"
    assert ctx.media == [str(image)]
    assert ctx.meme_tag == "shy"


def test_decorate_meme_ctx_ignores_code_tag(tmp_path: Path) -> None:
    _ = _write_meme_workspace(tmp_path)
    ctx = _answer_ctx("应该是 `<meme:shy>`。\n\n<æm>shy</æm>")
    decorate_meme_ctx(ctx, MemeDecorator(MemeCatalog(tmp_path / "memes")))
    assert ctx.reply == "应该是 `<meme:shy>`。\n\n<æm>shy</æm>"
    assert ctx.media == []
    assert ctx.meme_tag is None


@pytest.mark.asyncio
async def test_v3_named_exports_run_complete_lifecycle_behavior(
    tmp_path: Path,
) -> None:
    image = _write_meme_workspace(tmp_path)
    composable = ComposablePlugin.from_module(_meme_plugin_module)
    assert composable.skill_roots == ("skills",)
    assert composable.dashboard_module == "dashboard.py"
    assert composable.workspace_roots == ("memes",)
    root = CompositionRoot("meme-v3")
    _ = await root.context.provide(CITATION_PROTOCOL_SERVICE, object())

    async def mount(ctx: Context) -> None:
        await apply(ctx, object())

    _ = await root.mount(
        mount,
        name="meme",
        inject=inject,
        runtime=PluginRuntime(
            plugin_id="meme",
            plugin_dir=Path(__file__).parents[1],
            data_dir=tmp_path / "plugin-data",
            workspace=tmp_path,
            config=object(),
            workspace_roots=("memes",),
        ),
    )
    receipt = root.receipt()
    assert receipt.ready is True
    assert receipt.writes == ()
    assert receipt.external_effects == ()

    prompt = _prompt_ctx()
    _ = await root.context.serial(PROMPT_RENDER_EVENT, prompt)
    assert [section.name for section in prompt.system_sections_bottom] == ["memes"]

    answer = _answer_ctx("好的 <meme:shy>")
    _ = await root.context.serial(AFTER_REASONING_PREPROCESS_EVENT, answer)
    assert answer.reply == "好的"
    assert answer.media == [str(image)]
    assert answer.meme_tag == "shy"

    await root.dispose()
    assert root.receipt().effects == ()
    assert root.topology_view().listeners == ()


@pytest.mark.asyncio
async def test_v3_candidate_reads_only_its_projected_meme_root(
    tmp_path: Path,
) -> None:
    formal_workspace = tmp_path / "formal-workspace"
    formal_image = _write_meme_workspace(formal_workspace)
    candidate_workspace = (
        tmp_path
        / "runtime"
        / "plugin-validation"
        / "meme"
        / "composition"
        / "attempt"
        / "workspace"
    )
    _ = shutil.copytree(
        formal_workspace / "memes",
        candidate_workspace / "memes",
    )
    candidate_image = candidate_workspace / "memes" / "shy" / "001.png"
    before = {
        path.relative_to(candidate_workspace).as_posix(): path.read_bytes()
        for path in candidate_workspace.rglob("*")
        if path.is_file()
    }
    root = CompositionRoot("meme-candidate")
    _ = await root.context.provide(CITATION_PROTOCOL_SERVICE, object())

    async def mount(ctx: Context) -> None:
        await apply(ctx, object())

    _ = await root.mount(
        mount,
        name="meme",
        inject=inject,
        runtime=PluginRuntime(
            plugin_id="meme",
            plugin_dir=Path(__file__).parents[1],
            data_dir=tmp_path / "candidate-data",
            workspace=candidate_workspace,
            config=object(),
            workspace_roots=("memes",),
        ),
    )
    prompt = _prompt_ctx()
    _ = await root.context.serial(PROMPT_RENDER_EVENT, prompt)
    answer = _answer_ctx("好的 <meme:shy>")
    _ = await root.context.serial(AFTER_REASONING_PREPROCESS_EVENT, answer)

    dashboard_module = importlib.import_module("test_meme_plugin.dashboard")
    app = FastAPI()
    dashboard_module.register(
        app,
        DashboardContext(
            plugin_id="meme",
            plugin_dir=Path(__file__).parents[1],
            data_root=tmp_path / "candidate-data",
            validation=True,
            _workspace_roots=(("memes", candidate_workspace / "memes"),),
        ),
    )
    candidate_route = next(
        route
        for route in app.routes
        if isinstance(route, APIRoute)
        and route.path == "/api/dashboard/meme/categories"
    )
    categories = candidate_route.endpoint()

    after = {
        path.relative_to(candidate_workspace).as_posix(): path.read_bytes()
        for path in candidate_workspace.rglob("*")
        if path.is_file()
    }
    assert before == after
    assert formal_image.read_bytes() == candidate_image.read_bytes()
    assert answer.media == [str(candidate_image)]
    assert categories["categories"][0]["tag"] == "shy"
    assert root.receipt().writes == ()
    assert root.receipt().external_effects == ()
    await root.dispose()


@pytest.mark.asyncio
async def test_v3_plugin_loads_package_and_dashboard_through_real_manager(
    tmp_path: Path,
) -> None:
    _ = _write_meme_workspace(tmp_path / "workspace")
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
    _ = shutil.copytree(
        Path(__file__).parents[1],
        plugin_home / "meme",
        ignore=_copy_ignore(),
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
    assert generation.instance.workspace_roots == ("memes",)
    assert snapshot.plugin_skill_index is not None
    assert "meme-manage" in snapshot.plugin_skill_index.records

    dashboard = PluginDashboardHost(
        workspace=workspace,
        memory_admin=object(),
        memory_store=object(),
        core_routes=(),
    )
    dashboard.prepare_snapshot(snapshot)
    assert len(snapshot.dashboard_bindings) == 1
    binding = snapshot.dashboard_bindings[0]
    assert isinstance(binding, DashboardBinding)
    assert binding.plugin_id == "meme"
    assert binding.validation is False
    assert binding.runtime_workspace == workspace.resolve()
    categories = next(
        route.endpoint
        for route in binding.routes
        if route.path == "/api/dashboard/meme/categories"
    )()
    assert categories["categories"][0]["tag"] == "shy"

    root = snapshot.composition_root
    assert root is not None
    await manager.terminate_all()
    assert root.receipt().effects == ()
    assert root.topology_view().listeners == ()


@pytest.mark.asyncio
async def test_citation_meme_cross_repository_v3_behavior(tmp_path: Path) -> None:
    raw_citation_root = os.environ.get("AKASHIC_CITATION_ROOT", "").strip()
    if not raw_citation_root:
        raise RuntimeError(
            "AKASHIC_CITATION_ROOT 必须指向 exact-commit Citation checkout"
        )
    citation_root = Path(raw_citation_root)

    workspace = tmp_path / "workspace"
    image = _write_meme_workspace(workspace)
    plugin_home = tmp_path / "plugins"
    _ = shutil.copytree(
        citation_root,
        plugin_home / "citation",
        ignore=_copy_ignore(),
    )
    _ = shutil.copytree(
        Path(__file__).parents[1],
        plugin_home / "meme",
        ignore=_copy_ignore(),
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

    prompt = _prompt_ctx()
    _ = await snapshot.composition_root.context.serial(PROMPT_RENDER_EVENT, prompt)
    answer = _answer_ctx("答复正文\n§cited:[mem_1]§ <meme:shy>")
    _ = await snapshot.composition_root.context.serial(
        AFTER_REASONING_PREPROCESS_EVENT,
        answer,
    )
    _ = await snapshot.composition_root.context.serial(
        AFTER_REASONING_CLEANUP_EVENT,
        answer,
    )

    assert [section.name for section in prompt.system_sections_bottom] == [
        "citation_protocol",
        "memes",
    ]
    assert answer.reply == "答复正文"
    assert answer.persist_assistant_metadata["cited_memory_ids"] == ["mem_1"]
    assert answer.media == [str(image)]
    assert answer.meme_tag == "shy"
    root = snapshot.composition_root
    await manager.terminate_all()
    assert root.receipt().effects == ()
    assert root.topology_view().listeners == ()
