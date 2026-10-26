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
- Cột B là tên file. Không phân biệt hoa thường. Tool lấy **mọi file có tên chứa** chữ trong ô B, nên báo cáo bị ghi
  thêm tên dự án vẫn tìm được: `Report_0128` tìm được `Report_0128.pdf`, `Report_0128_TenDuAn.pdf` và
  `TenDuAn_Report_0128.xlsx`. Chỉ tên file được so, không so tên thư mục. Phần đuôi không bị tìm trong tên:
  nếu ô B **không có đuôi file** (vd `Report_0128`) thì khớp mọi đuôi; nếu **có đuôi** (vd `Report_0501.xlsx`) thì
  file phải có đúng đuôi đó (`Report_0501_TenDuAn.xlsx` khớp, `Report_0501.xlsx.bak` không khớp).
  Ô số định dạng `0000` được hiểu là `0005`, không phải `5`.
- Vì khớp theo "chứa", tên quá ngắn hoặc quá chung sẽ lấy nhiều file ngoài ý muốn (`0005` cũng khớp `10005.pdf`):
  hãy nhập tên đủ dài để chỉ ra đúng báo cáo.
- Cột A phải là đường dẫn tuyệt đối (UNC, ổ đĩa, `file:`); chữ thường hoặc đường dẫn tương đối bị báo "Không phải đường dẫn thư mục".
- Mặc định tìm cả trong thư mục con; mọi file có tên chứa tên ở cột B đều được lấy.

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
- Thư mục đích **không được nằm trong** (hoặc trùng) một thư mục nguồn, vì như vậy sẽ ghi vào server.
- File CSV xuất ra vô hiệu hóa ô bắt đầu bằng `=`, `+`, `-`, `@` để Excel không chạy thành công thức.
- Máy chủ chỉ lắng nghe `127.0.0.1`, mỗi lần chạy có token riêng, và kiểm tra header Host. (Token nằm trong trang web nên tool dành cho máy một người dùng.)
- Chưa hỗ trợ liên kết web (SharePoint, Google Drive): dòng đó báo "Chưa hỗ trợ liên kết web".

## Phát triển

Repo này mang theo bộ agent routing (roster, chính sách T0–T3, ngân sách agent, hook) để làm việc với Claude Code;
xem [`CLAUDE.md`](CLAUDE.md). Kiểm tra: `pytest`, `python scripts/mutation_check.py --all`,
`python scripts/i18n_check.py`, `python scripts/layout_check.py`, và `npm run typecheck && npm run lint && npm run build` trong `web/`.

Thành phần giao diện sao chép từ Automation-UI-Kit (MIT, dựa trên shadcn/ui): xem `web/THIRD_PARTY_NOTICES.md`.
