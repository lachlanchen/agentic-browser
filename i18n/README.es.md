[English](../README.md) · [العربية](README.ar.md) · [Español](README.es.md) · [Français](README.fr.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Tiếng Việt](README.vi.md) · [中文 (简体)](README.zh-Hans.md) · [中文（繁體）](README.zh-Hant.md) · [Deutsch](README.de.md) · [Русский](README.ru.md)

# Agentic Browser

Un banco de trabajo local para navegación asistida por agentes. Usa Chrome/Chromium real, Chrome DevTools Protocol, una webapp visible, una vista de captura interactiva, observación del DOM y un wrapper de `codex exec` para ejecutar una acción acotada por paso.

## Inicio rápido

```bash
python3 -m pip install -r requirements.txt
./run-agentic-browser-vdesktop.sh start
```

Abre `http://127.0.0.1:8794`.

## Capacidades

- Control manual desde webapp y CLI.
- Modo headless, Xephyr o Xvfb.
- Observación combinada de screenshot, DOM, enlaces y texto visible.
- Navegación protegida y descargas públicas permitidas solo bajo política.
- Logs en `library/`.

Consulta el [README principal](../README.md) para la documentación completa.

