[English](../README.md) · [العربية](README.ar.md) · [Español](README.es.md) · [Français](README.fr.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Tiếng Việt](README.vi.md) · [中文 (简体)](README.zh-Hans.md) · [中文（繁體）](README.zh-Hant.md) · [Deutsch](README.de.md) · [Русский](README.ru.md)

# Agentic Browser

一個本地優先的智能瀏覽器工作台，基於真實 Chrome/Chromium 和 Chrome DevTools Protocol。它提供網頁控制台、可點擊截圖視口、DOM 觀察、CLI，以及透過 `codex exec` 逐步決策的自動瀏覽能力。

## 快速開始

```bash
python3 -m pip install -r requirements.txt
./run-agentic-browser-vdesktop.sh start
```

打開 `http://127.0.0.1:8794`。

## 能力

- Webapp 和 CLI 控制同一個瀏覽器服務。
- 支援 headless、Xephyr、Xvfb 模式。
- 同時觀察截圖、DOM、連結、可見文字和安全策略。
- 阻止不安全的鏡像、下載、直接檔案 URL。
- 日誌寫入 `library/`。

完整文件請看 [主 README](../README.md)。

