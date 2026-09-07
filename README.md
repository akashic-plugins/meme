# meme 插件

表情包发送能力。插件从 workspace 的 `memes/` 读取启用类别，向普通 Content 服务注册动态提示与文本解析器，并把选中的图片导入为通用 `artifact_ref`。

## 行为

- 提示模型在回复中使用 `<meme:tag>`。
- 只解析非 Markdown 代码区间中的 Meme 标记，每条回复至多选择一张图片。
- 类别、随机选择方式和结果保存到 `Message.metadata.meme`。
- 图片在消息提交前经 Core Artifact 服务导入；Delivery 重试复用同一 artifact。
- 合法类别没有可用图片时清理标记，返回 `status=missing`，不伪造附件。
- manifest、类别目录、Dashboard、管理 Skill 和 Web 展示继续由 Meme 拥有。

Meme 不依赖 Citation。两者可以单独安装，也不依赖注册顺序。

## 配置

表情包资源放在 workspace 的 `memes/` 目录中：

```json
{
  "categories": {
    "happy": {"desc": "开心", "aliases": ["高兴"], "enabled": true}
  }
}
```

图片放在对应类别目录中，支持 `.png`、`.jpg`、`.jpeg`、`.gif` 和 `.webp`。
