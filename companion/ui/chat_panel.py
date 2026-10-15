from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, QRect, Qt
from PyQt6.QtWidgets import QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget

MAX_BUBBLES = 60
BUBBLE_WIDTH_RATIO = 0.8
ROW_MARGIN = 4
TEXT_SLACK = 4  # font rounding between measurement and rendering
# (horizontal, vertical) padding + border per bubble kind; must match the window stylesheet.
CHROME = {"userBubble": (24, 16), "assistantBubble": (24, 16), "noticeBubble": (20, 8)}
ALIGNMENT = {
    "user": Qt.AlignmentFlag.AlignRight,
    "assistant": Qt.AlignmentFlag.AlignLeft,
    "notice": Qt.AlignmentFlag.AlignHCenter,
}


class ChatPanel(QScrollArea):
    """Scrollable chat bubbles: user on the right, companion on the left, notices centered."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chatPanel")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        container.setObjectName("chatContainer")
        self.rows = QVBoxLayout(container)
        self.rows.setContentsMargins(ROW_MARGIN, ROW_MARGIN, ROW_MARGIN, ROW_MARGIN)
        self.rows.setSpacing(6)
        self.rows.addStretch(1)  # keeps bubbles anchored to the bottom
        self.setWidget(container)

        self.bubbles: list[QLabel] = []
        self.current_reply: QLabel | None = None
        self.verticalScrollBar().rangeChanged.connect(self.scroll_to_bottom)
        # The viewport, not the scroll area, narrows when the scrollbar appears; refit on its resize.
        self.viewport().installEventFilter(self)

    def load(self, turns: list[tuple[str, str]]) -> None:
        for role, text in turns[-MAX_BUBBLES:]:
            self.add_bubble(text, role)

    def add_user(self, text: str) -> None:
        self.add_bubble(text, "user")

    def add_notice(self, text: str) -> None:
        self.add_bubble(text, "notice")

    def update_reply(self, text: str) -> None:
        if self.current_reply is None:
            self.current_reply = self.add_bubble(text, "assistant")
        else:
            self.current_reply.setText(text)
            self.fit(self.current_reply)

    def end_reply(self) -> None:
        self.current_reply = None

    def add_bubble(self, text: str, kind: str) -> QLabel:
        label = QLabel(text)
        # Model output must never be interpreted as HTML (QLabel auto-detects rich text).
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setObjectName(f"{kind}Bubble")
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.rows.addWidget(label, 0, ALIGNMENT[kind])
        self.bubbles.append(label)
        self.fit(label)
        self.trim()
        return label

    # Size each bubble explicitly. Left to the layout, a word-wrapping QLabel shrinks to its
    # narrowest wrap, and QLabel.heightForWidth ignores the stylesheet padding.
    def fit(self, label: QLabel) -> None:
        label.ensurePolished()
        metrics = label.fontMetrics()
        chrome_x, chrome_y = CHROME[label.objectName()]
        text = label.text()
        natural = max((metrics.horizontalAdvance(line) for line in text.splitlines()), default=0) + TEXT_SLACK
        width = min(natural + chrome_x, self.bubble_width())
        bounds = metrics.boundingRect(QRect(0, 0, width - chrome_x, 1_000_000), Qt.TextFlag.TextWordWrap, text)
        label.setFixedSize(width, bounds.height() + chrome_y)

    def trim(self) -> None:
        while len(self.bubbles) > MAX_BUBBLES:
            oldest = self.bubbles.pop(0)
            self.rows.takeAt(1)  # index 0 is the anchoring stretch
            oldest.deleteLater()
            if oldest is self.current_reply:
                self.current_reply = None

    def bubble_width(self) -> int:
        return max(160, int((self.viewport().width() - 2 * ROW_MARGIN) * BUBBLE_WIDTH_RATIO))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # type: ignore[override]
        if watched is self.viewport() and event.type() == QEvent.Type.Resize:
            for bubble in self.bubbles:
                self.fit(bubble)
        return super().eventFilter(watched, event)

    def scroll_to_bottom(self, _minimum: int = 0, maximum: int = 0) -> None:
        self.verticalScrollBar().setValue(maximum or self.verticalScrollBar().maximum())
