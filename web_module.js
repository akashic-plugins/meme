export function activate(ctx) {
  return ctx.ui.inject("workbench.panels.v1", (mount) => mount.register({
    id: "meme",
    label: "Meme 表情包",
    order: 40,
    render(host) {
      const panel = document.createElement("section");
      panel.className = "meme-dashboard";
      panel.innerHTML = `<nav class="meme-dashboard__sidebar" aria-label="表情包分类"><div class="meme-dashboard__sidebar-heading"><h2>分类</h2><span data-category-count>0</span></div><div data-categories></div></nav><section class="meme-dashboard__gallery"><div class="meme-dashboard__header"><div><p>表情包库</p><h1 data-title>选择一个分类</h1><div class="meme-dashboard__description" data-description></div></div><span class="meme-dashboard__total" data-total>0 张图片</span></div><p data-status role="status" aria-live="polite"></p><div class="meme-grid" data-gallery></div></section>`;
      host.replaceChildren(panel);
      const categoriesHost = panel.querySelector("[data-categories]");
      const categoryCount = panel.querySelector("[data-category-count]");
      const title = panel.querySelector("[data-title]");
      const description = panel.querySelector("[data-description]");
      const total = panel.querySelector("[data-total]");
      const status = panel.querySelector("[data-status]");
      const gallery = panel.querySelector("[data-gallery]");
      let categories = [];
      let selectedTag = "";
      let catalogRequest = new AbortController();
      let imageRequest = new AbortController();
      let mutationRequest = new AbortController();
      let observer = null;
      let objectUrls = [];
      let disposed = false;

      const clearImages = () => {
        imageRequest.abort();
        imageRequest = new AbortController();
        observer?.disconnect();
        observer = null;
        for (const url of objectUrls) URL.revokeObjectURL(url);
        objectUrls = [];
        gallery.replaceChildren();
      };

      const loadCategories = async (preferredTag = selectedTag) => {
        catalogRequest.abort();
        catalogRequest = new AbortController();
        const activeRequest = catalogRequest;
        status.textContent = "正在读取表情包分类…";
        try {
          const result = await json(ctx, "/api/dashboard/meme/categories", {}, activeRequest.signal);
          if (disposed || activeRequest.signal.aborted) return;
          categories = Array.isArray(result.categories) ? result.categories : [];
          selectedTag = categories.some((item) => item.tag === preferredTag)
            ? preferredTag
            : String(categories[0]?.tag ?? "");
          renderCategories();
          if (selectedTag) await loadImages(selectedTag);
          else {
            clearImages();
            title.textContent = "选择一个分类";
            total.textContent = "0 张图片";
            status.textContent = "还没有表情包分类。";
          }
        } catch (reason) {
          if (!activeRequest.signal.aborted) showError(status, reason);
        }
      };

      const renderCategories = () => {
        categoryCount.textContent = String(categories.length);
        categoriesHost.replaceChildren();
        for (const category of categories) {
          const row = document.createElement("div");
          row.className = "meme-category-row";
          const choose = document.createElement("button");
          choose.type = "button";
          choose.className = `meme-category${selectedTag === category.tag ? " is-active" : ""}`;
          choose.disabled = !category.enabled;
          choose.setAttribute("aria-current", selectedTag === category.tag ? "page" : "false");
          choose.innerHTML = `<span><strong>${escapeHtml(category.name || category.tag)}</strong><small>${escapeHtml(category.desc || category.tag)}</small></span><b>${Number(category.count || 0)}</b>`;
          choose.addEventListener("click", () => {
            selectedTag = category.tag;
            renderCategories();
            void loadImages(category.tag);
          });
          const remove = document.createElement("button");
          remove.type = "button";
          remove.className = "meme-delete";
          remove.setAttribute("aria-label", `删除分类 ${category.tag}`);
          remove.textContent = "×";
          remove.addEventListener("click", () => void deleteCategory(category));
          row.append(choose, remove);
          categoriesHost.append(row);
        }
      };

      const loadImages = async (tag) => {
        clearImages();
        const activeRequest = imageRequest;
        const category = categories.find((item) => item.tag === tag);
        title.textContent = category?.name || tag;
        description.textContent = category?.desc || "";
        status.textContent = "正在读取图片…";
        try {
          const result = await json(ctx, `/api/dashboard/meme/images/${encodeURIComponent(tag)}`, {}, activeRequest.signal);
          if (disposed || activeRequest.signal.aborted || tag !== selectedTag) return;
          const images = Array.isArray(result.images) ? result.images : [];
          total.textContent = `${images.length} 张图片`;
          status.textContent = images.length ? "" : "这个分类还没有图片。";
          observer = new IntersectionObserver((entries) => {
            for (const entry of entries) {
              if (!entry.isIntersecting) continue;
              observer?.unobserve(entry.target);
              void loadImage(entry.target, tag, activeRequest.signal);
            }
          }, {rootMargin: "160px"});
          for (const filename of images) {
            const figure = document.createElement("figure");
            figure.className = "meme-item";
            figure.dataset.filename = filename;
            figure.innerHTML = `<button type="button" class="meme-item__delete" aria-label="删除图片 ${escapeHtml(filename)}">×</button><div class="meme-item__preview"><span>载入中</span></div><figcaption title="${escapeHtml(filename)}">${escapeHtml(filename)}</figcaption>`;
            figure.querySelector("button").addEventListener("click", () => void deleteImage(tag, filename));
            gallery.append(figure);
            observer.observe(figure);
          }
        } catch (reason) {
          if (!activeRequest.signal.aborted) showError(status, reason);
        }
      };

      const loadImage = async (figure, tag, signal) => {
        try {
          const response = await ctx.http.request(`/api/dashboard/meme/media/${encodeURIComponent(tag)}/${encodeURIComponent(figure.dataset.filename)}`, {signal});
          if (!response.ok) throw new Error(`图片读取失败: HTTP ${response.status}`);
          const url = URL.createObjectURL(await response.blob());
          if (disposed || signal.aborted || tag !== selectedTag) {
            URL.revokeObjectURL(url);
            return;
          }
          objectUrls.push(url);
          const image = document.createElement("img");
          image.src = url;
          image.alt = "";
          figure.querySelector(".meme-item__preview").replaceChildren(image);
        } catch (reason) {
          if (!signal.aborted) figure.querySelector(".meme-item__preview").textContent = reason instanceof Error ? reason.message : String(reason);
        }
      };

      const deleteCategory = async (category) => {
        if (!window.confirm(`确定删除分类“${category.tag}”及其中全部图片吗？此操作无法撤销。`)) return;
        mutationRequest.abort();
        mutationRequest = new AbortController();
        const activeRequest = mutationRequest;
        try {
          await json(ctx, `/api/dashboard/meme/categories/${encodeURIComponent(category.tag)}`, {method: "DELETE"}, activeRequest.signal);
          if (disposed || activeRequest.signal.aborted) return;
          await loadCategories();
        } catch (reason) {
          if (!activeRequest.signal.aborted) showError(status, reason);
        }
      };

      const deleteImage = async (tag, filename) => {
        if (!window.confirm(`确定删除图片“${filename}”吗？此操作无法撤销。`)) return;
        mutationRequest.abort();
        mutationRequest = new AbortController();
        const activeRequest = mutationRequest;
        try {
          await json(ctx, `/api/dashboard/meme/media/${encodeURIComponent(tag)}/${encodeURIComponent(filename)}`, {method: "DELETE"}, activeRequest.signal);
          if (disposed || activeRequest.signal.aborted || tag !== selectedTag) return;
          const category = categories.find((item) => item.tag === tag);
          if (category) category.count = Math.max(0, Number(category.count) - 1);
          renderCategories();
          await loadImages(tag);
        } catch (reason) {
          if (!activeRequest.signal.aborted) showError(status, reason);
        }
      };

      void loadCategories();
      return () => {
        disposed = true;
        catalogRequest.abort();
        mutationRequest.abort();
        clearImages();
        host.replaceChildren();
      };
    },
  }));
}

async function json(ctx, path, init, signal) {
  const response = await ctx.http.request(path, {...init, signal});
  const body = await response.json();
  if (!response.ok) throw new Error(body?.detail || body?.message || `HTTP ${response.status}`);
  return body;
}

function showError(target, reason) {
  target.setAttribute("role", "alert");
  target.textContent = reason instanceof Error ? reason.message : String(reason);
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"})[character]);
}
