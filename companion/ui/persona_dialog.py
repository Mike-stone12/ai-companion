"""Edit the companion's persona: pick a preset, then adjust any field."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from companion.core.persona import CUSTOM_ID, FIELD_LIMITS, Persona, PersonaProvider
from companion.core.schedule import format_schedule, parse_schedule

FIELD_LABELS = {
    "name": "Companion's name",
    "user_name": "What it calls you",
    "relationship": "Relationship to you",
    "personality": "Personality",
    "speaking_style": "Speaking style",
    "background": "Background",
}
PLACEHOLDERS = {
    "name": "Leave empty to name the companion in chat",
    "user_name": "Leave empty to use no particular name",
}
FIRST_RUN_INTRO = (
    "Who should your companion be? The default is a childhood friend who grew up next door. "
    "Keep it, or describe the personality and character you want. You can change this later "
    "with Persona… in the right-click menu."
)
EDIT_INTRO = "Describe who your companion is. Changes apply from the next reply."
SCHEDULE_HELP = (
    "One time block per line: HH:MM-HH:MM [kind] activity. Kinds: busy, drowsy, asleep "
    "(leave it out for free time). Blocks may cross midnight. Asleep, the companion starts "
    "nothing but reminders and still answers, sleepily."
)


class PersonaDialog(QDialog):
    def __init__(
        self, provider: PersonaProvider, current: Persona, parent: QWidget | None = None, *,
        first_run: bool = False,
    ) -> None:
        super().__init__(parent)
        self.provider = provider
        self.current = current
        self.base = current
        self.setWindowTitle("Persona")
        self.resize(640, 760)
        # The avatar window styles descendant editors for a dark background.
        self.setStyleSheet("""
            QLineEdit, QPlainTextEdit {
                color: palette(text);
                background-color: palette(base);
                border: 1px solid palette(mid);
                border-radius: 2px;
                min-height: 0px;
                padding: 4px;
            }
            QLineEdit { min-height: 20px; }
        """)
        layout = QVBoxLayout(self)
        intro = QLabel(FIRST_RUN_INTRO if first_run else EDIT_INTRO)
        intro.setTextFormat(Qt.TextFormat.PlainText)
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.preset = QComboBox()
        self.preset.setObjectName("PERSONA_PRESET")
        for persona in provider.presets():
            self.preset.addItem(persona.title, persona.id)
        if current.id == CUSTOM_ID:
            self.preset.addItem("Custom", CUSTOM_ID)
        index = self.preset.findData(current.id)
        self.preset.setCurrentIndex(max(index, 0))
        self.preset.currentIndexChanged.connect(self.load_preset)
        form.addRow(self._label("Start from"), self.preset)

        self.editors: dict[str, QLineEdit | QPlainTextEdit] = {}
        for name, label in FIELD_LABELS.items():
            if name in PLACEHOLDERS:
                editor = QLineEdit()
                editor.setMaxLength(FIELD_LIMITS[name])
                editor.setPlaceholderText(PLACEHOLDERS[name])
            else:
                editor = QPlainTextEdit()
                editor.setTabChangesFocus(True)
                editor.setFixedHeight(76)
            editor.setObjectName(f"PERSONA_{name.upper()}")
            editor.setAccessibleName(label)
            self.editors[name] = editor
            form.addRow(self._label(label), editor)
        self.schedule = QPlainTextEdit()
        self.schedule.setObjectName("PERSONA_SCHEDULE")
        self.schedule.setAccessibleName("Daily routine")
        self.schedule.setTabChangesFocus(True)
        self.schedule.setFixedHeight(130)
        self.schedule.setToolTip(SCHEDULE_HELP)
        form.addRow(self._label("Daily routine"), self.schedule)
        help_label = self._label(SCHEDULE_HELP)
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color: palette(mid); font-size: 11px;")
        form.addRow("", help_label)
        layout.addLayout(form)
        self.error = self._label("")
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #c62828;")
        self.error.hide()
        layout.addWidget(self.error)
        self.fill(current)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        if first_run:
            buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Keep default")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel(text)
        label.setTextFormat(Qt.TextFormat.PlainText)
        return label

    def fill(self, persona: Persona) -> None:
        for name, editor in self.editors.items():
            value = getattr(persona, name)
            if isinstance(editor, QLineEdit):
                editor.setText(value)
            else:
                editor.setPlainText(value)
        self.schedule.setPlainText(format_schedule(persona.schedule))

    def load_preset(self, _index: int = 0) -> None:
        persona_id = self.preset.currentData()
        preset = self.current if persona_id == CUSTOM_ID else self.provider.get(persona_id)
        if preset is not None:
            self.base = preset
            self.fill(preset)

    def persona(self) -> Persona:
        """The edited persona; a preset left unchanged keeps its id."""
        values = {
            name: editor.text() if isinstance(editor, QLineEdit) else editor.toPlainText()
            for name, editor in self.editors.items()
        }
        return self.base.with_fields(**values, schedule=parse_schedule(self.schedule.toPlainText()))

    def accept(self) -> None:
        try:
            self.persona()
        except ValueError as exc:
            self.error.setText(str(exc))
            self.error.show()
            return
        super().accept()
