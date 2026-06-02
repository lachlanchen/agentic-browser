[English](../README.md) · [العربية](README.ar.md) · [Español](README.es.md) · [Français](README.fr.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Tiếng Việt](README.vi.md) · [中文 (简体)](README.zh-Hans.md) · [中文（繁體）](README.zh-Hant.md) · [Deutsch](README.de.md) · [Русский](README.ru.md)

# Agentic Browser

一个本地优先的智能浏览器工作台，基于真实 Chrome/Chromium 和 Chrome DevTools Protocol。它提供网页控制台、可点击截图视口、DOM 观察、CLI，以及通过 `codex exec` 逐步决策的自动浏览能力。

## 快速开始

```bash
python3 -m pip install -r requirements.txt
./run-agentic-browser-vdesktop.sh start
```

打开 `http://127.0.0.1:8794`。

## 能力

- Webapp 和 CLI 控制同一个浏览器服务。
- 支持 headless、Xephyr、Xvfb 模式。
- 同时观察截图、DOM、链接、可见文本和安全策略。
- 阻止不安全的镜像、下载、直接文件 URL。
- 日志写入 `library/`。

完整文档请看 [主 README](../README.md)。

