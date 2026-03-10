#!/usr/bin/env python3

import re
import sys
from typing import Optional
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QGridLayout, QTextEdit, QLabel, QPushButton, QCheckBox,
    QGroupBox, QStatusBar, QMenuBar, QToolTip, QSplitter,
)
from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtGui import QFont, QColor, QPalette, QAction, QShortcut, QKeySequence

ZERO_WIDTH_CHARS = frozenset({
    '\u200B', '\u200C', '\u200D', '\uFEFF',
})
ZERO_WIDTH_TABLE = str.maketrans({ch: None for ch in ZERO_WIDTH_CHARS})

SQL_BREAK_BEFORE = [
    "UNION ALL", "LEFT OUTER JOIN", "RIGHT OUTER JOIN", "FULL OUTER JOIN",
    "LEFT JOIN", "RIGHT JOIN", "FULL JOIN", "INNER JOIN", "CROSS JOIN",
    "CROSS APPLY", "OUTER APPLY", "GROUP BY", "ORDER BY", "PARTITION BY",
    "WITH", "SELECT", "FROM", "WHERE", "HAVING", "UNION", "INTERSECT",
    "MINUS", "EXCEPT", "JOIN", "CONNECT BY", "START WITH", "MODEL",
    "PIVOT", "UNPIVOT", "FETCH FIRST", "OFFSET", "RETURNING",
    "MERGE INTO", "USING", "MATCHED", "INSERT INTO", "VALUES",
    "UPDATE", "DELETE FROM", "SET", "LIMIT",
]

SQL_INDENT_KEYWORDS = {"AND", "OR", "ON"}
SQL_CASE_KEYWORDS = {"WHEN", "THEN", "ELSE"}

SQL_ALL_KEYWORDS = sorted(
    set(SQL_BREAK_BEFORE)
    | SQL_INDENT_KEYWORDS
    | SQL_CASE_KEYWORDS
    | {
        "CASE", "END", "AS", "IN", "IS", "NOT", "NULL", "BETWEEN",
        "LIKE", "EXISTS", "ALL", "ANY", "SOME", "DISTINCT",
        "OVER", "ROWS", "RANGE", "UNBOUNDED", "PRECEDING",
        "FOLLOWING", "CURRENT", "ROW", "DESC", "ASC", "NULLS",
        "FIRST", "LAST", "COUNT", "SUM", "AVG", "MIN", "MAX",
        "NVL", "NVL2", "DECODE", "COALESCE", "CAST", "TRIM",
        "SUBSTR", "REPLACE", "TO_CHAR", "TO_DATE", "TO_NUMBER",
        "SYSDATE", "SYSTIMESTAMP", "DUAL", "ROWNUM", "ROWID",
        "LEVEL", "PRIOR", "NOCYCLE", "SIBLINGS",
        "CREATE", "ALTER", "DROP", "TABLE", "VIEW", "INDEX",
        "SEQUENCE", "TRIGGER", "PROCEDURE", "FUNCTION", "PACKAGE",
        "BEGIN", "DECLARE", "EXCEPTION", "RETURN", "CURSOR",
        "OPEN", "CLOSE", "FETCH", "INTO", "BULK", "COLLECT",
        "FORALL", "LOOP", "WHILE", "FOR", "IF", "ELSIF", "EXIT",
        "CONTINUE", "GRANT", "REVOKE", "ON", "TO", "WITH",
        "GRANT OPTION",
    },
    key=len,
    reverse=True,
)

DEFAULT_INDENT = "    "

class TextUtils:
    @staticmethod
    def split_eol(line: str) -> tuple[str, str]:
        for eol in ('\r\n', '\n', '\r'):
            if line.endswith(eol):
                return line[:-len(eol)], eol
        return line, ''

class BackslashHandler:
    @staticmethod
    def _line_has_backslash(core: str) -> bool:
        return core.rstrip().endswith('\\')

    @staticmethod
    def add_to_line(line: str, only_if_missing: bool = False) -> str:
        core, eol = TextUtils.split_eol(line)
        if only_if_missing and BackslashHandler._line_has_backslash(core):
            return line
        core_stripped = core.rstrip()
        return f"{core_stripped} \\{eol}"

    @staticmethod
    def remove_from_line(line: str) -> str:
        core, eol = TextUtils.split_eol(line)
        stripped = core.rstrip()
        if stripped.endswith('\\'):
            stripped = stripped[:-1].rstrip()
        return f"{stripped}{eol}"

    @classmethod
    def add_to_text(cls, text: str, only_if_missing: bool = False) -> str:
        if not text:
            return text
        lines = text.splitlines(keepends=True)
        result_lines = []
        for line in lines:
            core, eol = TextUtils.split_eol(line)
            if not core.strip():
                result_lines.append(line)
                continue
            result_lines.append(cls.add_to_line(line, only_if_missing))
        return ''.join(result_lines)

    @classmethod
    def remove_from_text(cls, text: str) -> str:
        if not text:
            return text
        lines = text.splitlines(keepends=True)
        result_lines = []
        for line in lines:
            core, eol = TextUtils.split_eol(line)
            cleaned = cls.remove_from_line(line)
            cleaned_core, cleaned_eol = TextUtils.split_eol(cleaned)
            if not cleaned_core.strip() and core.strip() == '\\':
                continue
            result_lines.append(cleaned)
        return ''.join(result_lines)

class TextCleaner:
    _MARKER_PATTERN = re.compile(r'(?<!\w)_[A-Za-z]{1,8}_(?!\w)(?!\s*[.*])')
    _MARKER_NUM_PATTERN = re.compile(r'(?<!\w)_[A-Za-z]{1,8}\d{1,3}_(?!\w)(?!\s*[.*])')
    _BOLD_PATTERN = re.compile(r'\*\*(.+?)\*\*')
    _MULTI_SPACE = re.compile(r'[ \t]+')
    _TRAILING_SPACE = re.compile(r'[ \t]+(\r?\n)')

    @classmethod
    def clean(cls, text: str, remove_markers: bool = True) -> str:
        if not text:
            return text
        text = text.replace('\u00A0', ' ')
        text = text.translate(ZERO_WIDTH_TABLE)
        text = cls._BOLD_PATTERN.sub(r'\1', text)
        if remove_markers:
            text = cls._MARKER_PATTERN.sub('', text)
            text = cls._MARKER_NUM_PATTERN.sub('', text)
        text = cls._MULTI_SPACE.sub(' ', text)
        text = cls._TRAILING_SPACE.sub(r'\1', text)
        return text

class SQLFormatter:
    def __init__(self, indent: str = DEFAULT_INDENT):
        self.indent = indent

    @staticmethod
    def _protect_literals(sql: str) -> tuple[str, list[str]]:
        tokens: list[str] = []
        result: list[str] = []
        i, n = 0, len(sql)
        while i < n:
            ch = sql[i]
            if ch == "'":
                j = i + 1
                while j < n:
                    if sql[j] == "'":
                        if j + 1 < n and sql[j + 1] == "'":
                            j += 2
                            continue
                        j += 1
                        break
                    j += 1
                token = sql[i:j]
                key = f"__LIT{len(tokens)}__"
                tokens.append(token)
                result.append(key)
                i = j
            elif ch == '-' and i + 1 < n and sql[i + 1] == '-':
                j = i + 2
                while j < n and sql[j] != '\n':
                    j += 1
                token = sql[i:j]
                key = f"__LIT{len(tokens)}__"
                tokens.append(token)
                result.append(key)
                i = j
            elif ch == '/' and i + 1 < n and sql[i + 1] == '*':
                j = i + 2
                while j + 1 < n and not (sql[j] == '*' and sql[j + 1] == '/'):
                    j += 1
                j = min(j + 2, n)
                token = sql[i:j]
                key = f"__LIT{len(tokens)}__"
                tokens.append(token)
                result.append(key)
                i = j
            else:
                result.append(ch)
                i += 1
        return ''.join(result), tokens

    @staticmethod
    def _restore_literals(sql: str, tokens: list[str]) -> str:
        for idx, token in enumerate(tokens):
            sql = sql.replace(f"__LIT{idx}__", token, 1)
        return sql

    @staticmethod
    def _normalize_whitespace(sql: str) -> str:
        sql = sql.replace('\r\n', '\n').replace('\r', '\n')
        sql = re.sub(r'[ \t]+', ' ', sql)
        sql = re.sub(r' *\n *', '\n', sql)
        return sql.strip()

    @staticmethod
    def _uppercase_keywords(sql: str) -> str:
        for kw in SQL_ALL_KEYWORDS:
            pattern = r'\b' + re.escape(kw) + r'\b'
            sql = re.sub(pattern, kw, sql, flags=re.IGNORECASE)
        return sql

    @staticmethod
    def _insert_line_breaks(sql: str) -> str:
        for kw in sorted(SQL_BREAK_BEFORE, key=len, reverse=True):
            pattern = r'[ ]+\b' + re.escape(kw) + r'\b'
            sql = re.sub(pattern, '\n' + kw, sql)
        for kw in ('ON', 'AND', 'OR', 'CASE', 'WHEN', 'THEN', 'ELSE', 'END'):
            pattern = r'[ ]+\b' + re.escape(kw) + r'\b'
            sql = re.sub(pattern, '\n' + kw, sql)
        result = []
        paren = 0
        i, n = 0, len(sql)
        while i < n:
            ch = sql[i]
            if ch == '(':
                paren += 1
                result.append(ch)
            elif ch == ')':
                paren = max(0, paren - 1)
                result.append(ch)
            elif ch == ',' and paren == 0:
                result.append(',')
                j = i + 1
                while j < n and sql[j] == ' ':
                    j += 1
                if j < n and sql[j] != '\n':
                    result.append('\n')
                i = j
                continue
            else:
                result.append(ch)
            i += 1
        return ''.join(result)

    def _indent_lines(self, sql: str) -> str:
        lines = sql.splitlines()
        result: list[str] = []
        paren_depth = 0
        case_depth = 0
        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue
            upper = line.upper()
            first_word = upper.split()[0] if upper.split() else ''
            if first_word == 'END' and not any(
                upper.startswith(kw) for kw in ('END LOOP', 'END IF')
            ):
                case_depth = max(0, case_depth - 1)
            if line.startswith(')'):
                paren_depth = max(0, paren_depth - 1)
            level = paren_depth + case_depth
            if first_word in ('AND', 'OR', 'ON'):
                level += 1
            if first_word in SQL_CASE_KEYWORDS or any(
                upper.startswith(kw + ' ') for kw in SQL_CASE_KEYWORDS
            ):
                level += 1
            result.append(f"{self.indent * level}{line}")
            if first_word == 'CASE':
                case_depth += 1
            opens = line.count('(')
            closes = line.count(')')
            net = opens - closes
            if net > 0:
                paren_depth += net
            elif net < 0:
                paren_depth = max(0, paren_depth + net)
        return '\n'.join(result)

    def format(self, sql: str) -> str:
        if not sql or not sql.strip():
            return sql
        protected, tokens = self._protect_literals(sql)
        normalized = self._normalize_whitespace(protected)
        uppercased = self._uppercase_keywords(normalized)
        with_breaks = self._insert_line_breaks(uppercased)
        indented = self._indent_lines(with_breaks)
        result = self._restore_literals(indented, tokens)
        if not result.endswith('\n'):
            result += '\n'
        return result

def strip_backslashes_for_formatting(text: str) -> str:
    lines = text.splitlines(keepends=True)
    result = []
    for line in lines:
        core, eol = TextUtils.split_eol(line)
        stripped = core.rstrip()
        if stripped == '\\':
            continue
        if stripped.endswith('\\'):
            stripped = stripped[:-1].rstrip()
        result.append(f"{stripped}{eol}")
    return ''.join(result)

def transform_text(
    text: str,
    *,
    clean: bool = True,
    format_sql: bool = True,
    remove_markers: bool = True,
    backslash_mode: str = 'none',
    only_if_missing: bool = False,
    indent: str = DEFAULT_INDENT,
) -> str:
    if clean:
        text = TextCleaner.clean(text, remove_markers=remove_markers)
    if format_sql:
        text = strip_backslashes_for_formatting(text)
        formatter = SQLFormatter(indent=indent)
        text = formatter.format(text)
    if backslash_mode == 'add':
        if not format_sql:
            text = BackslashHandler.add_to_text(text, only_if_missing)
        else:
            text = BackslashHandler.add_to_text(text, only_if_missing=False)
    elif backslash_mode == 'remove':
        text = BackslashHandler.remove_from_text(text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text

DARK_STYLE = """
QMainWindow {
    background-color: #2b2b2b;
}
QTextEdit {
    background-color: #1e1e1e;
    color: #d4d4d4;
    border: 1px solid #3c3c3c;
    border-radius: 4px;
    padding: 6px;
    selection-background-color: #264f78;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 11px;
}
QLabel {
    color: #cccccc;
    font-size: 12px;
}
QLabel#title {
    font-weight: bold;
    font-size: 13px;
    color: #e0e0e0;
}
QPushButton {
    background-color: #3c3c3c;
    color: #d4d4d4;
    border: 1px solid #555555;
    border-radius: 4px;
    padding: 6px 14px;
    font-size: 11px;
    min-width: 80px;
}
QPushButton:hover {
    background-color: #4a4a4a;
    border-color: #0078d4;
}
QPushButton:pressed {
    background-color: #0078d4;
    color: white;
}
QPushButton#primary {
    background-color: #0078d4;
    color: white;
    border-color: #0078d4;
    font-weight: bold;
}
QPushButton#primary:hover {
    background-color: #1a8ad4;
}
QPushButton#primary:pressed {
    background-color: #005a9e;
}
QPushButton#danger {
    background-color: #c42b1c;
    color: white;
    border-color: #c42b1c;
}
QPushButton#danger:hover {
    background-color: #d43b2c;
}
QCheckBox {
    color: #cccccc;
    spacing: 6px;
    font-size: 11px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #555555;
    border-radius: 3px;
    background-color: #2b2b2b;
}
QCheckBox::indicator:checked {
    background-color: #0078d4;
    border-color: #0078d4;
}
QCheckBox::indicator:hover {
    border-color: #0078d4;
}
QGroupBox {
    color: #cccccc;
    border: 1px solid #3c3c3c;
    border-radius: 6px;
    margin-top: 8px;
    padding-top: 16px;
    font-size: 11px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}
QStatusBar {
    background-color: #007acc;
    color: white;
    font-size: 11px;
    padding: 2px 8px;
}
QMenuBar {
    background-color: #2b2b2b;
    color: #cccccc;
    border-bottom: 1px solid #3c3c3c;
}
QMenuBar::item:selected {
    background-color: #3c3c3c;
}
QMenu {
    background-color: #2b2b2b;
    color: #cccccc;
    border: 1px solid #3c3c3c;
}
QMenu::item:selected {
    background-color: #0078d4;
    color: white;
}
QMenu::separator {
    height: 1px;
    background-color: #3c3c3c;
    margin: 4px 8px;
}
QSplitter::handle {
    background-color: #3c3c3c;
    width: 3px;
}
QSplitter::handle:hover {
    background-color: #0078d4;
}
"""

class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Ajustar SQL')
        self.setMinimumSize(1100, 650)
        self.resize(1200, 700)
        self._build_ui()
        self._build_menu()
        self._bind_shortcuts()
        self._center_window()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        labels_layout = QHBoxLayout()
        lbl_in = QLabel('📝 Entrada')
        lbl_in.setObjectName('title')
        lbl_out = QLabel('📋 Saída')
        lbl_out.setObjectName('title')
        labels_layout.addWidget(lbl_in)
        labels_layout.addWidget(lbl_out)
        main_layout.addLayout(labels_layout)

        splitter = QSplitter(Qt.Horizontal)

        self.txt_in = QTextEdit()
        self.txt_in.setAcceptRichText(False)
        self.txt_in.setLineWrapMode(QTextEdit.NoWrap)
        self.txt_in.setPlaceholderText('Cole o SQL aqui...')
        font_in = QFont('Consolas', 11)
        font_in.setStyleHint(QFont.Monospace)
        self.txt_in.setFont(font_in)

        self.txt_out = QTextEdit()
        self.txt_out.setAcceptRichText(False)
        self.txt_out.setLineWrapMode(QTextEdit.NoWrap)
        self.txt_out.setReadOnly(True)
        self.txt_out.setPlaceholderText('Resultado aparecerá aqui...')
        font_out = QFont('Consolas', 11)
        font_out.setStyleHint(QFont.Monospace)
        self.txt_out.setFont(font_out)

        splitter.addWidget(self.txt_in)
        splitter.addWidget(self.txt_out)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        main_layout.addWidget(splitter, stretch=1)

        options_group = QGroupBox('Opções')
        options_layout = QGridLayout(options_group)
        options_layout.setSpacing(8)

        self.chk_clean = QCheckBox('Limpar caracteres estranhos (NBSP / zero-width)')
        self.chk_clean.setChecked(True)
        self.chk_clean.setToolTip('Substitui NBSP por espaço e remove chars zero-width')

        self.chk_markers = QCheckBox('Remover marcadores invisíveis (_b_, _var_)')
        self.chk_markers.setChecked(True)
        self.chk_markers.setToolTip('Remove marcadores como _b_, _var_ que são artefatos')

        self.chk_format = QCheckBox('Formatar SQL (Oracle)')
        self.chk_format.setChecked(True)
        self.chk_format.setToolTip('Formata o SQL com indentação e quebras de linha')

        self.chk_only_missing = QCheckBox('Adicionar \\ apenas se ausente')
        self.chk_only_missing.setChecked(False)
        self.chk_only_missing.setToolTip('Não duplica \\ se a linha já termina com um')

        options_layout.addWidget(self.chk_clean, 0, 0)
        options_layout.addWidget(self.chk_markers, 0, 1)
        options_layout.addWidget(self.chk_format, 1, 0)
        options_layout.addWidget(self.chk_only_missing, 1, 1)
        main_layout.addWidget(options_group)

        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(8)

        btn_add = QPushButton('▶ Formatar + \\')
        btn_add.setObjectName('primary')
        btn_add.setToolTip('Ctrl+Enter')
        btn_add.clicked.connect(self.process_add)

        btn_remove = QPushButton('▶ Formatar − \\')
        btn_remove.setToolTip('Ctrl+Shift+Enter')
        btn_remove.clicked.connect(self.process_remove)

        btn_format = QPushButton('▶ Só Formatar')
        btn_format.setToolTip('Ctrl+F')
        btn_format.clicked.connect(self.process_format_only)

        btn_copy = QPushButton('📋 Copiar saída')
        btn_copy.setToolTip('Ctrl+Shift+C')
        btn_copy.clicked.connect(self.copy_output)

        btn_clear = QPushButton('🗑 Limpar')
        btn_clear.setToolTip('Ctrl+L')
        btn_clear.clicked.connect(self.clear_all)

        btn_quit = QPushButton('✖ Sair')
        btn_quit.setObjectName('danger')
        btn_quit.setToolTip('Ctrl+Q')
        btn_quit.clicked.connect(self.close)

        buttons_layout.addWidget(btn_add)
        buttons_layout.addWidget(btn_remove)
        buttons_layout.addWidget(btn_format)
        buttons_layout.addStretch()
        buttons_layout.addWidget(btn_copy)
        buttons_layout.addWidget(btn_clear)
        buttons_layout.addWidget(btn_quit)
        main_layout.addLayout(buttons_layout)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage('Pronto.')

    def _build_menu(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu('Arquivo')
        act_clear = QAction('Limpar tudo', self)
        act_clear.setShortcut('Ctrl+L')
        act_clear.triggered.connect(self.clear_all)
        file_menu.addAction(act_clear)
        file_menu.addSeparator()
        act_quit = QAction('Sair', self)
        act_quit.setShortcut('Ctrl+Q')
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        action_menu = menubar.addMenu('Ações')
        act_add = QAction('Formatar + Adicionar \\', self)
        act_add.setShortcut('Ctrl+Return')
        act_add.triggered.connect(self.process_add)
        action_menu.addAction(act_add)

        act_remove = QAction('Formatar + Remover \\', self)
        act_remove.setShortcut('Ctrl+Shift+Return')
        act_remove.triggered.connect(self.process_remove)
        action_menu.addAction(act_remove)

        action_menu.addSeparator()

        act_format = QAction('Apenas Formatar (sem \\)', self)
        act_format.setShortcut('Ctrl+F')
        act_format.triggered.connect(self.process_format_only)
        action_menu.addAction(act_format)

        action_menu.addSeparator()

        act_copy = QAction('Copiar saída', self)
        act_copy.setShortcut('Ctrl+Shift+C')
        act_copy.triggered.connect(self.copy_output)
        action_menu.addAction(act_copy)

    def _bind_shortcuts(self):
        QShortcut(QKeySequence('Ctrl+Return'), self).activated.connect(self.process_add)
        QShortcut(QKeySequence('Ctrl+Shift+Return'), self).activated.connect(self.process_remove)

    def _center_window(self):
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = (geo.width() - self.width()) // 2 + geo.x()
            y = (geo.height() - self.height()) // 2 + geo.y()
            self.move(x, y)

    def _run(self, backslash_mode: str):
        text = self.txt_in.toPlainText()
        if not text.strip():
            self.txt_out.setPlainText('')
            self.status_bar.showMessage('⚠ Entrada vazia.')
            return
        try:
            result = transform_text(
                text,
                clean=self.chk_clean.isChecked(),
                format_sql=self.chk_format.isChecked(),
                remove_markers=self.chk_markers.isChecked(),
                backslash_mode=backslash_mode,
                only_if_missing=self.chk_only_missing.isChecked(),
            )
            self.txt_out.setPlainText(result)
            lines_in = len(text.splitlines()) if text else 0
            lines_out = len(result.splitlines()) if result else 0
            mode_label = {
                'add': 'Formatado + \\ adicionadas',
                'remove': 'Formatado + \\ removidas',
                'none': 'Formatado (sem alteração de \\)',
            }.get(backslash_mode, 'Processado')
            self.status_bar.showMessage(
                f'✔ {mode_label} — {lines_in} linhas entrada → {lines_out} linhas saída'
            )
        except Exception as e:
            self.status_bar.showMessage(f'✖ Erro: {e}')

    def process_add(self):
        self._run('add')

    def process_remove(self):
        self._run('remove')

    def process_format_only(self):
        self._run('none')

    def copy_output(self):
        text = self.txt_out.toPlainText()
        if not text.strip():
            self.status_bar.showMessage('⚠ Nada para copiar.')
            return
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
        self.status_bar.showMessage('📋 Saída copiada para a área de transferência!')

    def clear_all(self):
        self.txt_in.clear()
        self.txt_out.clear()
        self.status_bar.showMessage('🗑 Limpo.')

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_STYLE)
    window = App()
    window.show()
    sys.exit(app.exec())