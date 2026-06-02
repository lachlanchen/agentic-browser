[English](../README.md) · [العربية](README.ar.md) · [Español](README.es.md) · [Français](README.fr.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Tiếng Việt](README.vi.md) · [中文 (简体)](README.zh-Hans.md) · [中文（繁體）](README.zh-Hant.md) · [Deutsch](README.de.md) · [Русский](README.ru.md)

# Agentic Browser

Một công cụ duyệt web agentic chạy cục bộ, dùng Chrome/Chromium thật và Chrome DevTools Protocol. Công cụ có webapp, vùng ảnh chụp có thể bấm, quan sát DOM, CLI và wrapper `codex exec` để chọn từng hành động an toàn.

## Chạy nhanh

```bash
python3 -m pip install -r requirements.txt
./run-agentic-browser-vdesktop.sh start
```

Mở `http://127.0.0.1:8794`.

## Điểm chính

- Webapp và CLI điều khiển cùng một dịch vụ trình duyệt.
- Hỗ trợ headless, Xephyr và Xvfb.
- Quan sát ảnh chụp, DOM, liên kết và văn bản nhìn thấy.
- Chính sách an toàn chặn URL mirror/tải xuống/tệp trực tiếp không phù hợp.
- Nhật ký được lưu trong `library/`.

Xem [README chính](../README.md) để biết đầy đủ chi tiết.

