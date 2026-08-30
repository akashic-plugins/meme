from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from agent.plugin_composition import DashboardContext
from .runtime import MemeCatalog


def register(app: FastAPI, context: DashboardContext) -> None:
    memes_dir = context.workspace_root("memes")
    catalog = MemeCatalog(memes_dir)

    @app.get("/api/dashboard/meme/categories")
    def get_meme_categories() -> dict[str, Any]:
        catalog._load()
        result: list[dict[str, Any]] = []
        for tag, cat in catalog._categories.items():
            cat_dir = _safe_path(memes_dir, ((tag, "category"),))
            count = 0
            if cat_dir.is_dir():
                count = len([
                    f for f in cat_dir.iterdir()
                    if not f.is_symlink()
                    and f.is_file()
                    and f.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}
                ])
            result.append({
                "tag": tag,
                "name": cat.name,
                "desc": cat.desc,
                "aliases": cat.aliases,
                "enabled": cat.enabled,
                "count": count
            })
        result.sort(key=lambda x: x["tag"])
        return {"categories": result}

    @app.get("/api/dashboard/meme/images/{tag}")
    def get_meme_images(tag: str) -> dict[str, Any]:
        cat_dir = _safe_path(memes_dir, ((tag, "category"),))
        images = []
        if cat_dir.is_dir():
            images = [
                f.name for f in cat_dir.iterdir()
                if not f.is_symlink()
                and f.is_file()
                and f.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}
            ]
            images.sort()
        return {"tag": tag, "images": images}

    @app.delete("/api/dashboard/meme/categories/{tag}")
    def delete_meme_category(tag: str) -> dict[str, Any]:
        return _remove_category(memes_dir, tag, catalog)

    @app.delete("/api/dashboard/meme/media/{tag}/{filename}")
    def delete_meme_media(tag: str, filename: str) -> dict[str, Any]:
        file_path = _safe_path(
            memes_dir,
            ((tag, "category"), (filename, "filename")),
        )
        if not file_path.is_file():
            raise HTTPException(status_code=404, detail="Meme image not found")
        recovery_id = _move_to_recovery(memes_dir, file_path, "image")
        return {"success": True, "recovery_id": recovery_id}

    @app.get("/api/dashboard/meme/media/{tag}/{filename}")
    def get_meme_media(tag: str, filename: str) -> Any:
        file_path = _safe_path(
            memes_dir,
            ((tag, "category"), (filename, "filename")),
        )
        if not file_path.is_file():
            raise HTTPException(status_code=404, detail="Meme image not found")
        return FileResponse(file_path)


def _safe_segment(value: str, label: str) -> str:
    if (
        not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or "\x00" in value
        or os.path.basename(value) != value
    ):
        raise HTTPException(status_code=422, detail=f"Invalid {label}")
    return value


def _safe_path(root: Path, segments: tuple[tuple[str, str], ...]) -> Path:
    base = root.resolve(strict=False)
    candidate = base
    for value, label in segments:
        candidate /= _safe_segment(value, label)
        if candidate.is_symlink():
            raise HTTPException(status_code=422, detail=f"Invalid {label}")
    if not candidate.resolve(strict=False).is_relative_to(base):
        raise HTTPException(status_code=422, detail="Path escapes meme workspace")
    return candidate


def _move_to_recovery(memes_dir: Path, source: Path, kind: str) -> str:
    recovery_id = f"{kind}-{uuid4().hex}"
    recovery_dir = _safe_path(memes_dir, ((".trash", "recovery root"),)) / recovery_id
    try:
        recovery_dir.mkdir(parents=True, exist_ok=False)
        source.replace(recovery_dir / source.name)
    except OSError as error:
        raise HTTPException(status_code=500, detail=f"Failed to preserve deleted {kind}") from error
    return recovery_id


def _remove_category(
    memes_dir: Path,
    tag: str,
    catalog: MemeCatalog,
) -> dict[str, object]:
    manifest_path = _safe_path(memes_dir, (("manifest.json", "manifest"),))
    category_dir = _safe_path(memes_dir, ((tag, "category"),))
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
    except (OSError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=500, detail="Meme manifest is unreadable") from error
    categories = manifest.get("categories") if isinstance(manifest, dict) else None
    if not isinstance(categories, dict):
        raise HTTPException(status_code=500, detail="Meme manifest categories are invalid")
    if tag not in categories:
        raise HTTPException(status_code=404, detail="Category not found")

    recovery_id = f"category-{uuid4().hex}"
    recovery_dir = _safe_path(memes_dir, ((".trash", "recovery root"),)) / recovery_id
    moved_category: Path | None = None
    try:
        recovery_dir.mkdir(parents=True, exist_ok=False)
        (recovery_dir / "manifest.json").write_bytes(manifest_bytes)
        if category_dir.exists():
            moved_category = recovery_dir / tag
            category_dir.replace(moved_category)
        del categories[tag]
        _write_manifest(manifest_path, manifest)
    except OSError as error:
        if moved_category is not None and moved_category.exists():
            moved_category.replace(category_dir)
        raise HTTPException(status_code=500, detail="Failed to preserve deleted category") from error
    catalog._manifest_mtime = -1.0
    return {"success": True, "recovery_id": recovery_id}


def _write_manifest(path: Path, manifest: dict[str, object]) -> None:
    staging = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with staging.open("w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staging, path)
    finally:
        staging.unlink(missing_ok=True)
