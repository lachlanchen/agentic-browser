[English](../README.md) · [العربية](README.ar.md) · [Español](README.es.md) · [Français](README.fr.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Tiếng Việt](README.vi.md) · [中文 (简体)](README.zh-Hans.md) · [中文（繁體）](README.zh-Hant.md) · [Deutsch](README.de.md) · [Русский](README.ru.md)

# Agentic Browser

Eine lokale agentische Browser-Workbench auf Basis von echtem Chrome/Chromium und Chrome DevTools Protocol. Sie bietet Webapp, klickbare Screenshot-Ansicht, DOM-Beobachtung, CLI und einen `codex exec` Wrapper für sichere Einzelschritte.

## Schnellstart

```bash
python3 -m pip install -r requirements.txt
./run-agentic-browser-vdesktop.sh start
```

Öffne `http://127.0.0.1:8794`.

## Funktionen

- Webapp und CLI steuern denselben Browserdienst.
- Unterstützt headless, Xephyr und Xvfb.
- Beobachtet Screenshot, DOM, Links und sichtbaren Text.
- Sicherheitsregeln blockieren riskante Mirror-, Download- und Direktdatei-URLs.
- Logs werden unter `library/` gespeichert.

Details stehen im [Haupt-README](../README.md).

