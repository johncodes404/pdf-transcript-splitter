from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from core import (OutputNaming, SplitterError, build_plan, page_difference,
                  planned_filenames, recalculate_ranges, split_pdf)


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


def test_numbered_output_with_duplicate_names_and_directory(tmp_path):
    source = tmp_path / "成绩单.pdf"
    make_pdf(source, 6)  # two directory pages, one page, three pages
    plan = build_plan(["张盼", "张盼"], directory_pages=2, default_pages=1, allow_duplicate_names=True)
    plan[1].page_count = 3
    naming = OutputNaming("061", 5, 3, True, 0)
    output = split_pdf(source, plan, 2, naming=naming)
    files = sorted(output.glob("*.pdf"))
    assert [file.name for file in files] == ["061-000-目录.pdf", "061-005-张盼.pdf", "061-006-张盼.pdf"]
    assert [len(PdfReader(file).pages) for file in files] == [2, 1, 3]
    assert len(PdfReader(source).pages) == 6


@pytest.mark.parametrize("count,start,digits,directory,expected_first,expected_last", [
    (30, 1, None, False, "061-01-学生.pdf", "061-30-学生.pdf"),
    (120, 1, None, False, "061-001-学生.pdf", "061-120-学生.pdf"),
    (99, 1, None, True, "061-000-目录.pdf", "061-099-学生.pdf"),
    (2, 99, 2, False, "061-099-学生.pdf", "061-100-学生.pdf"),
    (2, 0, 4, False, "061-0000-学生.pdf", "061-0001-学生.pdf"),
])
def test_uniform_number_width(count, start, digits, directory, expected_first, expected_last):
    plan = build_plan(["学生"] * count, allow_duplicate_names=True)
    filenames = planned_filenames(plan, 1, OutputNaming("061", start, digits, directory))
    assert filenames[0] == expected_first
    assert filenames[-1] == expected_last
    assert len(set(filenames)) == len(filenames)


def test_custom_directory_number_and_no_directory_pages(tmp_path):
    source = tmp_path / "成绩单.pdf"
    make_pdf(source, 2)
    plan = build_plan(["张三", "李四"], directory_pages=0, default_pages=1)
    naming = OutputNaming("00012", 20, 2, True, 999)
    output = split_pdf(source, plan, 0, naming=naming)
    assert sorted(file.name for file in output.glob("*.pdf")) == ["00012-20-张三.pdf", "00012-21-李四.pdf"]
    assert planned_filenames(plan, 1, naming)[0] == "00012-999-目录.pdf"
    assert planned_filenames(plan, 1, OutputNaming("", 7, 2))[0] == "07-张三.pdf"


@pytest.mark.parametrize("naming", [OutputNaming("../061"), OutputNaming(start_number=-1),
                                      OutputNaming(sequence_digits=0), OutputNaming(directory_number=-1),
                                      OutputNaming("061", 0, 2, True, 0)])
def test_invalid_naming_leaves_no_output(tmp_path, naming):
    source = tmp_path / "成绩单.pdf"
    make_pdf(source, 3)
    plan = build_plan(["目录"], default_pages=2)
    target = tmp_path / "输出"
    with pytest.raises(SplitterError):
        split_pdf(source, plan, 1, output_dir=target, naming=naming)
    assert not target.exists()
    assert not list(tmp_path.glob("输出.tmp*"))


def test_legacy_names_still_reject_duplicates():
    with pytest.raises(SplitterError):
        build_plan(["张盼", "张盼"])
