"""Small synthetic fixture builders with no customer content."""

from __future__ import annotations


def make_text_pdf(pages: list[list[str]]) -> bytes:
    """Build a minimal PDF with built-in Helvetica and extractable ASCII text."""

    if not pages:
        raise ValueError("at least one page is required")
    font_object_id = 3 + len(pages) * 2
    page_object_ids = [3 + index * 2 for index in range(len(pages))]
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: (
            b"<< /Type /Pages /Kids ["
            + b" ".join(f"{object_id} 0 R".encode() for object_id in page_object_ids)
            + f"] /Count {len(pages)} >>".encode()
        ),
        font_object_id: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for index, lines in enumerate(pages):
        page_object_id = page_object_ids[index]
        content_object_id = page_object_id + 1
        operations = ["BT /F1 12 Tf 14 TL 72 720 Td"]
        for line_index, line in enumerate(lines):
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            if line_index:
                operations.append("T*")
            operations.append(f"({escaped}) Tj")
        operations.append("ET")
        stream = " ".join(operations).encode("latin-1")
        objects[page_object_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_object_id} 0 R >> >> "
            f"/Contents {content_object_id} 0 R >>"
        ).encode()
        objects[content_object_id] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode()
            + stream
            + b"\nendstream"
        )

    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for object_id in range(1, font_object_id + 1):
        offsets.append(len(output))
        output.extend(f"{object_id} 0 obj\n".encode())
        output.extend(objects[object_id])
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {font_object_id + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        (
            f"trailer\n<< /Size {font_object_id + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode()
    )
    return bytes(output)

