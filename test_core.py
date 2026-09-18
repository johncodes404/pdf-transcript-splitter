from pathlib import Path

from pypdf import PdfReader, PdfWriter

from core import build_plan, page_difference, recalculate_ranges, split_pdf


def make_pdf(path: Path, pages: int) -> None:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    with path.open("wb") as handle:
        writer.write(handle)


def test_variable_page_counts(tmp_path: Path) -> None:
    source = tmp_path / "成绩单.pdf"
    make_pdf(source, 10)  # 1 directory + 2 + 3 + 4

    plan = build_plan(["张三", "李四", "王五"], directory_pages=1, default_pages=2)
    assert page_difference(plan, 1, 10) == 3

    plan[1].page_count = 3
    plan[2].page_count = 4
    recalculate_ranges(plan, 1)
    assert [(p.start_page, p.end_page) for p in plan] == [(2, 3), (4, 6), (7, 10)]
    assert page_difference(plan, 1, 10) == 0

    out = split_pdf(source, plan, directory_pages=1, filename_prefix="2026秋季-")
    assert len(PdfReader(str(out / "2026秋季-张三.pdf")).pages) == 2
    assert len(PdfReader(str(out / "2026秋季-李四.pdf")).pages) == 3
    assert len(PdfReader(str(out / "2026秋季-王五.pdf")).pages) == 4
