from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from .plugin import _workspace
from .runtime import MemeCatalog

def register(app: FastAPI, plugin_dir: Path, workspace: Path) -> None:
    memes_dir = _workspace(plugin_dir, workspace) / "memes"
    catalog = MemeCatalog(memes_dir)

    @app.get("/api/dashboard/meme/categories")
    def get_meme_categories() -> dict[str, Any]:
        catalog._load()
        result: list[dict[str, Any]] = []
        for tag, cat in catalog._categories.items():
            cat_dir = memes_dir / tag
            count = 0
            if cat_dir.is_dir():
                count = len([
                    f for f in cat_dir.iterdir()
                    if f.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}
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
        cat_dir = memes_dir / tag
        images = []
        if cat_dir.is_dir():
            images = [
                f.name for f in cat_dir.iterdir()
                if f.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}
            ]
            images.sort()
        return {"tag": tag, "images": images}

    @app.delete("/api/dashboard/meme/categories/{tag}")
    def delete_meme_category(tag: str) -> dict[str, Any]:
        catalog._load()
        if tag not in catalog._categories:
            raise HTTPException(status_code=404, detail="Category not found")
        del catalog._categories[tag]
        
        manifest_path = memes_dir / "manifest.json"
        if manifest_path.exists():
            import json
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            if "categories" in data and tag in data["categories"]:
                del data["categories"][tag]
                manifest_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                
        import shutil
        cat_dir = memes_dir / tag
        if cat_dir.is_dir():
            shutil.rmtree(cat_dir, ignore_errors=True)
            
        return {"success": True}

    @app.delete("/api/dashboard/meme/media/{tag}/{filename}")
    def delete_meme_media(tag: str, filename: str) -> dict[str, Any]:
        safe_tag = os.path.basename(tag)
        safe_filename = os.path.basename(filename)
        file_path = memes_dir / safe_tag / safe_filename
        if not file_path.is_file():
            raise HTTPException(status_code=404, detail="Meme image not found")
        file_path.unlink()
        return {"success": True}

    @app.get("/api/dashboard/meme/media/{tag}/{filename}")
    def get_meme_media(tag: str, filename: str) -> Any:
        # Avoid path traversal attacks
        safe_tag = os.path.basename(tag)
        safe_filename = os.path.basename(filename)
        file_path = memes_dir / safe_tag / safe_filename
        if not file_path.is_file():
            raise HTTPException(status_code=404, detail="Meme image not found")
        return FileResponse(file_path)
