from __future__ import annotations

import json
import importlib.util
from datetime import datetime, timezone
from types import SimpleNamespace
from pathlib import Path
import sys

import pytest

from agent.core.response_parser import ResponseMetadata
from agent.lifecycle.types import AfterReasoningCtx, PromptRenderCtx
from agent.plugins.context import PluginContext, PluginKVStore
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
    result = MemeDecorator(MemeCatalog(tmp_path / "memes")).decorate("好的", meme_tag="shy")
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
