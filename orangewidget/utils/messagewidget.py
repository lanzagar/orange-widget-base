import sys
import enum
import base64
from itertools import chain
from xml.sax.saxutils import escape
from collections import OrderedDict
from typing import (
    NamedTuple, Tuple, List, Dict, Iterable, Union, Optional, Hashable
)

from AnyQt.QtCore import (
    Qt, QSize, QBuffer, QPropertyAnimation, QEasingCurve, Property
)
from AnyQt.QtGui import QIcon, QPixmap, QPainter
from AnyQt.QtWidgets import (
    QWidget, QLabel, QSizePolicy, QStyle, QHBoxLayout,
    QMenu, QWidgetAction, QStyleOption, QStylePainter, QApplication
)
from AnyQt.QtCore import pyqtSignal as Signal

from orangewidget.utils.buttons import flat_button_hover_background

__all__ = ["Message", "MessagesWidget"]


def image_data(pm):
    # type: (QPixmap) -> str
    """
    Render the contents of the pixmap as a data URL (RFC-2397)

    Parameters
    ----------
    pm : QPixmap

    Returns
    -------
    datauri : str
    """
    pm = QPixmap(pm)
    device = QBuffer()
    assert device.open(QBuffer.ReadWrite)
    pm.save(device, b'png')
    device.close()
    data = bytes(device.data())
    payload = base64.b64encode(data).decode("ascii")
    return "data:image/png;base64," + payload


class Severity(enum.IntEnum):
    """
    An enum defining a severity level.
    """
    #: General informative message.
    Information = 1  # == QMessageBox.Information
    #: A warning message severity.
    Warning = 2  # == QMessageBox.Warning
    #: An error message severity.
    Error = 3  # == QMessageBox.Critical


class Message(
        NamedTuple(
            "Message", [
                ("severity", Severity),
                ("icon", QIcon),
                ("text", str),
                ("informativeText", str),
                ("detailedText", str),
                ("textFormat", Qt.TextFormat)
            ])):
    """
    A stateful message/notification.

    Parameters
    ----------
    severity : `Severity`
        Severity level (default: :attr:`Severity.Information`).
    icon : QIcon
        Associated icon. If empty the `QStyle.standardIcon` will be used based
        on severity.
    text : str
        Short message text.
    informativeText : str
        Extra informative text to append to `text` (space permitting).
    detailedText : str
        Extra detailed text (e.g. exception traceback)
    textFormat : Qt.TextFormat
        If `Qt.RichText` then the contents of `text`, `informativeText` and
        `detailedText` will be rendered as html instead of plain text.

    """
    #: Alias for :class:`.Severity`
    Severity = Severity

    #: Alias for :attr:`Severity.Information`
    Information = Severity.Information
    #: Alias for :attr:`Severity.Warning`
    Warning = Severity.Warning
    #: Alias for :attr:`Severity.Error`
    Error = Severity.Error

    def __new__(cls, severity=Severity.Information, icon=QIcon(), text="",
                informativeText="", detailedText="", textFormat=Qt.PlainText):
        return super().__new__(cls, Severity(severity), QIcon(icon), text,
                               informativeText, detailedText, textFormat)

    def __bool__(self):
        return not self.isEmpty()

    def asHtml(self, includeShortText=True):
        # type: () -> str
        """
        Render the message as an HTML fragment.
        """
        if self.textFormat == Qt.RichText:
            render = lambda t: t
        else:
            render = lambda t: ('<span style="white-space: pre">{}</span>'
                                .format(escape(t)))

        def iconsrc(message, size=12):
            # type: (Message) -> str
            """
            Return an image src url for message icon.
            """
            icon = message_icon(message)
            pm = icon.pixmap(size, size)
            return image_data(pm)

        imgsize = 12
        parts = [
            ('<div class="message {}">'
             .format(self.severity.name.lower()))
        ]
        if includeShortText:
            parts += [('<div class="field-text">'
                       '<img src="{iconurl}" width="{imgsize}" height="{imgsize}" />'
                       ' {text}'
                       '</div>'
                       .format(iconurl=iconsrc(self, size=imgsize * 2),
                               imgsize=imgsize,
                               text=render(self.text)))]
        if self.informativeText:
            parts += ['<div class="field-informative-text">{}</div>'
                      .format(render(self.informativeText))]
        if self.detailedText:
            parts += ['<div class="field-detailed-text">{}</div>'
                      .format(render(self.detailedText))]
        parts += ['</div>']
        return "\n".join(parts)

    def isEmpty(self):
        # type: () -> bool
        """
        Is this message instance empty (has no text or icon)
        """
        return (not self.text and self.icon.isNull() and
                not self.informativeText and not self.detailedText)

    @property
    def icon(self):
        return QIcon(super().icon)

    def __eq__(self, other):
        if isinstance(other, Message):
            return (self.severity == other.severity and
                    self.icon.cacheKey() == other.icon.cacheKey() and
                    self.text == other.text and
                    self.informativeText == other.informativeText and
                    self.detailedText == other.detailedText and
                    self.textFormat == other.textFormat)
        else:
            return False


def standard_pixmap(severity):
    # type: (Severity) -> QStyle.StandardPixmap
    mapping = {
        Severity.Information: QStyle.SP_MessageBoxInformation,
        Severity.Warning: QStyle.SP_MessageBoxWarning,
        Severity.Error: QStyle.SP_MessageBoxCritical,
    }
    return mapping[severity]


def message_icon(message, style=None):
    # type: (Message, Optional[QStyle]) -> QIcon
    """
    Return the resolved icon for the message.

    If `message.icon` is a valid icon then it is used. Otherwise the
    appropriate style icon is used based on the `message.severity`

    Parameters
    ----------
    message : Message
    style : Optional[QStyle]

    Returns
    -------
    icon : QIcon
    """
    if style is None and QApplication.instance() is not None:
        style = QApplication.style()
    if message.icon.isNull():
        icon = style.standardIcon(standard_pixmap(message.severity))
    else:
        icon = message.icon
    return icon


def categorize(messages):
    # type: (List[Message]) -> Tuple[Optional[Message], List[Message], List[Message], List[Message]]
    """
    Categorize the messages by severity picking the message leader if
    possible.

    The leader is a message with the highest severity iff it is the only
    representative of that severity.

    Parameters
    ----------
    messages : List[Messages]

    Returns
    -------
    r : Tuple[Optional[Message], List[Message], List[Message], List[Message]]
    """
    errors = [m for m in messages if m.severity == Severity.Error]
    warnings = [m for m in messages if m.severity == Severity.Warning]
    info = [m for m in messages if m.severity == Severity.Information]
    lead = None
    if len(errors) == 1:
        lead = errors.pop(-1)
    elif not errors and len(warnings) == 1:
        lead = warnings.pop(-1)
    elif not errors and not warnings and len(info) == 1:
        lead = info.pop(-1)
    return lead, errors, warnings, info


# pylint: disable=too-many-branches
def summarize(messages):
    # type: (List[Message]) -> Message
    """
    Summarize a list of messages into a single message instance

    Parameters
    ----------
    messages: List[Message]

    Returns
    -------
    message: Message
    """
    if not messages:
        return Message()

    if len(messages) == 1:
        return messages[0]

    lead, errors, warnings, info = categorize(messages)
    severity = Severity.Information
    icon = QIcon()
    leading_text = ""
    text_parts = []
    if lead is not None:
        severity = lead.severity
        icon = lead.icon
        leading_text = lead.text
    elif errors:
        severity = Severity.Error
    elif warnings:
        severity = Severity.Warning

    def format_plural(fstr, items, *args, **kwargs):
        return fstr.format(len(items), *args,
                           s="s" if len(items) != 1 else "",
                           **kwargs)
    if errors:
        text_parts.append(format_plural("{} error{s}", errors))
    if warnings:
        text_parts.append(format_plural("{} warning{s}", warnings))
    if info:
        if not (errors and warnings and lead):
            text_parts.append(format_plural("{} message{s}", info))
        else:
            text_parts.append(format_plural("{} other", info))

    if leading_text:
        text = leading_text
        if text_parts:
            text = text + " (" + ", ".join(text_parts) + ")"
    else:
        text = ", ".join(text_parts)
    detailed = "<hr/>".join(m.asHtml()
                            for m in chain([lead], errors, warnings, info)
                            if m is not None and not m.isEmpty())
    return Message(severity, icon, text, detailedText=detailed,
                   textFormat=Qt.RichText)


class ElidingLabel(QLabel):
    def __init__(self, elide=False, **kwargs):
        super().__init__(**kwargs)
        self.__elide = elide
        self.__originalText = ""

    def resizeEvent(self, event):
        if self.__elide:
            self.__setElidedText(self.__originalText)

    def __setElidedText(self, text):
        fm = self.fontMetrics()

        # Qt sometimes elides even when text width == target width
        width = self.width() + 1

        elided = fm.elidedText(text, Qt.ElideRight, width)
        super().setText(elided)

    def setText(self, text):
        self.__originalText = text
        if self.__elide:
            self.__setElidedText(text)
        else:
            super().setText(text)

    def sizeHint(self):
        fm = self.fontMetrics()
        w = fm.horizontalAdvance(self.__originalText)
        h = super().minimumSizeHint().height()
        return QSize(w, h)

    def setElide(self, enabled):
        if self.__elide == enabled:
            return

        self.__elide = enabled
        if enabled:
            self.__setElidedText(self.__originalText)
        else:
            super().setText(self.__originalText)


class MessageWidget(QWidget):
    """
    An iconified message display area.

    `IconifiedMessage` displays a short message along with an icon.
    """
    #: Signal emitted when an embedded html link is clicked
    #: (if `openExternalLinks` is `False`).
    linkActivated = Signal(str)

    #: Signal emitted when an embedded html link is hovered.
    linkHovered = Signal(str)

    Message = Message

    def __init__(self, parent=None, openExternalLinks=False, elideText=False,
                 defaultStyleSheet="", **kwargs):
        kwargs.setdefault(
            "sizePolicy",
            QSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum)
        )
        super().__init__(parent, **kwargs)
        self._openExternalLinks = openExternalLinks  # type: bool
        #: The full (joined all messages text - rendered as html), displayed
        #: in a tooltip.
        self.message = None
        #: Leading icon
        self.__iconwidget = IconWidget(
            sizePolicy=QSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        )
        #: Inline  message text
        self.__textlabel = ElidingLabel(
            wordWrap=False,
            textInteractionFlags=Qt.LinksAccessibleByMouse,
            openExternalLinks=self._openExternalLinks,
            sizePolicy=QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum),
            elide=elideText
        )
        self.__textlabel.linkActivated.connect(self.linkActivated)
        self.__textlabel.linkHovered.connect(self.linkHovered)
        self.setLayout(QHBoxLayout())
        self.layout().setContentsMargins(2, 1, 2, 1)
        self.layout().setSpacing(0)
        self.layout().addWidget(self.__iconwidget, alignment=Qt.AlignLeft)
        self.layout().addSpacing(4)
        self.layout().addWidget(self.__textlabel)
        self.__textlabel.setAttribute(Qt.WA_MacSmallSize)
        self.__defaultStyleSheet = defaultStyleSheet

        self.anim = QPropertyAnimation(
            self.__iconwidget, b"opacity", self.__iconwidget)
        self.anim.setDuration(350)
        self.anim.setStartValue(1)
        self.anim.setKeyValueAt(0.5, 0)
        self.anim.setEndValue(1)
        self.anim.setEasingCurve(QEasingCurve.OutQuad)
        self.anim.setLoopCount(2)

    def setMessage(self, message):
        self.message = message
        self.ensurePolished()
        icon = message_icon(message)
        self.__iconwidget.setIcon(icon)
        self.__iconwidget.setVisible(not (message.isEmpty() or icon.isNull()))
        self.__textlabel.setTextFormat(message.textFormat)
        self.__textlabel.setText(message.text)
        self.__textlabel.setVisible(bool(message.text))
        self.setToolTip(self._styled(message.asHtml()))
        self.anim.start(QPropertyAnimation.KeepWhenStopped)
        self.layout().activate()

    def sizeHint(self):
        sh = super().sizeHint()
        h = self.style().pixelMetric(QStyle.PM_SmallIconSize)
        if not self.message:
            sh.setWidth(0)
        return sh.expandedTo(QSize(0, h + 2))

    def minimumSizeHint(self):
        msh = super().minimumSizeHint()
        h = self.style().pixelMetric(QStyle.PM_SmallIconSize)
        if not self.message:
            msh.setWidth(0)
        else:
            msh.setWidth(h + 2)
        return msh.expandedTo(QSize(0, h + 2))

    def setOpenExternalLinks(self, state):
        # type: (bool) -> None
        """
        If `True` then `linkActivated` signal will be emitted when the user
        clicks on an html link in a message, otherwise links are opened
        using `QDesktopServices.openUrl`
        """
        # TODO: update popup if open
        self._openExternalLinks = state
        self.__textlabel.setOpenExternalLinks(state)

    def openExternalLinks(self):
        # type: () -> bool
        """
        """
        return self._openExternalLinks

    def setDefaultStyleSheet(self, css):
        # type: (str) -> None
        """
        Set a default css to apply to the rendered text.

        Parameters
        ----------
        css : str
            A css style sheet as supported by Qt's Rich Text support.

        Note
        ----
        Not to be confused with `QWidget.styleSheet`

        See Also
        --------
        `Supported HTML Subset`_

        .. _`Supported HTML Subset`:
            http://doc.qt.io/qt-5/richtext-html-subset.html
        """
        if self.__defaultStyleSheet != css:
            self.__defaultStyleSheet = css

    def defaultStyleSheet(self):
        """
        Returns
        -------
        css : str
            The current style sheet
        """
        return self.__defaultStyleSheet

    def flashIcon(self):
        self.anim.start(QPropertyAnimation.KeepWhenStopped)

    def _styled(self, html):
        # Prepend css style sheet before a html fragment.
        if self.__defaultStyleSheet.strip():
            return f"<style>{escape(self.__defaultStyleSheet)}</style>\n{html}"
        else:
            return html

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()

    def changeEvent(self, event):
        super().changeEvent(event)
        self.update()

    def paintEvent(self, event):
        if not self.message:
            return

        opt = QStyleOption()
        opt.initFrom(self)
        if opt.state & (QStyle.State_MouseOver | QStyle.State_HasFocus):
            p = QPainter(self)
            flat_button_hover_background(p, opt)


class MessagesWidget(MessageWidget):
    """
    An iconified multiple message display area.

    `MessagesWidget` displays a short message along with an icon. If there
    are multiple messages they are summarized. The user can click on the
    widget to display the full message text in a popup view.
    """
    Severity = Severity
    #: General informative message.
    Information = Severity.Information
    #: A warning message severity.
    Warning = Severity.Warning
    #: An error message severity.
    Error = Severity.Error

    def __init__(self, parent=None, openExternalLinks=False, elideText=False,
                 defaultStyleSheet="", **kwargs):
        super().__init__(parent, openExternalLinks, elideText,
                         defaultStyleSheet, **kwargs)
        self.__messages = OrderedDict()  # type: Dict[Hashable, Message]

    def setMessage(self, message_id, message):
        # type: (Hashable, Message) -> None
        """
        Add a `message` for `message_id` to the current display.

        Note
        ----
        Set an empty `Message` instance to clear the message display but
        retain the relative ordering in the display should a message for
        `message_id` reactivate.
        """
        self.__messages[message_id] = message
        self.__update()

    def removeMessage(self, message_id):
        # type: (Hashable) -> None
        """
        Remove message for `message_id` from the display.

        Note
        ----
        Setting an empty `Message` instance will also clear the display,
        however the relative ordering of the messages will be retained,
        should the `message_id` 'reactivate'.
        """
        del self.__messages[message_id]
        self.__update()

    def setMessages(self, messages):
        # type: (Union[Iterable[Tuple[Hashable, Message]], Dict[Hashable, Message]]) -> None
        """
        Set multiple messages in a single call.
        """
        messages = OrderedDict(messages)
        self.__messages.update(messages)
        self.__update()

    def clear(self):
        # type: () -> None
        """
        Clear all messages.
        """
        self.__messages.clear()
        self.__update()

    def messages(self):
        # type: () -> List[Message]
        """
        Return all set messages.

        Returns
        -------
        messages: `List[Message]`
        """
        return list(self.__messages.values())

    def summarize(self):
        # type: () -> Message
        """
        Summarize all the messages into a single message.
        """
        messages = [m for m in self.__messages.values() if not m.isEmpty()]
        if messages:
            return summarize(messages)
        else:
            return Message()

    def flashIcon(self):
        for message in self.messages():
            if message.severity != Severity.Information:
                self.anim.start(QPropertyAnimation.KeepWhenStopped)
                break

    def __update(self):
        super().setMessage(self.summarize())

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            message = self.message
            if message:
                popup = QMenu(self)
                label = QLabel(
                    self, textInteractionFlags=Qt.TextBrowserInteraction,
                    openExternalLinks=self._openExternalLinks,
                )
                label.setContentsMargins(4, 4, 4, 4)
                label.setText(self._styled(message.asHtml()))

                label.linkActivated.connect(self.linkActivated)
                label.linkHovered.connect(self.linkHovered)
                action = QWidgetAction(popup)
                action.setDefaultWidget(label)
                popup.addAction(action)
                popup.popup(event.globalPos(), action)
                event.accept()
            return
        else:
            super().mousePressEvent(event)


class InOutStateWidget(MessageWidget):
    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        else:
            super().mousePressEvent(event)


class IconWidget(QWidget):
    """
    A widget displaying an `QIcon`
    """
    def __init__(self, parent=None, icon=QIcon(), iconSize=QSize(), **kwargs):
        sizePolicy = kwargs.pop("sizePolicy", QSizePolicy(QSizePolicy.Fixed,
                                                          QSizePolicy.Fixed))
        super().__init__(parent, **kwargs)
        self._opacity = 1
        self.__icon = QIcon(icon)
        self.__iconSize = QSize(iconSize)
        self.setSizePolicy(sizePolicy)

    def setIcon(self, icon):
        # type: (QIcon) -> None
        if self.__icon != icon:
            self.__icon = QIcon(icon)
            self.updateGeometry()
            self.update()

    def getOpacity(self):
        return self._opacity

    def setOpacity(self, o):
        self._opacity = o
        self.update()

    opacity = Property(float, fget=getOpacity, fset=setOpacity)

    def icon(self):
        # type: () -> QIcon
        return QIcon(self.__icon)

    def iconSize(self):
        # type: () -> QSize
        if not self.__iconSize.isValid():
            size = self.style().pixelMetric(QStyle.PM_ButtonIconSize)
            return QSize(size, size)
        else:
            return QSize(self.__iconSize)

    def setIconSize(self, iconSize):
        # type: (QSize) -> None
        if self.__iconSize != iconSize:
            self.__iconSize = QSize(iconSize)
            self.updateGeometry()
            self.update()

    def sizeHint(self):
        sh = self.iconSize()
        m = self.contentsMargins()
        return QSize(sh.width() + m.left() + m.right(),
                     sh.height() + m.top() + m.bottom())

    def paintEvent(self, event):
        painter = QStylePainter(self)
        painter.setOpacity(self._opacity)
        opt = QStyleOption()
        opt.initFrom(self)
        painter.drawPrimitive(QStyle.PE_Widget, opt)
        if not self.__icon.isNull():
            rect = self.contentsRect()
            if opt.state & QStyle.State_MouseOver:
                mode = QIcon.Active
            elif opt.state & QStyle.State_Enabled:
                mode = QIcon.Normal
            else:
                mode = QIcon.Disabled
            self.__icon.paint(painter, rect, Qt.AlignCenter, mode, QIcon.Off)
        painter.end()


def main(argv=None):  # pragma: no cover
    from AnyQt.QtWidgets import QVBoxLayout, QCheckBox, QStatusBar
    app = QApplication(list(argv) if argv else [])
    l1 = QVBoxLayout()
    l1.setContentsMargins(0, 0, 0, 0)
    blayout = QVBoxLayout()
    l1.addLayout(blayout)
    sb = QStatusBar()

    w = QWidget()
    w.setLayout(l1)
    messages = [
        Message(Severity.Error, text="Encountered a HCF",
                detailedText="<em>AAA! It burns.</em>",
                textFormat=Qt.RichText),
        Message(Severity.Warning,
                text="ACHTUNG!",
                detailedText=(
                    "<div style=\"color: red\">DAS KOMPUTERMASCHINE IST "
                    "NICHT FÜR DER GEFINGERPOKEN</div>"
                ),
                textFormat=Qt.RichText),
        Message(Severity.Information,
                text="The rain in spain falls mostly on the plain",
                informativeText=(
                    "<a href=\"https://www.google.si/search?q="
                    "Average+Yearly+Precipitation+in+Spain\">Link</a>"
                ),
                textFormat=Qt.RichText),
        Message(Severity.Error,
                text="I did not do this!",
                informativeText="The computer made suggestions...",
                detailedText="... and the default options was yes."),
        Message(),
    ]
    mw = MessagesWidget(openExternalLinks=True)
    for i, m in enumerate(messages):
        cb = QCheckBox(m.text)

        def toogled(state, i=i, m=m):
            if state:
                mw.setMessage(i, m)
            else:
                mw.removeMessage(i)
        cb.toggled[bool].connect(toogled)
        blayout.addWidget(cb)

    sb.addWidget(mw)
    w.layout().addWidget(sb, 0)
    w.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv))
