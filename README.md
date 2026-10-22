# File Ops Toolkit

Tool lấy file hàng loạt: đọc một file Excel, mở từng thư mục trên server, tìm các file có tên được liệt kê
và sao chép toàn bộ về một thư mục do bạn chọn. Giao diện web (React, dựng từ
[Automation-UI-Kit](https://github.com/vohoailinh90/Automation-UI-Kit)) chạy ngay trên máy Windows của bạn
để truy cập được thư mục mạng. Giao diện có tiếng Việt / English / 日本語.

## File Excel đầu vào

| | A | B |
|---|---|---|
| 1 | `Address` | `File_Name` |
| 2 | `\\server\share\Folders_For_QMC22\19QMC_0039_230005433535` | `Report_0501.xlsx` |
| 3 | `\\server\share\Folders_For_QMC22\19QMC_0042_230005433544` | `Report_0128` |

- Dòng 1 là tiêu đề; dữ liệu từ dòng 2. Dòng trống bị bỏ qua.
- Cột A có thể là chữ đường dẫn UNC / ổ đĩa, ô có hyperlink (`file://...`), hoặc công thức `=HYPERLINK(...)`.
  Nếu ô hiển thị chữ thân thiện (vd "Mở thư mục"), tool dùng địa chỉ của hyperlink.
- Cột B là tên file. Không phân biệt hoa thường. Nếu **không có đuôi file** (vd `Report_0128`) thì khớp với
  file cùng tên ở mọi đuôi (`Report_0128.pdf`, `Report_0128.xlsx`…), nhưng chỉ khi không có file trùng đúng tên.
- Mặc định tìm cả trong thư mục con; mọi file trùng tên đều được lấy.

## Chạy

Cần Python 3.10+ và (lần đầu, để dựng giao diện) Node.js 22+.

```bat
start.bat
```

hoặc:

```bash
pip install -r requirements.txt
cd web && npm ci && npm run build && cd ..
python app.py                 # mở giao diện tại http://127.0.0.1:8765
python app.py run list.xlsx D:\fetched --report report.csv   # không cần giao diện
```

Trong giao diện: chọn file Excel → chọn thư mục đích (gõ đường dẫn hoặc "Duyệt…") → **Bắt đầu**. Kết quả từng
dòng hiện theo thời gian thực và có thể xuất CSV.

## An toàn dữ liệu

- Chỉ **đọc** từ server: không sửa, không xóa, không di chuyển gì ở nguồn.
- Không bao giờ **ghi đè** file trong thư mục đích. Chạy lại cùng danh sách thì file đã có (giống hệt) được báo
  "Đã có sẵn"; file khác nhưng trùng tên được lưu thành `tên (2).đuôi`. Tùy chọn "mỗi thư mục nguồn một thư
  mục con" tránh va chạm tên.
- Máy chủ chỉ lắng nghe `127.0.0.1`, mỗi lần chạy có token riêng, và kiểm tra header Host.
- Chưa hỗ trợ liên kết web (SharePoint, Google Drive): dòng đó báo "Chưa hỗ trợ liên kết web".

## Phát triển

Repo này mang theo bộ agent routing (roster, chính sách T0–T3, ngân sách agent, hook) để làm việc với Claude Code;
xem [`CLAUDE.md`](CLAUDE.md). Kiểm tra: `pytest`, `python scripts/mutation_check.py --all`,
`python scripts/i18n_check.py`, `python scripts/layout_check.py`, và `npm run typecheck && npm run lint && npm run build` trong `web/`.

Thành phần giao diện sao chép từ Automation-UI-Kit (MIT, dựa trên shadcn/ui): xem `web/THIRD_PARTY_NOTICES.md`.
