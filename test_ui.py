# 界面回归检查：覆盖名单编辑、方案失效、页数调整与真实 PDF 输出。
import tkinter as tk

import pytest
from pypdf import PdfReader, PdfWriter

from app import TranscriptSplitterApp


@pytest.fixture
def app():
    window = TranscriptSplitterApp()
    window.update()
    yield window
    window.destroy()


def prepare(app, tmp_path, count=24):
    source = tmp_path / "成绩单.pdf"
    writer = PdfWriter()
    for _ in range(count * 2 + 1):
        writer.add_blank_page(width=100, height=100)
    writer.write(source)
    app.pdf_path_var.set(str(source))
    app.names_text.insert("1.0", "\n".join(f"学生{i}" for i in range(1, count + 1)))
    app.update()
    app.generate_plan()
    app.update()


def test_names_blanks_undo_and_numbering(app):
    app.names_text.insert("1.0", "张三\n\n李四\n  \n王五")
    app.update()
    assert app.count_var.get() == "3 人"
    numbers = [app.gutter.itemcget(item, "text") for item in app.gutter.find_all() if app.gutter.type(item) == "text"]
    assert numbers == ["1", "2", "3"]
    app.names_text.edit_separator()
    app.names_text.insert("end", "\n赵六")
    app.update()
    assert app.count_var.get() == "4 人"
    app.names_text.edit_undo()
    app.update()
    assert app.count_var.get() == "3 人"
    app.select_all_names(None)
    assert app.names_text.get("sel.first", "sel.last").startswith("张三\n\n李四")


def test_input_hint_focus_paste_clear_and_undo(app):
    assert app.names_placeholder.winfo_ismapped()
    assert not app.gutter.winfo_ismapped()
    assert not app.names_horizontal.winfo_ismapped()
    assert app.names_text.get("1.0", "end-1c") == ""
    app.focus_force()
    app.names_placeholder.event_generate("<Button-1>")
    app.update()
    assert app.focus_get() == app.names_text
    assert app.names_border.cget("highlightbackground") == "#2563eb"
    assert not app.names_placeholder.winfo_ismapped()
    app.clipboard_clear()
    app.clipboard_append("张三\n李四")
    app.names_text.event_generate("<<Paste>>")
    app.update()
    assert app.count_var.get() == "2 人"
    assert app.gutter.winfo_ismapped()
    assert not app.names_placeholder.winfo_ismapped()
    app.names_text.edit_separator()
    app.names_text.delete("1.0", "end")
    app.update()
    assert app.names_placeholder.winfo_ismapped()
    assert not app.gutter.winfo_ismapped()
    assert not app.names_text.tag_ranges("stripe")
    app.names_text.edit_undo()
    app.update()
    assert app.names_text.get("1.0", "end-1c") == "张三\n李四"
    assert not app.names_placeholder.winfo_ismapped()


def test_horizontal_overflow_and_pdf_hint(app):
    assert app.pdf_display_var.get() == "选择或拖入一个 PDF"
    assert app.pdf_path_var.get() == ""
    app.pdf_path_var.set("D:/成绩单.pdf")
    assert app.pdf_display_var.get() == "D:/成绩单.pdf"
    app.pdf_path_var.set("")
    assert app.pdf_display_var.get() == "选择或拖入一个 PDF"
    app.names_text.insert("1.0", "长姓名" * 100)
    app.update()
    assert app.names_horizontal.winfo_ismapped()
    app.names_text.delete("1.0", "end")
    app.names_text.insert("1.0", "张三")
    app.update()
    assert not app.names_horizontal.winfo_ismapped()
    app.geometry("880x650")
    app.update()
    assert app.pdf_entry.winfo_width() > 100
    assert app.pdf_entry.winfo_rootx() + app.pdf_entry.winfo_width() < app.winfo_rootx() + app.winfo_width()


def test_drop_one_pdf_and_reject_invalid_files(app, tmp_path, monkeypatch):
    source = tmp_path / "带 空格的成绩单.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(source)
    assert app.load_dropped_files([source])
    assert app.pdf_path_var.get() == str(source)
    assert app.pdf_total_pages == 1
    assert "1 页" in app.summary_var.get()

    warnings = []
    monkeypatch.setattr("app.messagebox.showwarning", lambda title, text: warnings.append(text))
    text_file = tmp_path / "名单.txt"
    text_file.write_text("张三", encoding="utf-8")
    assert not app.load_dropped_files([text_file])
    assert not app.load_dropped_files([source, source])
    assert warnings == ["请拖入一个有效的 PDF 文件。", "请一次只拖入一个 PDF 文件。"]


def test_editing_and_scroll(app, tmp_path):
    prepare(app, tmp_path, 100)
    app.tree.see("75")
    app.tree.selection_set("75")
    app.update()
    position = app.tree.yview()[0]
    app.apply_selected_pages(3)
    app.update()
    assert app.tree.yview()[0] == position
    assert app.plan[75].page_count == 3
    assert app.plan[76].start_page == app.plan[75].end_page + 1
    assert "超出 1 页" in app.summary_var.get()
    app.start_page_editor(75)
    app.editor.delete(0, "end")
    app.editor.insert(0, "0")
    assert not app.commit_page_edit()
    assert app.plan[75].page_count == 3
    assert app.edit_error.winfo_manager() == "grid"
    app.cancel_page_edit()
    app.start_page_editor(75)
    app.editor.delete(0, "end")
    app.editor.insert(0, "2")
    app.editor.focus_force()
    app.update()
    app.editor.event_generate("<Return>")
    app.update()
    assert app.plan[75].page_count == 2
    app.start_page_editor(75)
    app.editor.delete(0, "end")
    app.editor.insert(0, "4")
    app.editor.focus_force()
    app.update()
    app.editor.event_generate("<Escape>")
    app.update()
    assert app.plan[75].page_count == 2
    app.start_page_editor(75)
    app.editor.delete(0, "end")
    app.editor.insert(0, "3")
    app.editor.event_generate("<FocusOut>")
    app.update()
    assert app.plan[75].page_count == 3
    app.names_text.insert("end", "\n新同学")
    app.update()
    assert app.plan_is_stale
    assert app.split_button.instate(["disabled"])
    assert all(button.instate(["disabled"]) for button in app.quick_buttons)
    app.start_page_editor(75)
    assert app.editor is None


def test_output_and_repeated_split(app, tmp_path):
    prepare(app, tmp_path)
    assert "校验通过" in app.summary_var.get()
    assert app.tree.winfo_height() > 300
    app.filename_prefix_var.set("测试-")
    assert not app.plan_is_stale
    app.perform_split()
    first = app.last_output_dir
    assert len(list(first.glob("*.pdf"))) == 24
    assert len(PdfReader(first / "测试-学生1.pdf").pages) == 2
    app.perform_split()
    assert app.last_output_dir != first
    assert first.exists()
    assert app.result_var.get() == "已生成 24 个 PDF"
    app.directory_pages_var.set(2)
    assert app.plan_is_stale
    assert app.split_button.instate(["disabled"])


@pytest.mark.parametrize("scaling", [1.3333, 1.6667, 2.0])
def test_layout_scaling(app, scaling):
    app.tk.call("tk", "scaling", scaling)
    app.geometry("1100x760")
    app.update()
    assert app.tree.winfo_height() > 300
    assert app.split_button.winfo_rootx() + app.split_button.winfo_width() <= app.winfo_rootx() + app.winfo_width()
    app.state("zoomed")
    app.update()
    assert app.tree.winfo_height() > 300
