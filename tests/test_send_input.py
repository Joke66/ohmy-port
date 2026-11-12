"""发送输入框回归测试：Qt 默认自动补全不能改写用户输入。

背景：可编辑 QComboBox 会被 Qt 自动安装大小写不敏感的 QCompleter（内联补全），
输入 "P" 且历史里有 "p" 时，回车会把输入替换成 "p" 再发送。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox

from serial_tool import _disable_combo_autocomplete


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _send_combo(history: list[str]) -> QComboBox:
    combo = QComboBox()
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.NoInsert)
    for text in history:
        combo.addItem(text)
    _disable_combo_autocomplete(combo)
    combo.show()
    return combo


def _type_and_enter(combo: QComboBox, text: str) -> str:
    edit = combo.lineEdit()
    edit.setFocus()
    edit.selectAll()
    QTest.keyClicks(edit, text)
    QTest.keyClick(edit, Qt.Key_Return)
    QApplication.processEvents()
    return combo.currentText()


def test_completer_removed(qapp):
    assert _send_combo(["p"]).lineEdit().completer() is None


def test_uppercase_not_replaced_by_lowercase_history(qapp):
    combo = _send_combo(["p"])
    assert _type_and_enter(combo, "P") == "P"


def test_prefix_not_expanded_to_history_item(qapp):
    combo = _send_combo(["ping"])
    assert _type_and_enter(combo, "PI") == "PI"


def test_history_still_available(qapp):
    combo = _send_combo(["p", "ping"])
    assert [combo.itemText(i) for i in range(combo.count())] == ["p", "ping"]
