// dashboard_panel.tsx
import { useEffect, useState } from "react";
import { jsx, jsxs } from "react/jsx-runtime";
var dashboardRequest = null;
async function api(path, init) {
  if (!dashboardRequest) throw new Error("Meme \u5DE5\u4F5C\u53F0\u9762\u677F\u672A\u6FC0\u6D3B");
  const response = await dashboardRequest(path, init);
  const body = await response.json();
  if (!response.ok) throw new Error(String(body.detail ?? body.message ?? `HTTP ${response.status}`));
  return body;
}
async function media(path, signal) {
  if (!dashboardRequest) throw new Error("Meme \u5DE5\u4F5C\u53F0\u9762\u677F\u672A\u6FC0\u6D3B");
  const response = await dashboardRequest(path, { signal });
  if (!response.ok) throw new Error(`\u56FE\u7247\u8BFB\u53D6\u5931\u8D25\uFF1AHTTP ${response.status}`);
  return response.blob();
}
function MemeMain() {
  const [categories, setCategories] = useState([]);
  const [selectedTag, setSelectedTag] = useState(null);
  const [images, setImages] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const controller = new AbortController();
    void api("/api/dashboard/meme/categories", { signal: controller.signal }).then((data) => {
      if (controller.signal.aborted) return;
      setCategories(data.categories || []);
      if (data.categories?.length > 0) {
        setSelectedTag(data.categories[0].tag);
      }
      setLoading(false);
    }, (reason) => {
      if (controller.signal.aborted) return;
      setError(reason instanceof Error ? reason.message : "\u5206\u7C7B\u8BFB\u53D6\u5931\u8D25");
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
    void api(`/api/dashboard/meme/images/${selectedTag}`, { signal: controller.signal }).then((data) => {
      if (!controller.signal.aborted) setImages(data.images || []);
    }, (reason) => {
      if (!controller.signal.aborted) {
        setError(reason instanceof Error ? reason.message : "\u56FE\u7247\u8BFB\u53D6\u5931\u8D25");
      }
    });
    return () => controller.abort();
  }, [selectedTag]);
  return /* @__PURE__ */ jsxs("main", { className: "meme-dashboard", "aria-labelledby": "meme-dashboard-title", children: [
    /* @__PURE__ */ jsxs("nav", { className: "meme-dashboard__sidebar", "aria-label": "\u8868\u60C5\u5305\u5206\u7C7B", children: [
      /* @__PURE__ */ jsxs("div", { className: "meme-dashboard__sidebar-heading", children: [
        /* @__PURE__ */ jsx("h2", { children: "\u5206\u7C7B" }),
        /* @__PURE__ */ jsx("span", { children: categories.length })
      ] }),
      categories.map((c) => /* @__PURE__ */ jsxs("div", { className: "meme-category-row", children: [
        /* @__PURE__ */ jsxs(
          "button",
          {
            type: "button",
            className: `meme-category${selectedTag === c.tag ? " is-active" : ""}`,
            onClick: () => setSelectedTag(c.tag),
            "aria-current": selectedTag === c.tag ? "page" : void 0,
            disabled: !c.enabled,
            children: [
              /* @__PURE__ */ jsxs("span", { children: [
                /* @__PURE__ */ jsx("strong", { children: c.name || c.tag }),
                /* @__PURE__ */ jsx("small", { children: c.desc || c.tag })
              ] }),
              /* @__PURE__ */ jsx("b", { children: c.count })
            ]
          }
        ),
        /* @__PURE__ */ jsx(
          "button",
          {
            type: "button",
            className: "meme-delete",
            onClick: () => {
              if (confirm(`\u786E\u5B9A\u8981\u5220\u9664\u5206\u7C7B "${c.tag}" \u5417\uFF1F\u8FD9\u4F1A\u6C38\u4E45\u5220\u9664\u8BE5\u5206\u7C7B\u53CA\u5176\u6240\u6709\u56FE\u7247\uFF01`)) {
                void api(`/api/dashboard/meme/categories/${c.tag}`, { method: "DELETE" }).then(() => {
                  setCategories((categories2) => {
                    const next = categories2.filter((cat) => cat.tag !== c.tag);
                    if (selectedTag === c.tag) setSelectedTag(next.length > 0 ? next[0].tag : null);
                    return next;
                  });
                }).catch((err) => alert("\u5220\u9664\u5931\u8D25\uFF1A" + err.message));
              }
            },
            "aria-label": `\u5220\u9664\u5206\u7C7B ${c.tag}`,
            title: "\u5220\u9664\u5206\u7C7B",
            children: "\u2715"
          }
        )
      ] }, c.tag)),
      !loading && categories.length === 0 && /* @__PURE__ */ jsx("p", { className: "meme-dashboard__nav-empty", children: "\u8FD8\u6CA1\u6709\u5206\u7C7B\u3002" })
    ] }),
    /* @__PURE__ */ jsxs("section", { className: "meme-dashboard__gallery", children: [
      /* @__PURE__ */ jsxs("div", { className: "meme-dashboard__header", children: [
        /* @__PURE__ */ jsxs("div", { children: [
          /* @__PURE__ */ jsx("p", { children: "\u8868\u60C5\u5305\u5E93" }),
          /* @__PURE__ */ jsx("h1", { id: "meme-dashboard-title", children: selectedTag ? categories.find((c) => c.tag === selectedTag)?.name || selectedTag : "\u9009\u62E9\u4E00\u4E2A\u5206\u7C7B" }),
          /* @__PURE__ */ jsx("div", { className: "meme-dashboard__description", children: selectedTag ? categories.find((c) => c.tag === selectedTag)?.desc : "" })
        ] }),
        /* @__PURE__ */ jsxs("span", { className: "meme-dashboard__total", children: [
          images.length,
          " \u5F20\u56FE\u7247"
        ] })
      ] }),
      /* @__PURE__ */ jsxs("div", { className: "meme-grid", "aria-live": "polite", children: [
        images.map((img) => /* @__PURE__ */ jsxs("figure", { className: "meme-item", children: [
          /* @__PURE__ */ jsx(
            "button",
            {
              type: "button",
              className: "meme-item__delete",
              onClick: (e) => {
                e.stopPropagation();
                if (confirm(`\u786E\u5B9A\u8981\u5220\u9664\u56FE\u7247 "${img}" \u5417\uFF1F`)) {
                  void api(`/api/dashboard/meme/media/${selectedTag}/${img}`, { method: "DELETE" }).then(() => {
                    setImages((images2) => images2.filter((i) => i !== img));
                    setCategories((categories2) => categories2.map((c) => c.tag === selectedTag ? { ...c, count: c.count - 1 } : c));
                  }).catch((err) => alert("\u5220\u9664\u5931\u8D25\uFF1A" + err.message));
                }
              },
              "aria-label": `\u5220\u9664\u56FE\u7247 ${img}`,
              title: "\u5220\u9664\u56FE\u7247",
              children: "\u2715"
            }
          ),
          /* @__PURE__ */ jsx("div", { className: "meme-item__preview", children: /* @__PURE__ */ jsx(MemeImage, { tag: selectedTag, name: img }) }),
          /* @__PURE__ */ jsx("figcaption", { title: img, children: img })
        ] }, img)),
        loading && /* @__PURE__ */ jsx("div", { className: "meme-state", role: "status", children: "\u6B63\u5728\u8BFB\u53D6\u8868\u60C5\u5305\u5206\u7C7B\u2026" }),
        !loading && !error && images.length === 0 && selectedTag && /* @__PURE__ */ jsxs("div", { className: "meme-state", children: [
          /* @__PURE__ */ jsx("strong", { children: "\u8FD9\u4E2A\u5206\u7C7B\u8FD8\u6CA1\u6709\u56FE\u7247" }),
          /* @__PURE__ */ jsx("span", { children: "\u901A\u8FC7 Meme \u63D2\u4EF6\u5BFC\u5165\u56FE\u7247\u540E\u4F1A\u663E\u793A\u5728\u8FD9\u91CC\u3002" })
        ] }),
        error && /* @__PURE__ */ jsxs("div", { className: "meme-state is-error", role: "alert", children: [
          /* @__PURE__ */ jsx("strong", { children: "\u65E0\u6CD5\u52A0\u8F7D\u8868\u60C5\u5305" }),
          /* @__PURE__ */ jsx("span", { children: error })
        ] })
      ] })
    ] })
  ] });
}
function MemeImage({ tag, name }) {
  const [source, setSource] = useState(null);
  useEffect(() => {
    const controller = new AbortController();
    let objectUrl = null;
    void media(`/api/dashboard/meme/media/${tag}/${name}`, controller.signal).then((blob) => {
      objectUrl = URL.createObjectURL(blob);
      setSource(objectUrl);
    }, (reason) => {
      if (!controller.signal.aborted) console.error("Meme \u56FE\u7247\u8BFB\u53D6\u5931\u8D25", reason);
    });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [name, tag]);
  return /* @__PURE__ */ jsx("img", { src: source ?? void 0, alt: "", loading: "lazy" });
}
var panel = {
  id: "meme",
  label: "Meme \u8868\u60C5\u5305",
  viewLabel: "\u8868\u60C5\u5305",
  order: 50,
  layout: "workbench",
  rowKey: "id",
  columns: [],
  async getCount({ signal }) {
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
  Main: MemeMain
};
function activate(ctx) {
  dashboardRequest = ctx.http.request;
  const release = ctx.ui.inject("workbench.panels.v2", (mount) => mount.register(panel));
  return () => {
    release();
    dashboardRequest = null;
  };
}
export {
  activate
};
