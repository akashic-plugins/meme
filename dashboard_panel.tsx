import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./dashboard_panel.css";
import type { WebHostContextV1, WebUiDisposer } from "@akashic/web-ui-v1";
import type { WorkbenchPanelEntry } from "@akashic/workbench-ui-v2";

let dashboardRequest: WebHostContextV1["http"]["request"] | null = null;

async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  if (!dashboardRequest) throw new Error("Meme 工作台面板未激活");
  const response = await dashboardRequest(path, init);
  const body = await response.json() as T & { detail?: unknown; message?: unknown };
  if (!response.ok) throw new Error(String(body.detail ?? body.message ?? `HTTP ${response.status}`));
  return body;
}

async function media(path: string, signal: AbortSignal): Promise<Blob> {
  if (!dashboardRequest) throw new Error("Meme 工作台面板未激活");
  const response = await dashboardRequest(path, { signal });
  if (!response.ok) throw new Error(`图片读取失败：HTTP ${response.status}`);
  return response.blob();
}

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
    const controller = new AbortController();
    void api("/api/dashboard/meme/categories", { signal: controller.signal }).then((data: any) => {
      if (controller.signal.aborted) return;
      setCategories(data.categories || []);
      if (data.categories?.length > 0) {
        setSelectedTag(data.categories[0].tag);
      }
      setLoading(false);
    }, (reason: unknown) => {
      if (controller.signal.aborted) return;
      setError(reason instanceof Error ? reason.message : "分类读取失败");
      setLoading(false);
    });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!selectedTag) {
      setImages([]);
      return;
    }
    const controller = new AbortController();
    setImages([]);
    setError(null);
    void api(`/api/dashboard/meme/images/${selectedTag}`, { signal: controller.signal }).then((data: any) => {
      if (!controller.signal.aborted) setImages(data.images || []);
    }, (reason: unknown) => {
      if (!controller.signal.aborted) {
        setError(reason instanceof Error ? reason.message : "图片读取失败");
      }
    });
    return () => controller.abort();
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
              <div className="meme-item__preview"><MemeImage tag={selectedTag!} name={img} /></div>
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

function MemeImage({ tag, name }: { tag: string; name: string }) {
  const [source, setSource] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let objectUrl: string | null = null;
    void media(`/api/dashboard/meme/media/${tag}/${name}`, controller.signal).then((blob) => {
      objectUrl = URL.createObjectURL(blob);
      setSource(objectUrl);
    }, (reason: unknown) => {
      if (!controller.signal.aborted) console.error("Meme 图片读取失败", reason);
    });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [name, tag]);

  return <img src={source ?? undefined} alt="" loading="lazy" />;
}

const panel = {
  id: "meme",
  label: "Meme 表情包",
  viewLabel: "表情包",
  order: 50,
  layout: "workbench",
  rowKey: "id",
  columns: [],
  
  async getCount({ signal }: { signal: AbortSignal }): Promise<number | null> {
    try {
      const data = await api("/api/dashboard/meme/categories", { signal });
      let total = 0;
      for (const cat of data.categories || []) {
        total += cat.count;
      }
      return total;
    } catch (error) {
      if (signal.aborted) throw error;
      return null;
    }
  },

  async fetchPage() {
    return { items: [], total: 0 };
  },

  renderMain(container: HTMLElement): WebUiDisposer {
    const root = createRoot(container);
    root.render(<MemeMain />);
    return () => root.unmount();
  },
} satisfies WorkbenchPanelEntry;

export function activate(ctx: WebHostContextV1): WebUiDisposer {
  dashboardRequest = ctx.http.request;
  const release = ctx.ui.inject("workbench.panels.v2", (mount) => mount.register(panel));
  return () => {
    release();
    dashboardRequest = null;
  };
}
