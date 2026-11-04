"""Thin Qt binding for the GUI-independent settings form."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from companion.core.api_key import ApiKeyStore, KeychainUnavailable, describe_status
from companion.core.settings_form import SettingsForm


class SettingsDialog(QDialog):
    def __init__(
        self, form: SettingsForm, parent: QWidget | None = None, *, api_keys: ApiKeyStore | None = None,
        extra_keys: list[tuple[str, ApiKeyStore]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.form = form
        self.api_keys = api_keys
        # Other services' keys (pictures, voice), each in its own keychain entry.
        self.extra_keys = extra_keys or []
        self.changed_accounts: set[str] = set()
        # Set when the keychain entry was saved or removed, even if the dialog is cancelled.
        self.api_key_changed = False
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
        if api_keys is not None:
            layout.addWidget(self._build_api_key_box())
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

    def _build_api_key_box(self) -> QGroupBox:
        box = QGroupBox("API keys")
        rows = QVBoxLayout(box)
        self.key_rows: list[_KeyRow] = []
        for title, store in [("Chat", self.api_keys), *self.extra_keys]:
            row = _KeyRow(title, store, self._key_changed)
            self.key_rows.append(row)
            rows.addLayout(row.layout)
        # The chat row's widgets, as before.
        chat = self.key_rows[0]
        self.api_key_status, self.api_key_input = chat.status, chat.input
        self.api_key_save, self.api_key_clear, self.api_key_message = chat.save_button, chat.clear_button, chat.message
        return box

    def _key_changed(self, account: str) -> None:
        self.api_key_changed = True
        self.changed_accounts.add(account)

    def save_api_key(self) -> None:
        self.key_rows[0].save()

    def clear_api_key(self) -> None:
        self.key_rows[0].clear()

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


class _KeyRow:
    """Status, a password field that is never prefilled, Save and Remove for one keychain entry."""

    def __init__(self, title: str, store: ApiKeyStore, changed) -> None:
        self.title = title
        self.store = store
        self.changed = changed
        self.layout = QVBoxLayout()
        self.status = SettingsDialog._label("")
        self.layout.addWidget(self.status)
        line = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setObjectName("API_KEY_INPUT" if store.account == "OPENAI_API_KEY" else f"{store.account}_INPUT")
        self.input.setEchoMode(QLineEdit.EchoMode.Password)
        self.input.setPlaceholderText(f"Paste a new {title.lower()} key to store it in the system keychain")
        self.input.setAccessibleName(f"New {title.lower()} API key")
        self.save_button = QPushButton("Save to keychain")
        self.save_button.clicked.connect(self.save)
        self.clear_button = QPushButton("Remove from keychain")
        self.clear_button.clicked.connect(self.clear)
        line.addWidget(self.input, 1)
        line.addWidget(self.save_button)
        line.addWidget(self.clear_button)
        self.layout.addLayout(line)
        self.message = SettingsDialog._label("")
        self.message.setWordWrap(True)
        self.layout.addWidget(self.message)
        self.refresh()

    def refresh(self, message: str = "") -> None:
        resolved = self.store.resolve()
        available = self.store.available
        self.status.setText(f"{self.title} key: {describe_status(resolved, available)}")
        self.input.setEnabled(available)
        self.save_button.setEnabled(available)
        self.clear_button.setEnabled(available and resolved.source == "keychain")
        self.message.setText(message)
        self.message.setVisible(bool(message))

    def save(self) -> None:
        try:
            self.store.save(self.input.text())
        except (ValueError, KeychainUnavailable) as exc:
            self.refresh(str(exc))
            return
        finally:
            self.input.clear()
        self.changed(self.store.account)
        self.refresh("Saved. It is used right away.")

    def clear(self) -> None:
        try:
            self.store.clear()
        except KeychainUnavailable as exc:
            self.refresh(str(exc))
            return
        self.changed(self.store.account)
        self.refresh("Removed from the keychain.")
