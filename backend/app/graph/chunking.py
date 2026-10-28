OVERLAP = 100


def chunk_text(text: str, size: int) -> list[str]:
    """Paragraph-aware packing; an oversized paragraph is cut with overlap."""
    pieces = []
    for para in (p.strip() for p in text.split("\n\n")):
        if not para:
            continue
        while len(para) > size:
            cut = para.rfind(" ", size // 2, size)
            cut = cut if cut > 0 else size
            pieces.append(para[:cut])
            para = para[max(cut - OVERLAP, 1) :].lstrip()
        pieces.append(para)
    chunks, cur = [], ""
    for piece in pieces:
        if cur and len(cur) + len(piece) + 2 > size:
            chunks.append(cur)
            cur = piece
        else:
            cur = f"{cur}\n\n{piece}" if cur else piece
    if cur:
        chunks.append(cur)
    return chunks
