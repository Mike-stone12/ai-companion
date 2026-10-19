"""Thin Qt binding for the GUI-independent settings form."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from companion.core.settings_form import SettingsForm


class SettingsDialog(QDialog):
    def __init__(self, form: SettingsForm, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.form = form
        self.editors: dict[str, QCheckBox | QComboBox | QLineEdit] = {}
        self._edited: set[str] = set()
        self.setWindowTitle("Settings")
        self.resize(780, 600)
        # The avatar window styles all descendant line edits for a dark background.
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
        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        rows = QGridLayout(content)
        rows.setColumnStretch(1, 1)

        for row, field in enumerate(form.fields):
            label = self._label(field.description or field.key)
            label.setWordWrap(True)
            if field.kind == "bool":
                editor = QCheckBox()
                # The model exposes booleans as effective configuration text (1/0).
                editor.setChecked(field.value.strip().lower() in {"1", "true", "yes", "on"})
                changed = editor.toggled
            elif field.kind == "choice":
                editor = QComboBox()
                editor.addItems(field.choices)
                value = next(
                    (choice for choice in field.choices if choice.casefold() == field.value.strip().casefold()),
                    None,
                )
                if value is None:
                    # Preserve an invalid current value until the user selects a choice.
                    editor.addItem(field.value)
                    value = field.value
                editor.setCurrentText(value)
                changed = editor.currentTextChanged
            else:
                # Numeric text is parsed and checked by the form, without Qt range limits.
                editor = QLineEdit(field.value)
                changed = editor.textChanged
            editor.setObjectName(field.key)
            editor.setAccessibleName(field.description or field.key)
            if field.description:
                label.setToolTip(field.description)
                editor.setToolTip(field.description)
            label.setBuddy(editor)
            self.editors[field.key] = editor
            changed.connect(lambda _value, key=field.key: self._edited.add(key))
            note = "Overridden by environment" if field.env_overridden else f"Source: {field.source}"
            rows.addWidget(label, row, 0)
            rows.addWidget(editor, row, 1)
            rows.addWidget(self._label(note), row, 2)

        self.errors = self._label("")
        self.errors.setWordWrap(True)
        self.errors.hide()
        rows.addWidget(self.errors, len(form.fields), 0, 1, 3)
        rows.setRowStretch(len(form.fields) + 1, 1)
        scroll.setWidget(content)
        self._scroll = scroll
        layout.addWidget(scroll)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel(text)
        label.setTextFormat(Qt.TextFormat.PlainText)
        return label

    def save(self) -> None:
        # Leave untouched settings alone, including values supplied only by the environment.
        for key, editor in self.editors.items():
            if key not in self._edited:
                continue
            if isinstance(editor, QCheckBox):
                value = editor.isChecked()
            elif isinstance(editor, QComboBox):
                value = editor.currentText()
            else:
                value = editor.text()
            self.form.set_value(key, value)
        if self.form.has_errors():
            self._show_error("\n".join(
                message if key in message else f"{key}: {message}"
                for key, message in self.form.errors.items()
            ))
            return
        try:
            self.form.apply()
        except (OSError, ValueError) as exc:
            self._show_error(f"Could not save settings: {exc}")
            return
        self.accept()

    def _show_error(self, text: str) -> None:
        self.errors.setText(text)
        self.errors.show()
        self._scroll.ensureWidgetVisible(self.errors)
