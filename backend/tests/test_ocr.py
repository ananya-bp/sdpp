"""OCR tests run the *real* Tesseract/poppler pipeline against real generated files - no mocking
of the OCR library itself, per the guide's rule that every "tested and working" claim needs a
real command/run behind it.
"""
import io

from PIL import Image, ImageDraw, ImageFont

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _text_png(lines: list[str]) -> bytes:
    font = ImageFont.truetype(FONT_PATH, 28)
    img = Image.new("RGB", (900, 60 * len(lines) + 40), "white")
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((20, 20 + i * 60), line, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _text_pdf(lines: list[str]) -> bytes:
    """A real, rasterizable single-page PDF: build the page as an image and save it as PDF."""
    font = ImageFont.truetype(FONT_PATH, 28)
    img = Image.new("RGB", (900, 60 * len(lines) + 40), "white")
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((20, 20 + i * 60), line, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, "PDF")
    return buf.getvalue()


def _blank_png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (200, 200), "white").save(buf, "PNG")
    return buf.getvalue()


SAMPLE_LINES = ["KLE Technological University", "USN: SIM23CSE001", "CGPA: 8.37", "Date: 12/05/2024"]


def submit(api, headers, doc_type_id, files):
    parts = [("files", (name, data, ctype)) for name, data, ctype in files]
    return api.post(
        "/api/applications", headers=headers, data={"document_type_id": str(doc_type_id)}, files=parts
    )


def test_ocr_extracts_text_and_fields_from_image(api, student_auth, doc_type, upload_dir):
    _, headers = student_auth
    png = _text_png(SAMPLE_LINES)
    r = submit(api, headers, doc_type.id, [("marks_card.png", png, "image/png")])
    application_id = r.json()["id"]

    r = api.post(f"/api/applications/{application_id}/ocr", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "OCR_COMPLETED"
    assert body["history"][-1]["status"] == "OCR_COMPLETED"

    [doc] = body["documents"]
    ocr = doc["ocr_result"]
    assert ocr["status"] == "SUCCESS"
    assert "SIM23CSE001" in ocr["raw_text"]
    assert ocr["extracted_fields"]["detected_usns"] == ["SIM23CSE001"]
    assert ocr["extracted_fields"]["detected_cgpa_like_numbers"] == ["8.37"]
    assert ocr["extracted_fields"]["detected_dates"] == ["12/05/2024"]
    assert ocr["extracted_fields"]["word_count"] > 0


def test_ocr_extracts_text_from_pdf(api, student_auth, doc_type, upload_dir):
    _, headers = student_auth
    pdf = _text_pdf(SAMPLE_LINES)
    r = submit(api, headers, doc_type.id, [("marks_card.pdf", pdf, "application/pdf")])
    application_id = r.json()["id"]

    r = api.post(f"/api/applications/{application_id}/ocr", headers=headers)
    assert r.status_code == 200
    [doc] = r.json()["documents"]
    assert doc["ocr_result"]["status"] == "SUCCESS"
    assert "SIM23CSE001" in doc["ocr_result"]["raw_text"]


def test_ocr_handles_blank_image_gracefully(api, student_auth, doc_type, upload_dir):
    _, headers = student_auth
    r = submit(api, headers, doc_type.id, [("blank.png", _blank_png(), "image/png")])
    application_id = r.json()["id"]

    r = api.post(f"/api/applications/{application_id}/ocr", headers=headers)
    assert r.status_code == 200
    [doc] = r.json()["documents"]
    assert doc["ocr_result"]["status"] == "SUCCESS"
    assert doc["ocr_result"]["raw_text"] == ""
    assert doc["ocr_result"]["extracted_fields"]["word_count"] == 0


def test_ocr_handles_corrupt_pdf_without_crashing(api, student_auth, doc_type, upload_dir):
    _, headers = student_auth
    # Passes upload validation (starts with %PDF-) but has no real page content - real Tesseract
    # error path, not a mock.
    corrupt = b"%PDF-1.4\n" + (b"\x00\x01\x02garbage" * 30)
    r = submit(api, headers, doc_type.id, [("corrupt.pdf", corrupt, "application/pdf")])
    application_id = r.json()["id"]

    r = api.post(f"/api/applications/{application_id}/ocr", headers=headers)
    assert r.status_code == 200  # request itself must not crash / 500
    body = r.json()
    assert body["status"] == "OCR_COMPLETED"  # still advances; a bad file doesn't block the app
    [doc] = body["documents"]
    assert doc["ocr_result"]["status"] == "FAILED"
    assert doc["ocr_result"]["error_message"]
    assert doc["ocr_result"]["raw_text"] is None


def test_ocr_with_no_files_still_completes(api, student_auth, doc_type):
    _, headers = student_auth
    r = submit(api, headers, doc_type.id, [])
    application_id = r.json()["id"]

    r = api.post(f"/api/applications/{application_id}/ocr", headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] == "OCR_COMPLETED"
    assert r.json()["documents"] == []


def test_ocr_rerun_replaces_result_not_duplicates(api, student_auth, doc_type, upload_dir):
    _, headers = student_auth
    png = _text_png(SAMPLE_LINES)
    r = submit(api, headers, doc_type.id, [("marks_card.png", png, "image/png")])
    application_id = r.json()["id"]

    r1 = api.post(f"/api/applications/{application_id}/ocr", headers=headers)
    r2 = api.post(f"/api/applications/{application_id}/ocr", headers=headers)
    assert r1.status_code == 200 and r2.status_code == 200
    assert len(r2.json()["documents"]) == 1  # one OCR result per document, not appended
    history_statuses = [h["status"] for h in r2.json()["history"]]
    assert history_statuses.count("OCR_COMPLETED") == 2  # but each run IS logged in history


def test_ocr_requires_login(api, doc_type):
    assert api.post("/api/applications/1/ocr").status_code == 401


def test_ocr_404_for_someone_elses_application(api, student_auth, make_student, register, doc_type):
    _, headers = student_auth
    r = submit(api, headers, doc_type.id, [])
    application_id = r.json()["id"]

    other = make_student()
    other_headers = {"Authorization": "Bearer " + register(other.usn, "other@example.com").json()["access_token"]}
    r = api.post(f"/api/applications/{application_id}/ocr", headers=other_headers)
    assert r.status_code == 404
