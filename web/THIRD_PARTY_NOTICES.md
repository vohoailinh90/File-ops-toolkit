# Third-party notices

Kit này (MIT, xem [LICENSE](./LICENSE)) có chứa mã chép hoặc chỉnh sửa từ các dự án dưới đây. License gốc của từng dự án áp dụng cho phần mã đó — khi copy các file này sang repo khác, **mang theo file này** (hoặc đúng đoạn license tương ứng).

Chỉ liệt kê mã **nằm trong repo**. Thư viện cài qua npm (`recharts`, `@radix-ui/*`, `lightweight-charts`, `@tanstack/react-table`, `cmdk`...) đi kèm license riêng trong `node_modules`.

## shadcn/ui — MIT

- Nguồn: https://github.com/shadcn-ui/ui (registry `new-york-v4`, commit `98a1fe6`, 2026-09-25)
- Áp dụng cho `src/components/ui/*`:
  - `chart.tsx` — gần nguyên văn (chỉ đổi import `cn`, bỏ `"use client"`).
  - `toggle.tsx`, `toggle-group.tsx` — theo API của shadcn, chỉnh focus ring, màu hover và trạng thái bật cho đủ tương phản (chi tiết trong chú thích đầu file).
  - Các primitive còn lại (`button`, `card`, `badge`, `tabs`, `table`...) viết tay theo đúng API/convention của shadcn.

```
MIT License

Copyright (c) 2023 shadcn

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## taste-skill — MIT

- Nguồn: https://github.com/Leonxlnx/taste-skill (commit `ce26fc2`, 2026-09-26)
- Áp dụng cho `.claude/skills/design-taste-frontend/`:
  - `SKILL.md` — nguyên văn `skills/taste-skill/SKILL.md` của repo gốc (install name `design-taste-frontend`, bản v2 experimental), không sửa dòng nào. SHA-256: `aa194351b246b8b4799099d4ed7b033d29eab6e6e3d58d8d2172978be7b3ec89` — `sha256sum` ra số khác nghĩa là file đã bị sửa.
  - `LICENSE` — license gốc, để thư mục skill chép riêng sang repo khác vẫn đủ license.
- Đây là hướng dẫn cho agent (Markdown), không phải mã chạy trong app. Khi nào dùng skill và bên nào thắng khi nó vênh với kit: xem [CLAUDE.md](./CLAUDE.md).

```
MIT License

Copyright (c) 2026 Leonxlnx

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Kho skill giao diện (`skills/`)

Bốn skill dưới đây chép **nguyên văn, không sửa** vào `skills/` (riêng `swiftui-liquid-glass` vào `.claude/skills/`, vì đang bật ở kit), mỗi thư mục mang theo file giấy phép gốc để chép riêng sang repo khác vẫn đủ giấy phép. Commit đầy đủ, SHA-256 từng file và các file upstream cố ý không chép nằm ở [`skills/MANIFEST.json`](skills/MANIFEST.json); `python3 scripts/check_skills.py` kiểm mọi file. Skill thứ năm trong manifest là `design-taste-frontend`, ghi ở mục taste-skill phía trên (cũng nằm ở `.claude/skills/`). Đây là hướng dẫn cho agent (Markdown) và, ở `ui-ux-pro-max`, dữ liệu CSV cùng bốn script Python tra cứu cục bộ; không có mã nào chạy trong app của kit.

- **frontend-design — Apache-2.0.** Nguồn: https://github.com/anthropics/skills (commit `dbd4588`, 2026-10-09), thư mục `skills/frontend-design/`. Áp dụng cho `skills/frontend-design/` (`SKILL.md` và `LICENSE.txt`, giấy phép Apache-2.0 đầy đủ). Không sửa file nào, nên không phát sinh nghĩa vụ ghi chú thay đổi (§4b).
- **ui-ux-pro-max — MIT**, Copyright (c) 2024 Next Level Builder. Nguồn: https://github.com/nextlevelbuilder/ui-ux-pro-max-skill (commit `56ea9cf`, 2026-10-14), thư mục `.claude/skills/ui-ux-pro-max/`. Áp dụng cho `skills/ui-ux-pro-max/`; `LICENSE` là giấy phép gốc của repo. Không chép `scripts/tests/` và `scripts/validate_data.py`.
- **swiftui-liquid-glass — MIT**, Copyright (c) 2026 Thomas Ricouard. Nguồn: https://github.com/Dimillian/Skills (commit `05ba982`, 2026-03-29), thư mục `swiftui-liquid-glass/`. Áp dụng cho `.claude/skills/swiftui-liquid-glass/` (`SKILL.md`, `agents/openai.yaml`, `references/liquid-glass.md`, `LICENSE`); `LICENSE` là giấy phép gốc của repo. Khi nào dùng skill và bên nào thắng khi nó vênh với kit: xem [CLAUDE.md](./CLAUDE.md).
- **swiftui-design-skill — MIT**, Copyright (c) 2026 wholiver. Nguồn: https://github.com/Wholiver/swiftui-design-skill (commit `2c82638`, 2026-05-01). Áp dụng cho `skills/swiftui-design-skill/` (`SKILL.md`, `metadata.json`, `references/`, `templates/`, `LICENSE`). Không chép `README.md`, `README-zh.md`, `RELEASE-v1.0.0.md` và `.gitignore`.

Khi chép các thư mục này sang repo khác, mang theo cả file giấy phép trong thư mục (xem [`skills/README.md`](skills/README.md)).

## Tremor — chỉ cảm hứng thiết kế, không chép mã

`src/components/dashboard/{tracker,bar-list,category-bar,progress-ring}.tsx` lấy **ý tưởng hình ảnh** từ Tracker, BarList, CategoryBar và ProgressCircle của [Tremor](https://github.com/tremorlabs/tremor) (Apache-2.0), nhưng được viết lại từ đầu theo token và convention của kit — không có dòng mã nào chép từ Tremor, nên không kéo theo nghĩa vụ của Apache-2.0. Nếu sau này port nguyên văn một component của Tremor, phải giữ license Apache-2.0 cho file đó, ghi rõ đã sửa gì (§4b), và giữ các notice sẵn có (§4c).
