Không đủ căn cứ để khẳng định A mới hơn B hoặc venue Z nằm trong ngân sách 500 USD.

Đây là đánh giá **tình huống giả lập**, dựa hoàn toàn vào các mô tả và dữ kiện bạn cung cấp. Tôi không tìm kiếm web, không kiểm tra bibliographic identity, không có bản thảo thực tế để đọc hoặc xác minh số trang. “A có full text” trong tình huống không có nghĩa tôi đã đọc toàn bộ A. Các tên A/B/C/Z không được xem là tài liệu hay venue thật.

| Đối tượng/claim | Novelty /10 | Căn cứ và mức chắc chắn |
|---|---:|---|
| Thuật toán trung tâm của A, so với C | **0/10**, trong phép đối chiếu giả lập này | Quy tắc chọn phương sai hậu nghiệm lớn nhất, kernel GP và giả định nhiễu đều trùng C; chỉ đổi acronym. C là `direct_precedent` cho claim này. Chắc chắn cao **có điều kiện vào tính đúng/đủ của dữ kiện đã cung cấp**, không phải chứng nhận toàn bộ lịch sử phương pháp. |
| Phần áp dụng vào bệnh viện mới của A | **2/10, tạm thời**, khoảng phán đoán 1–3 | Thay bối cảnh/dataset nhưng chưa chỉ ra khác biệt làm thay đổi suy luận hoặc quyết định. Chắc chắn thấp: chưa có tìm kiếm tiền lệ cho dataset/bối cảnh, chưa xem bằng chứng về ý nghĩa khoa học. Đây không phải điểm gộp của toàn bài. |
| B | **Chưa đánh giá được** | Abstract chỉ tuyên bố cơ chế nhân quả mới và cải thiện 5%; chưa xác minh cơ chế, tiền lệ, thiết kế hoặc kết quả. Không chấm 0 vì thiếu truy cập, cũng không thưởng điểm cho chữ “new”. |

Các điểm này là phán đoán có giải thích trên thang quy ước, không phải đại lượng novelty đã hiệu chuẩn. Không lấy trung bình novelty thuật toán và dataset để tạo điểm novelty tổng thể của A. Cần xác định contribution chính, đánh giá tiền lệ của từng claim, rồi mới kết luận ở cấp bản thảo.

**Điểm tổng thể A và B: chưa đủ căn cứ; không xếp hạng.** Không đủ dữ liệu để chấm cùng sáu chiều importance, novelty, soundness, evidence, transparency và clarity. A được mô tả chi tiết hơn B không khiến nó tự động tốt hơn. Nếu sau này có đủ tài liệu, có thể công bố trước trọng số cho bài thực nghiệm (15/20/20/20/15/10), áp dụng nhất quán, công bố từng chiều và kiểm tra độ nhạy; không phân bổ lại trọng số để lấp chiều chưa biết.

Accuracy 0,91 của A chưa chứng minh ưu thế: thiếu bất định, thông tin so sánh và kiểm tra độc lập giữa train/test. **Patient overlap hiện là nghi vấn chưa được xác minh**, không phải bằng chứng chắc chắn leakage đã xảy ra. Nếu có overlap không phù hợp với mục tiêu dự đoán, phép đánh giá cần làm lại; điểm tổng hợp không được che lấp vấn đề này. Claim “cơ chế nhân quả” của B cũng chưa được chứng minh chỉ bởi cải thiện accuracy. “5%” còn cần phân biệt phần trăm tương đối với điểm phần trăm.

Hành động tiếp theo cho A:

1. Bỏ claim thuật toán mới; mô tả và dẫn nguồn việc sử dụng phương pháp C, không đặt tên lớn để ngụ ý novelty.
2. Kiểm tra ID bệnh nhân, thời điểm, split và mọi bước preprocessing; lưu dữ liệu kiểm tra overlap. Chọn split theo đúng đối tượng khái quát hóa. Nếu sửa sau khi xem kết quả, ghi rõ đây là sửa đổi, không giả vờ là kế hoạch ban đầu.
3. So sánh phương pháp tái sử dụng với baseline phù hợp dưới cùng dữ liệu, ngân sách tuning và protocol; báo số lượng bệnh nhân/quan sát, độ bất định có xét phụ thuộc và chỉ số phù hợp mục tiêu. Chưa chạy thì không ghi thành kết quả.
4. Chỉ phát triển claim bối cảnh mới nếu có lý do cụ thể rằng bối cảnh bệnh viện làm thay đổi suy luận, ranh giới áp dụng hoặc quyết định, rồi tìm tiền lệ cho claim đó. Một triển khai/split sai cần sửa không tự trở thành research gap.
5. Lấy full text B và các tiền lệ gần nhất trước khi xếp hạng novelty hay chất lượng A–B. Nếu vẫn không tiếp cận được, giữ kết luận không so sánh được.

Với Z, chỉ các mốc sau được **cho sẵn trong CFP giả lập**, chưa được kiểm chứng ngoài tình huống:

| Mốc | Theo CFP giả lập | Asia/Saigon (UTC+7) |
|---|---|---|
| Đăng ký abstract | 28/01/2027, 23:59 AoE (UTC−12) | **29/01/2027, 18:59** |
| Nộp full paper | 04/02/2027, 23:59 AoE (UTC−12) | **05/02/2027, 18:59** |
| Sự kiện | 10–12/06/2027 | Giữ ngày gốc; chưa có nơi tổ chức, giờ và múi giờ để chuyển đổi |

Đổi AoE sang giờ Việt Nam cộng 19 giờ; đã kiểm tra phép chuyển bằng datetime/ZoneInfo. Không bỏ qua mốc abstract sớm hơn full paper; cần xác nhận liệu đây có phải điều kiện bắt buộc để nộp bài. Notification, rebuttal, revision, camera-ready và đăng ký tác giả chưa được cung cấp.

**Chi phí: chưa xác định.** Không có fee page không có nghĩa miễn phí. Cần nguồn chính thức cho phí nộp, phí xuất bản/APC, đăng ký tác giả bắt buộc, quá trang, thuế, các khoản bao gồm trong gói và waiver; thêm đi lại, visa, lưu trú nếu phải trình bày trực tiếp. Không cộng trùng phí đã bao gồm và không giả định waiver được duyệt. Chưa thể chứng minh tổng bắt buộc nằm dưới 500 USD; không có cơ sở bịa một khoảng giá.

**Venue fit /10: chưa chấm được.** Chưa có scope/track, loại contribution được nhận, yêu cầu bằng chứng, format/eligibility và chi phí. Không suy ra xác suất được nhận từ deadline. Chưa thể chọn Z làm phương án khả thi hoặc đặt lịch hoàn thành thí nghiệm tùy ý: trước hết cần thời lượng thực tế cho audit dữ liệu → sửa và chạy lại nếu cần → phân tích → sửa claim → kiểm tra tiền lệ → draft/coauthor review → format và buffer nộp. Đặt go/no-go trước mốc abstract sau khi biết chi phí, eligibility và khả năng hoàn thành bằng chứng; nếu không đạt, chọn chu kỳ/venue khác đã kiểm chứng.
