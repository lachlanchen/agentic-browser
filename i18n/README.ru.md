[English](../README.md) · [العربية](README.ar.md) · [Español](README.es.md) · [Français](README.fr.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Tiếng Việt](README.vi.md) · [中文 (简体)](README.zh-Hans.md) · [中文（繁體）](README.zh-Hant.md) · [Deutsch](README.de.md) · [Русский](README.ru.md)

# Agentic Browser

Локальная рабочая среда для агентного браузинга на базе настоящего Chrome/Chromium и Chrome DevTools Protocol. Она предоставляет веб-интерфейс, кликабельный скриншот, наблюдение DOM, CLI и wrapper `codex exec` для безопасного пошагового управления.

## Быстрый старт

```bash
python3 -m pip install -r requirements.txt
./run-agentic-browser-vdesktop.sh start
```

Откройте `http://127.0.0.1:8794`.

## Возможности

- Webapp и CLI управляют одним браузерным сервисом.
- Поддерживаются headless, Xephyr и Xvfb.
- Наблюдение скриншота, DOM, ссылок и видимого текста.
- Политика безопасности блокирует опасные mirror/download/direct-file URL.
- Логи сохраняются в `library/`.

Полная документация находится в [главном README](../README.md).

