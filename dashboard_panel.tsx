/// <reference path="../../types/akashic-dashboard.d.ts" />
import { useEffect, useState, useRef } from "react";

// The Akashic Dashboard injects itself globally.
// We declare it here to satisfy TypeScript in our standalone build.
declare global {
  interface Window {
    AkashicDashboard: any;
  }
}

const { api, ui } = window.AkashicDashboard;

interface Category {
  tag: string;
  name: string;
  desc: string;
  aliases: string[];
  enabled: boolean;
  count: number;
}

function MagicIndicator(props: { containerRef: React.RefObject<HTMLElement | null>; activeSelector: string; deps: any[] }) {
  const [style, setStyle] = useState<any>({ opacity: 0 });

  useEffect(() => {
    let animationFrameId: number;

    const update = () => {
      animationFrameId = requestAnimationFrame(() => {
        if (!props.containerRef.current) return;
        const activeEl = props.containerRef.current.querySelector(props.activeSelector) as HTMLElement;
        if (!activeEl) {
          setStyle((prev: any) => ({ ...prev, opacity: 0 }));
          return;
        }

        const top = activeEl.offsetTop;
        const left = activeEl.offsetLeft;
        const width = activeEl.offsetWidth;
        const height = activeEl.offsetHeight;
        const radius = window.getComputedStyle(activeEl).borderRadius;

        setStyle({
          opacity: 1,
          transform: `translate(${left}px, ${top}px)`,
          width: `${width}px`,
          height: `${height}px`,
          borderRadius: radius,
        });
      });
    };

    update();
    const observer = new MutationObserver(update);
    if (props.containerRef.current) {
      observer.observe(props.containerRef.current, { childList: true, subtree: true, attributes: true, attributeFilter: ['class'] });
    }
    window.addEventListener("resize", update);

    return () => {
      cancelAnimationFrame(animationFrameId);
      observer.disconnect();
      window.removeEventListener("resize", update);
    };
  }, props.deps);

  return <div className="magic-indicator" style={style} />;
}

function MemeMain() {
  const containerRef = useRef<HTMLDivElement>(null);
  const sidebarRef = useRef<HTMLDivElement>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [selectedTag, setSelectedTag] = useState<string | null>(null);
  const [images, setImages] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (containerRef && containerRef.current && containerRef.current.parentElement) {
      containerRef.current.parentElement.style.height = "100%";
      containerRef.current.parentElement.style.display = "flex";
      containerRef.current.parentElement.style.flexDirection = "column";
      
      const pane = containerRef.current.closest('.plugin-workbench-pane') as HTMLElement;
      if (pane) {
        pane.style.display = "flex";
        pane.style.flexDirection = "column";
      }
    }
  }, []);

  useEffect(() => {
    void api("/api/dashboard/meme/categories").then((data: any) => {
      setCategories(data.categories || []);
      if (data.categories?.length > 0) {
        setSelectedTag(data.categories[0].tag);
      }
    }, (reason: unknown) => setError(reason instanceof Error ? reason.message : "分类读取失败"));
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
    <div ref={containerRef} className="meme-dashboard">
      {/* Sidebar: Categories */}
      <div ref={sidebarRef} className="meme-dashboard__sidebar">
        <h3 className={ui.cx.label} style={{ marginBottom: "10px", paddingLeft: "10px" }}>分类</h3>
        <MagicIndicator containerRef={sidebarRef} activeSelector=".active" deps={[selectedTag, categories]} />
        {categories.map((c) => (
          <div key={c.tag} className="group" style={{ display: "flex", alignItems: "center", gap: "4px" }}>
            <button
              type="button"
              className={`session-item ${selectedTag === c.tag ? "active" : ""}`}
              style={{ display: "flex", flex: 1, justifyContent: "space-between", alignItems: "center", minWidth: 0, opacity: c.enabled ? 1 : 0.5 }}
              onClick={() => setSelectedTag(c.tag)}
            >
              <span style={{ fontWeight: "bold", overflow: "hidden", textOverflow: "ellipsis" }}>{c.tag}</span>
              <span className={ui.cx.badge(selectedTag === c.tag ? "accent" : "neutral", { dot: true })}>{c.count}</span>
            </button>
            <button
              type="button"
              className="opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition-opacity"
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
              style={{ minWidth: "40px", minHeight: "40px", padding: "0 4px", color: "var(--ak-color-status-error)" }}
              aria-label={`删除分类 ${c.tag}`}
              title="删除分类"
            >
              ✕
            </button>
          </div>
        ))}
      </div>

      {/* Main Area: Gallery */}
      <div className="meme-dashboard__gallery">
        <div className="meme-dashboard__header">
          <div>
            <h2 style={{ fontSize: "24px", fontWeight: "600", color: "var(--ak-color-text-primary)", marginBottom: "4px" }}>
              {selectedTag ? categories.find((c) => c.tag === selectedTag)?.name || selectedTag : "选择一个分类"}
            </h2>
            <div className={ui.cx.label} style={{ opacity: 0.7 }}>
              {selectedTag ? categories.find((c) => c.tag === selectedTag)?.desc : ""}
            </div>
          </div>
          <span className={ui.cx.badge("neutral")}>{images.length} 张图片</span>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: "20px", paddingBottom: "40px" }}>
          {images.map(img => (
            <div key={img} className={`${ui.cx.tile} group`} style={{ padding: "10px", display: "flex", flexDirection: "column", alignItems: "center", gap: "12px", transition: "transform 0.15s", cursor: "pointer", position: "relative" }} onMouseOver={(e) => (e.currentTarget.style.transform = "scale(1.02)")} onMouseOut={(e) => (e.currentTarget.style.transform = "scale(1)")}>
              <button
                type="button"
                className="opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition-opacity"
                style={{ position: "absolute", top: "4px", right: "4px", zIndex: 10, minWidth: "40px", minHeight: "40px", background: "var(--ak-color-bg-surface-low)", border: "1px solid var(--ak-color-border-default)", borderRadius: "4px", padding: "2px 6px", color: "var(--ak-color-status-error)" }}
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
              <div style={{ height: "160px", width: "100%", display: "flex", alignItems: "center", justifyContent: "center", backgroundColor: "var(--ak-color-bg-surface-low)", borderRadius: "8px", overflow: "hidden" }}>
                <img src={`/api/dashboard/meme/media/${selectedTag}/${img}`} alt={img} style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "contain" }} loading="lazy" />
              </div>
              <div className={ui.cx.mono} style={{ fontSize: "11px", wordBreak: "break-all", textAlign: "center", width: "100%", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {img}
              </div>
            </div>
          ))}
          {images.length === 0 && selectedTag && (
            <div style={{ padding: "40px", textAlign: "center", color: "var(--ak-color-text-muted)", gridColumn: "1 / -1" }}>
              该类别下暂无表情包图片
            </div>
          )}
          {error && (
            <div role="alert" style={{ padding: "20px", color: "var(--ak-color-status-error)", gridColumn: "1 / -1" }}>
              表情包界面加载失败：{error}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

window.AkashicDashboard.registerPlugin({
  id: "meme",
  label: "Meme 表情包",
  viewLabel: "meme",
  layout: "workbench", // This uses the full-page layout without the default table
  
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
