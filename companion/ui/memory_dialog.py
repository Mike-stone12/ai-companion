"""Thin Qt binding for the GUI-independent memory browser."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from companion.core.diary import DiaryEntry
from companion.core.memory.browser import MemoryBrowserModel


class MemoryDialog(QDialog):
    def __init__(
        self, model: MemoryBrowserModel, parent: QWidget | None = None, *,
        diary: list[DiaryEntry] | None = None, self_memories: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.model = model
        self.setWindowTitle("Memories")
        self.resize(640, 560)
        # Override the avatar window's dark line-edit styling, as Settings does.
        self.setStyleSheet("""
            QLineEdit {
                color: palette(text);
                background-color: palette(base);
                border: 1px solid palette(mid);
                border-radius: 2px;
                min-height: 0px;
                padding: 4px;
            }
        """)
        outer = QVBoxLayout(self)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)
        memories_page = QWidget()
        layout = QVBoxLayout(memories_page)
        self.tabs.addTab(memories_page, "Your memories")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search memories")
        self.search.setAccessibleName("Search memories")
        layout.addWidget(self.search)
        self.memories = QListWidget()
        self.memories.setAccessibleName("Memories, newest first")
        layout.addWidget(self.memories, 1)
        layout.addWidget(self._label("Save your summary before changing selection or search."))
        self.editor = QPlainTextEdit()
        self.editor.setAccessibleName("Selected memory summary")
        layout.addWidget(self.editor)
        self.message = self._label("")
        self.message.setWordWrap(True)
        self.message.hide()
        layout.addWidget(self.message)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close)
        self.save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        self.save_button.setAutoDefault(False)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        if diary is not None:
            self.tabs.addTab(self._diary_page(diary), "Her diary")
        if self_memories is not None:
            self.tabs.addTab(self._self_page(self_memories), "Her own memories")
        self.memories.currentItemChanged.connect(self._select_memory)
        self.search.textChanged.connect(self._refresh)
        self._refresh()

    def _diary_page(self, entries: list[DiaryEntry]) -> QWidget:
        """Read-only: newest entry first, full text below."""
        page = QWidget()
        layout = QVBoxLayout(page)
        self.diary_list = QListWidget()
        self.diary_list.setAccessibleName("Diary entries, newest first")
        self.diary_text = QPlainTextEdit()
        self.diary_text.setReadOnly(True)
        self.diary_text.setAccessibleName("Selected diary entry")
        for entry in sorted(entries, key=lambda item: item.day, reverse=True):
            item = QListWidgetItem()
            preview = entry.text if len(entry.text) <= 24 else entry.text[:23] + "…"
            item.setData(Qt.ItemDataRole.DisplayRole, f"{entry.day:%Y-%m-%d}  {preview}")
            item.setData(Qt.ItemDataRole.UserRole, entry.text)
            self.diary_list.addItem(item)
        self.diary_list.currentItemChanged.connect(
            lambda current, _previous: self.diary_text.setPlainText(
                current.data(Qt.ItemDataRole.UserRole) if current is not None else ""
            )
        )
        layout.addWidget(self.diary_list, 1)
        layout.addWidget(self.diary_text, 1)
        if self.diary_list.count():
            self.diary_list.setCurrentRow(0)
        else:
            layout.addWidget(self._label("No diary entries yet. She writes one for each day you talk, the day after."))
        layout.addWidget(self._close_buttons())
        return page

    def _self_page(self, items: list[dict[str, str]]) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(self._label("What she has said about herself and promised you, newest first."))
        self.self_list = QListWidget()
        self.self_list.setAccessibleName("The companion's own memories")
        for memory in sorted(items, key=lambda item: item.get("updated_at", ""), reverse=True):
            self.self_list.addItem(f"{memory['summary']}  [{memory.get('category', 'memory')}]")
        layout.addWidget(self.self_list, 1)
        layout.addWidget(self._close_buttons())
        return page

    def _close_buttons(self) -> QDialogButtonBox:
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        return buttons

    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel(text)
        label.setTextFormat(Qt.TextFormat.PlainText)
        return label

    def _refresh(self) -> None:
        selected = self.memories.currentItem()
        index = selected.data(Qt.ItemDataRole.UserRole).index if selected is not None else None
        self.memories.clear()
        current = None
        for row in self.model.filter(self.search.text()):
            item = QListWidgetItem()
            # The default item delegate renders DisplayRole as plain text.
            item.setData(Qt.ItemDataRole.DisplayRole, f"{row.summary}\n{row.timestamp}")
            item.setData(Qt.ItemDataRole.UserRole, row)
            self.memories.addItem(item)
            if row.index == index:
                current = item
        if current is not None:
            self.memories.setCurrentItem(current)
        elif self.memories.count():
            self.memories.setCurrentRow(0)
        else:
            self._select_memory()
            self._show_message("No memories match your search." if self.search.text() else "No memories stored.")

    def _select_memory(self) -> None:
        # This dialog edits one entry at a time; abandoned edits must not be saved later.
        self.model.discard()
        self.message.hide()
        selected = self.memories.currentItem()
        self.editor.setEnabled(selected is not None)
        self.save_button.setEnabled(selected is not None)
        self.editor.setPlainText(selected.data(Qt.ItemDataRole.UserRole).summary if selected is not None else "")

    def save(self) -> None:
        selected = self.memories.currentItem()
        if selected is None:
            return
        row = selected.data(Qt.ItemDataRole.UserRole)
        try:
            self.model.stage_edit(row.index, self.editor.toPlainText())
            message = self.model.save()
        except (OSError, ValueError) as exc:
            self._show_message(f"Could not save memory: {exc}")
            return
        self._refresh()
        self._show_message(message)

    def _show_message(self, text: str) -> None:
        self.message.setText(text)
        self.message.show()
