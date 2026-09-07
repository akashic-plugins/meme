from __future__ import annotations

import importlib
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.routing import APIRoute

from agent.plugin_composition.artifacts import ARTIFACT_IMPORT
from agent.plugins.composable import ComposablePlugin
from agent.plugins.dashboard_host import DashboardBinding, PluginDashboardHost
from agent.plugins.manager import PluginManager
from agent.plugins.snapshot import bind_runtime_snapshot, reset_runtime_snapshot
from agent.plugins.static_manifest import load_static_plugin_manifest
from bus.event_bus import EventBus
from infra.channels.artifacts import ChannelAttachmentArtifactStore
from plugins.content import plugin as content_module
from plugins.content.plugin import CONTENT
from session.artifact_store import ArtifactStore
from session.log import MessageLog
from session.message import Output
from session.message_codec import json_value
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


meme_module = _load_meme_plugin_module()


def _copy_ignore():
    return shutil.ignore_patterns(".git", ".pytest_cache", "__pycache__")


def _write_manifest(root: Path, categories: dict[str, object]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "manifest.json"
    path.write_text(
        json.dumps({"categories": categories}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def _write_image(root: Path, category: str, name: str = "001.png") -> Path:
    directory = root / category
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    return path


def test_static_manifest_preserves_package_contributions() -> None:
    manifest = load_static_plugin_manifest(Path(meme_module.__file__).parent)
    plugin = ComposablePlugin.from_module(meme_module)
    assert manifest.name == meme_module.name == "meme"
    assert manifest.version == meme_module.version == "2.0.0"
    assert plugin.inject == (CONTENT, ARTIFACT_IMPORT)
    assert plugin.skill_roots == ("skills",)
    assert plugin.dashboard_module == "dashboard.py"
    assert plugin.workspace_roots == ("memes",)


def test_catalog_and_decorator_keep_category_selection(tmp_path: Path) -> None:
    memes = tmp_path / "memes"
    image = _write_image(memes, "shy")
    _write_manifest(
        memes,
        {"shy": {"desc": "害羞", "aliases": ["脸红"], "enabled": True}},
    )
    catalog = MemeCatalog(memes)
    snapshot = catalog.snapshot()
    assert "<meme:shy>" in (snapshot.build_prompt_block() or "")
    result = MemeDecorator(snapshot).decorate("好的", meme_tag="shy")
    assert result.content == "好的"
    assert result.media == [str(image)]
    assert result.tag == "shy"


def test_invalid_manifest_is_not_cached_as_an_empty_catalog(tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path, {"shy": {"desc": "害羞"}})
    catalog = MemeCatalog(tmp_path)
    assert catalog.snapshot().categories
    manifest.write_text("{broken")
    for _ in range(2):
        with pytest.raises(json.JSONDecodeError):
            catalog.snapshot()


def test_catalog_rejects_images_linked_outside_the_material_root(
    tmp_path: Path,
) -> None:
    memes = tmp_path / "memes"
    _write_manifest(memes, {"shy": {"desc": "害羞"}})
    category = memes / "shy"
    category.mkdir()
    outside = tmp_path / "private.png"
    outside.write_bytes(b"private")
    (category / "linked.png").symlink_to(outside)
    with pytest.raises(ValueError, match="素材根目录之外"):
        MemeCatalog(memes).snapshot()
    assert outside.read_bytes() == b"private"


def _dashboard_route(tmp_path: Path, path: str, method: str):
    dashboard_module = importlib.import_module("test_meme_plugin.dashboard")
    app = FastAPI()
    dashboard_module.register(
        app,
        __import__(
            "agent.plugin_composition", fromlist=["DashboardContext"]
        ).DashboardContext(
            plugin_id="meme",
            plugin_dir=Path(__file__).parents[1],
            data_root=tmp_path / "data",
            validation=True,
            _workspace_roots=(("memes", tmp_path / "memes"),),
        ),
    )
    return next(
        route
        for route in app.routes
        if isinstance(route, APIRoute)
        and route.path == path
        and method in route.methods
    )


def test_dashboard_rejects_path_traversal_and_keeps_delete_recovery(
    tmp_path: Path,
) -> None:
    memes = tmp_path / "memes"
    image = _write_image(memes, "shy")
    _write_manifest(memes, {"shy": {"desc": "害羞", "enabled": True}})
    media = _dashboard_route(
        tmp_path,
        "/api/dashboard/meme/media/{tag}/{filename}",
        "GET",
    )
    with pytest.raises(HTTPException) as raised:
        media.endpoint("..", "secret.png")
    assert raised.value.status_code == 422

    delete = _dashboard_route(
        tmp_path,
        "/api/dashboard/meme/media/{tag}/{filename}",
        "DELETE",
    )
    receipt = delete.endpoint("shy", "001.png")
    assert not image.exists()
    recovered = memes / ".trash" / receipt["recovery_id"] / "001.png"
    assert recovered.read_bytes() == b"\x89PNG\r\n\x1a\nfixture"


def test_dashboard_rejects_media_symlink(tmp_path: Path) -> None:
    memes = tmp_path / "memes"
    image = _write_image(memes, "shy")
    _write_manifest(memes, {"shy": {"desc": "害羞", "enabled": True}})
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"secret")
    image.unlink()
    image.symlink_to(secret)
    media = _dashboard_route(
        tmp_path,
        "/api/dashboard/meme/media/{tag}/{filename}",
        "GET",
    )
    with pytest.raises(HTTPException) as raised:
        media.endpoint("shy", "001.png")
    assert raised.value.status_code == 422


def test_category_delete_restores_when_manifest_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memes = tmp_path / "memes"
    image = _write_image(memes, "shy")
    _write_manifest(memes, {"shy": {"desc": "害羞", "enabled": True}})
    dashboard_module = importlib.import_module("test_meme_plugin.dashboard")

    def fail_write(*_args) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(dashboard_module, "_write_manifest", fail_write)
    delete = _dashboard_route(
        tmp_path,
        "/api/dashboard/meme/categories/{tag}",
        "DELETE",
    )
    with pytest.raises(HTTPException, match="Failed to preserve deleted category"):
        delete.endpoint("shy")
    assert image.is_file()
    manifest = json.loads((memes / "manifest.json").read_text())
    assert "shy" in manifest["categories"]


@pytest.mark.asyncio
async def test_real_manager_content_service_freezes_each_catalog_and_artifact(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    memes = workspace / "memes"
    shy = _write_image(memes, "shy")
    manifest = _write_manifest(
        memes,
        {"shy": {"desc": "害羞", "enabled": True}},
    )
    plugin_home = tmp_path / "plugins"
    core_plugins = Path(content_module.__file__).parents[1]
    shutil.copytree(core_plugins / "content", plugin_home / "content")
    shutil.copytree(
        Path(__file__).parents[1],
        plugin_home / "meme",
        ignore=_copy_ignore(),
    )
    log = MessageLog(workspace / "sessions.db")
    records = ArtifactStore(workspace / "sessions.db")
    physical = ChannelAttachmentArtifactStore(
        workspace=workspace,
        metadata_store=records,
    )
    manager = PluginManager(
        plugin_dirs=[plugin_home],
        event_bus=EventBus(),
        workspace=workspace,
        message_log=log,
        channel_attachment_store=physical,
    )
    await manager.load_all()
    snapshot = manager.current_snapshot
    assert snapshot is not None and snapshot.composition_root is not None
    generation = manager.generation("meme")
    assert generation is not None
    assert isinstance(generation.instance, ComposablePlugin)
    assert snapshot.composition_topology is not None
    assert snapshot.composition_topology.listeners == ()

    lease = manager._snapshot_store.lease()  # pyright: ignore[reportPrivateUsage]
    token = bind_runtime_snapshot(lease)
    try:
        content = snapshot.composition_root.context.require(CONTENT)
        async with content.bind() as old_view:
            assert "<meme:shy>" in old_view.prompts[0]
            happy = _write_image(memes, "happy")
            _write_manifest(
                memes,
                {"happy": {"desc": "开心", "enabled": True}},
            )
            changed = manifest.stat().st_mtime + 2
            os.utime(manifest, (changed, changed))
            assert "<meme:shy>" in old_view.prompts[0]
            parts, metadata = await old_view.decode("好的 <meme:shy>")
            artifact_ids = tuple(
                str(part.value) for part in parts if part.kind == "artifact_ref"
            )
            assert len(artifact_ids) == 1
            assert json_value(metadata["meme"]) == {
                "version": 1,
                "category": "shy",
                "selection": "random",
                "status": "selected",
            }
            ref = physical.resolve_refs(artifact_ids)[0]
            assert ref.sha256
            assert shy.read_bytes() == b"\x89PNG\r\n\x1a\nfixture"
            writer = log.writer(
                "session",
                author="model",
                source="conversation",
                body_types=(Output,),
                content=old_view.checks,
                check_metadata=old_view.check_metadata,
            )
            saved = writer.append(
                "reply",
                Output(parts, "complete"),
                metadata=metadata,
            )
            assert json_value(saved.metadata)["meme"]["category"] == "shy"
            assert saved.body.parts[-1].kind == "artifact_ref"

        async with content.bind() as new_view:
            assert "- happy: 开心" in new_view.prompts[0]
            assert "- shy: 害羞" not in new_view.prompts[0]
            literal = "这里的 <meme:happy> 是格式说明，不是发送请求。"
            literal_parts, literal_metadata = await new_view.decode(literal)
            assert "".join(str(part.value) for part in literal_parts) == literal
            assert not literal_metadata
            parts, metadata = await new_view.decode(
                "`示例 <meme:happy>`\n真的 <meme:happy>"
            )
            assert any(part.kind == "artifact_ref" for part in parts)
            assert json_value(metadata["meme"])["category"] == "happy"
            assert happy.read_bytes() == b"\x89PNG\r\n\x1a\nfixture"

            missing_parts, missing = await new_view.decode("试试 <meme:absent>")
            assert not any(part.kind == "artifact_ref" for part in missing_parts)
            assert json_value(missing["meme"])["status"] == "missing"
    finally:
        reset_runtime_snapshot(token)
        await lease.release()
        root = snapshot.composition_root
        await manager.terminate_all()
        records.close()
        log.close()
        assert root.receipt().effects == ()


@pytest.mark.asyncio
async def test_real_manager_keeps_dashboard_and_skill_contributions(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    memes = workspace / "memes"
    _write_image(memes, "shy")
    _write_manifest(memes, {"shy": {"desc": "害羞", "enabled": True}})
    plugin_home = tmp_path / "plugins"
    core_plugins = Path(content_module.__file__).parents[1]
    shutil.copytree(core_plugins / "content", plugin_home / "content")
    shutil.copytree(
        Path(__file__).parents[1],
        plugin_home / "meme",
        ignore=_copy_ignore(),
    )
    log = MessageLog(workspace / "sessions.db")
    records = ArtifactStore(workspace / "sessions.db")
    manager = PluginManager(
        plugin_dirs=[plugin_home],
        event_bus=EventBus(),
        workspace=workspace,
        message_log=log,
        channel_attachment_store=ChannelAttachmentArtifactStore(
            workspace=workspace,
            metadata_store=records,
        ),
    )
    await manager.load_all()
    snapshot = manager.current_snapshot
    assert snapshot is not None
    assert snapshot.plugin_skill_index is not None
    assert "meme-manage" in snapshot.plugin_skill_index.records
    dashboard = PluginDashboardHost(core_routes=())
    dashboard.prepare_snapshot(snapshot)
    assert len(snapshot.dashboard_bindings) == 1
    binding = snapshot.dashboard_bindings[0]
    assert isinstance(binding, DashboardBinding)
    categories = next(
        route.endpoint
        for route in binding.routes
        if route.path == "/api/dashboard/meme/categories"
    )()
    assert categories["categories"][0]["tag"] == "shy"
    await manager.terminate_all()
    records.close()
    log.close()
