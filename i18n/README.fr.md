[English](../README.md) · [العربية](README.ar.md) · [Español](README.es.md) · [Français](README.fr.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Tiếng Việt](README.vi.md) · [中文 (简体)](README.zh-Hans.md) · [中文（繁體）](README.zh-Hant.md) · [Deutsch](README.de.md) · [Русский](README.ru.md)

# Agentic Browser

Un atelier local de navigation agentique basé sur Chrome/Chromium réel et Chrome DevTools Protocol. Il fournit une webapp, une capture cliquable, l’observation du DOM, une CLI et un wrapper `codex exec` pour choisir une action sûre à chaque étape.

## Démarrage rapide

```bash
python3 -m pip install -r requirements.txt
./run-agentic-browser-vdesktop.sh start
```

Ouvrez `http://127.0.0.1:8794`.

## Points clés

- Webapp et CLI pour contrôler le même navigateur.
- Modes headless, Xephyr et Xvfb.
- Observation par capture d’écran, DOM, liens et texte visible.
- Garde de sécurité pour bloquer les liens de miroir/téléchargement non autorisés.
- Journaux sous `library/`.

Voir le [README principal](../README.md) pour la documentation complète.

