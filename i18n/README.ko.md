[English](../README.md) · [العربية](README.ar.md) · [Español](README.es.md) · [Français](README.fr.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Tiếng Việt](README.vi.md) · [中文 (简体)](README.zh-Hans.md) · [中文（繁體）](README.zh-Hant.md) · [Deutsch](README.de.md) · [Русский](README.ru.md)

# Agentic Browser

실제 Chrome/Chromium과 Chrome DevTools Protocol을 사용하는 로컬 우선 에이전트 브라우저 작업대입니다. 웹앱, 클릭 가능한 스크린샷 뷰포트, DOM 관찰, CLI, `codex exec` 기반의 단계별 제어를 제공합니다.

## 빠른 시작

```bash
python3 -m pip install -r requirements.txt
./run-agentic-browser-vdesktop.sh start
```

`http://127.0.0.1:8794` 를 여세요.

## 기능

- 웹앱과 CLI가 같은 브라우저 서비스를 제어합니다.
- headless, Xephyr, Xvfb 모드를 지원합니다.
- 스크린샷, DOM, 링크, 보이는 텍스트를 함께 관찰합니다.
- 안전 정책으로 위험한 미러/다운로드/직접 파일 URL을 차단합니다.
- 로그는 `library/` 아래에 저장됩니다.

전체 문서는 [메인 README](../README.md)를 참고하세요.

