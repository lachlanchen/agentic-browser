[English](../README.md) · [العربية](README.ar.md) · [Español](README.es.md) · [Français](README.fr.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Tiếng Việt](README.vi.md) · [中文 (简体)](README.zh-Hans.md) · [中文（繁體）](README.zh-Hant.md) · [Deutsch](README.de.md) · [Русский](README.ru.md)

# Agentic Browser

Chrome/Chromium と Chrome DevTools Protocol を使った、ローカル優先のエージェント型ブラウザ作業台です。Web UI、クリック可能なスクリーンショット、DOM 観察、CLI、`codex exec` による一手ずつの制御を提供します。

## クイックスタート

```bash
python3 -m pip install -r requirements.txt
./run-agentic-browser-vdesktop.sh start
```

`http://127.0.0.1:8794` を開きます。

## 機能

- Webapp と CLI から同じ制御ブラウザを操作。
- headless、Xephyr、Xvfb モードに対応。
- スクリーンショット、DOM、リンク、可視テキストをまとめて観察。
- 安全ポリシーで危険なミラーや直接ダウンロードをブロック。
- 実行ログを `library/` に保存。

詳細は [メイン README](../README.md) を参照してください。

