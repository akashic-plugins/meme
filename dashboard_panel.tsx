/// <reference path="../../types/akashic-dashboard.d.ts" />
import { useEffect, useState } from "react";

// The Akashic Dashboard injects itself globally.
// We declare it here to satisfy TypeScript in our standalone build.
declare global {
  interface Window {
    AkashicDashboard: any;
  }
}

const { api } = window.AkashicDashboard;

interface Category {
  tag: string;
  name: string;
  desc: string;
  aliases: string[];
  enabled: boolean;
  count: number;
}

function MemeMain() {
  const [categories, setCategories] = useState<Category[]>([]);
  const [selectedTag, setSelectedTag] = useState<string | null>(null);
  const [images, setImages] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    void api("/api/dashboard/meme/categories").then((data: any) => {
      setCategories(data.categories || []);
      if (data.categories?.length > 0) {
        setSelectedTag(data.categories[0].tag);
      }
      setLoading(false);
    }, (reason: unknown) => {
      setError(reason instanceof Error ? reason.message : "分类读取失败");
      setLoading(false);
    });
  }, []);

  useEffect(() => {
    if (selectedTag) {
      void api(`/api/dashboard/meme/images/${selectedTag}`).then((data: any) => {
        setImages(data.images || []);
      }, (reason: unknown) => setError(reason instanceof Error ? reason.message : "图片读取失败"));
    } else {
      setImages([]);
    }
  }, [selectedTag]);

  return (
    <main className="meme-dashboard" aria-labelledby="meme-dashboard-title">
      <nav className="meme-dashboard__sidebar" aria-label="表情包分类">
        <div className="meme-dashboard__sidebar-heading">
          <h2>分类</h2>
          <span>{categories.length}</span>
        </div>
        {categories.map((c) => (
          <div key={c.tag} className="meme-category-row">
            <button
              type="button"
              className={`meme-category${selectedTag === c.tag ? " is-active" : ""}`}
              onClick={() => setSelectedTag(c.tag)}
              aria-current={selectedTag === c.tag ? "page" : undefined}
              disabled={!c.enabled}
            >
              <span><strong>{c.name || c.tag}</strong><small>{c.desc || c.tag}</small></span>
              <b>{c.count}</b>
            </button>
            <button
              type="button"
              className="meme-delete"
              onClick={() => {
                if (confirm(`确定要删除分类 "${c.tag}" 吗？这会永久删除该分类及其所有图片！`)) {
                  void api(`/api/dashboard/meme/categories/${c.tag}`, { method: "DELETE" }).then(() => {
                    setCategories(categories => {
                      const next = categories.filter(cat => cat.tag !== c.tag);
                      if (selectedTag === c.tag) setSelectedTag(next.length > 0 ? next[0].tag : null);
                      return next;
                    });
                  }).catch((err: Error) => alert("删除失败：" + err.message));
                }
              }}
              aria-label={`删除分类 ${c.tag}`}
              title="删除分类"
            >
              ✕
            </button>
          </div>
        ))}
        {!loading && categories.length === 0 && <p className="meme-dashboard__nav-empty">还没有分类。</p>}
      </nav>

      <section className="meme-dashboard__gallery">
        <div className="meme-dashboard__header">
          <div>
            <p>表情包库</p>
            <h1 id="meme-dashboard-title">
              {selectedTag ? categories.find((c) => c.tag === selectedTag)?.name || selectedTag : "选择一个分类"}
            </h1>
            <div className="meme-dashboard__description">
              {selectedTag ? categories.find((c) => c.tag === selectedTag)?.desc : ""}
            </div>
          </div>
          <span className="meme-dashboard__total">{images.length} 张图片</span>
        </div>

        <div className="meme-grid" aria-live="polite">
          {images.map(img => (
            <figure key={img} className="meme-item">
              <button
                type="button"
                className="meme-item__delete"
                onClick={(e) => {
                  e.stopPropagation();
                  if (confirm(`确定要删除图片 "${img}" 吗？`)) {
                    void api(`/api/dashboard/meme/media/${selectedTag}/${img}`, { method: "DELETE" }).then(() => {
                      setImages(images => images.filter(i => i !== img));
                      setCategories(categories => categories.map(c => c.tag === selectedTag ? { ...c, count: c.count - 1 } : c));
                    }).catch((err: any) => alert("删除失败：" + err.message));
                  }
                }}
                aria-label={`删除图片 ${img}`}
                title="删除图片"
              >
                ✕
              </button>
              <div className="meme-item__preview">
                <img src={`/api/dashboard/meme/media/${selectedTag}/${img}`} alt="" loading="lazy" />
              </div>
              <figcaption title={img}>
                {img}
              </figcaption>
            </figure>
          ))}
          {loading && <div className="meme-state" role="status">正在读取表情包分类…</div>}
          {!loading && !error && images.length === 0 && selectedTag && (
            <div className="meme-state">
              <strong>这个分类还没有图片</strong>
              <span>通过 Meme 插件导入图片后会显示在这里。</span>
            </div>
          )}
          {error && (
            <div className="meme-state is-error" role="alert">
              <strong>无法加载表情包</strong>
              <span>{error}</span>
            </div>
          )}
        </div>
      </section>
    </main>
  );
}

window.AkashicDashboard.registerPlugin({
  id: "meme",
  label: "Meme 表情包",
  viewLabel: "表情包",
  layout: "workbench",
  
  async getCount(): Promise<number | null> {
    try {
      const data = await api("/api/dashboard/meme/categories");
      let total = 0;
      for (const cat of data.categories || []) {
        total += cat.count;
      }
      return total;
    } catch {
      return null;
    }
  },

  async fetchPage() {
    return { items: [], total: 0 };
  },

  Main: MemeMain,
});
