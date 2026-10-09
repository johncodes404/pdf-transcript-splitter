from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from pypdf import PdfReader, PdfWriter


INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class SplitterError(Exception):
    """Expected user-facing error for transcript splitting."""


@dataclass
class PersonPlan:
    name: str
    page_count: int = 2
    start_page: int = 0  # 1-based PDF page number
    end_page: int = 0    # 1-based PDF page number


@dataclass(frozen=True)
class OutputNaming:
    fixed_number: str = ""
    start_number: int = 1
    sequence_digits: int | None = None  # None means automatic, at least two digits
    export_directory: bool = False
    directory_number: int = 0

    def width(self, person_count: int, directory_pages: int) -> int:
        if self.fixed_number and not re.fullmatch(r"[0-9]+", self.fixed_number):
            raise SplitterError("固定编号只能填写数字，也可以留空；前导零会保留。")
        for title, value in (("起始序号", self.start_number), ("目录编号", self.directory_number)):
            if type(value) is not int or value < 0:
                raise SplitterError(f"{title}必须是大于或等于 0 的整数。")
        if self.sequence_digits is not None and (type(self.sequence_digits) is not int or self.sequence_digits < 1):
            raise SplitterError("序号位数必须是大于 0 的整数，或选择自动。")
        export_directory = self.export_directory and directory_pages > 0
        largest = max(self.start_number, self.start_number + person_count - 1,
                      self.directory_number if export_directory else 0)
        requested = self.sequence_digits if self.sequence_digits is not None else max(2, len(str(person_count + int(export_directory))))
        return max(requested, len(str(largest)))

    def filename(self, name: str, number: int, width: int) -> str:
        prefix = f"{self.fixed_number}-" if self.fixed_number else ""
        return f"{prefix}{number:0{width}d}-{sanitize_filename(name)}.pdf"


def planned_filenames(plan: list[PersonPlan], directory_pages: int, naming: OutputNaming) -> list[str]:
    """Return filenames in output order, using the same rules as the writer."""
    width = naming.width(len(plan), directory_pages)
    filenames = []
    if naming.export_directory and directory_pages > 0:
        filenames.append(naming.filename("目录", naming.directory_number, width))
    filenames.extend(naming.filename(item.name, naming.start_number + index, width)
                     for index, item in enumerate(plan))
    if len({name.casefold() for name in filenames}) != len(filenames):
        raise SplitterError("目录文件与人员文件名冲突，请调整目录编号或起始序号。")
    return filenames


def parse_names(raw_text: str) -> list[str]:
    """Parse one-name-per-line input, ignoring blank lines."""
    names = [line.strip() for line in raw_text.replace("\r\n", "\n").split("\n")]
    return [name for name in names if name]


def validate_names(names: Iterable[str], allow_duplicates: bool = False) -> list[str]:
    cleaned = [name.strip() for name in names if name.strip()]
    if not cleaned:
        raise SplitterError("姓名名单为空。请粘贴姓名后再生成拆分方案。")
    if allow_duplicates:
        return cleaned

    seen: set[str] = set()
    duplicates: list[str] = []
    for name in cleaned:
        if name in seen and name not in duplicates:
            duplicates.append(name)
        seen.add(name)
    if duplicates:
        raise SplitterError("姓名存在重复，可能导致文件覆盖：" + "、".join(duplicates))

    safe_names = [sanitize_filename(name) for name in cleaned]
    seen_safe: set[str] = set()
    safe_duplicates: list[str] = []
    for original, safe in zip(cleaned, safe_names):
        key = safe.casefold()
        if key in seen_safe and original not in safe_duplicates:
            safe_duplicates.append(original)
        seen_safe.add(key)
    if safe_duplicates:
        raise SplitterError(
            "部分姓名清理为 Windows 文件名后会重复，请调整这些姓名："
            + "、".join(safe_duplicates)
        )

    return cleaned


def sanitize_filename(name: str) -> str:
    safe = INVALID_FILENAME_CHARS.sub("_", name).strip().rstrip(".")
    if not safe:
        safe = "未命名"
    if safe.upper() in WINDOWS_RESERVED_NAMES:
        safe = f"_{safe}"
    return safe


def get_pdf_page_count(pdf_path: str | Path) -> int:
    path = Path(pdf_path)
    if not path.is_file():
        raise SplitterError("找不到 PDF 文件，请重新选择。")
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            try:
                result = reader.decrypt("")
            except Exception as exc:  # pragma: no cover - library/version dependent
                raise SplitterError("该 PDF 已加密，暂不支持需要密码的 PDF。") from exc
            if not result:
                raise SplitterError("该 PDF 已加密，暂不支持需要密码的 PDF。")
        return len(reader.pages)
    except SplitterError:
        raise
    except Exception as exc:
        raise SplitterError(f"无法读取 PDF：{exc}") from exc


def build_plan(names: Iterable[str], directory_pages: int = 1, default_pages: int = 2,
               allow_duplicate_names: bool = False) -> list[PersonPlan]:
    if directory_pages < 0:
        raise SplitterError("目录页数不能小于 0。")
    if default_pages < 1:
        raise SplitterError("默认每人页数至少为 1。")

    valid_names = validate_names(names, allow_duplicates=allow_duplicate_names)
    plan = [PersonPlan(name=name, page_count=default_pages) for name in valid_names]
    recalculate_ranges(plan, directory_pages)
    return plan


def recalculate_ranges(plan: list[PersonPlan], directory_pages: int) -> None:
    if directory_pages < 0:
        raise SplitterError("目录页数不能小于 0。")

    current_page = directory_pages + 1
    for item in plan:
        if item.page_count < 1:
            raise SplitterError(f"{item.name} 的页数至少为 1。")
        item.start_page = current_page
        item.end_page = current_page + item.page_count - 1
        current_page = item.end_page + 1


def planned_total_pages(plan: Iterable[PersonPlan], directory_pages: int) -> int:
    return directory_pages + sum(item.page_count for item in plan)


def page_difference(plan: Iterable[PersonPlan], directory_pages: int, pdf_total_pages: int) -> int:
    """Return PDF pages minus pages covered by the current plan."""
    return pdf_total_pages - planned_total_pages(plan, directory_pages)


def unique_output_dir(pdf_path: str | Path) -> Path:
    path = Path(pdf_path)
    base = path.with_name(f"{path.stem}_拆分结果")
    if not base.exists():
        return base

    index = 2
    while True:
        candidate = path.with_name(f"{path.stem}_拆分结果_{index}")
        if not candidate.exists():
            return candidate
        index += 1


def split_pdf(
    pdf_path: str | Path,
    plan: list[PersonPlan],
    directory_pages: int,
    output_dir: str | Path | None = None,
    filename_prefix: str = "",
    naming: OutputNaming | None = None,
) -> Path:
    path = Path(pdf_path)
    total_pages = get_pdf_page_count(path)
    recalculate_ranges(plan, directory_pages)

    diff = page_difference(plan, directory_pages, total_pages)
    if diff != 0:
        if diff > 0:
            raise SplitterError(f"还有 {diff} 页未分配，请先修正特殊成绩单的页数。")
        raise SplitterError(f"当前方案超出 PDF {-diff} 页，请先修正页数。")

    validate_names((item.name for item in plan), allow_duplicates=naming is not None)
    if naming is not None:
        filenames = planned_filenames(plan, directory_pages, naming)
    else:
        filenames = [sanitize_filename(f"{filename_prefix}{item.name}") + ".pdf" for item in plan]

    target = Path(output_dir) if output_dir else unique_output_dir(path)
    if target.exists():
        raise SplitterError(f"输出目录已存在：{target}")

    temp_dir = target.with_name(target.name + ".tmp")
    suffix = 2
    while temp_dir.exists():
        temp_dir = target.with_name(target.name + f".tmp{suffix}")
        suffix += 1

    reader = PdfReader(str(path))
    if reader.is_encrypted:
        try:
            result = reader.decrypt("")
        except Exception as exc:  # pragma: no cover
            raise SplitterError("该 PDF 已加密，暂不支持需要密码的 PDF。") from exc
        if not result:
            raise SplitterError("该 PDF 已加密，暂不支持需要密码的 PDF。")

    try:
        temp_dir.mkdir(parents=True, exist_ok=False)
        if naming is not None and naming.export_directory and directory_pages > 0:
            writer = PdfWriter()
            for page_number in range(directory_pages):
                writer.add_page(reader.pages[page_number])
            with (temp_dir / filenames.pop(0)).open("wb") as handle:
                writer.write(handle)
        for item, filename in zip(plan, filenames):
            writer = PdfWriter()
            for page_number in range(item.start_page, item.end_page + 1):
                writer.add_page(reader.pages[page_number - 1])

            output_file = temp_dir / filename
            with output_file.open("wb") as handle:
                writer.write(handle)

        temp_dir.rename(target)
        return target
    except Exception as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        if isinstance(exc, SplitterError):
            raise
        raise SplitterError(f"拆分失败：{exc}") from exc
