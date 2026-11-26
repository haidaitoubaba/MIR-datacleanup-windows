"""Mac/Windows desktop interface for staged MIR cleanup."""
from __future__ import annotations
import copy
import threading
from contextlib import contextmanager
import sys
import traceback
from datetime import datetime
from pathlib import Path
from string import Template
import numpy as np
from matplotlib.figure import Figure
from matplotlib.widgets import RectangleSelector, LassoSelector
from matplotlib.path import Path as PlotPath
from matplotlib.markers import MarkerStyle
import mir_cleanup_session as engine
import mir_cleanup_auto as auto
import soil_mir_data_cleanup as core
from PySide6 import QtCore, QtGui, QtWidgets as W
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT


APPEARANCE_LABELS = {'light': 'Light', 'night': 'Night', 'system': 'System'}
APPEARANCE_KEY = 'appearance/mode'
THEMES = {
    'light': dict(surface='#ffffff', panel='#f5f8f8', ink='#172c30', muted='#4a6165',
                  line='#d8e2e2', edge='#aebfc2', hover='#e9f3f2', selected='#d7ece9',
                  accent='#086862', accent_hover='#075651', on_accent='#ffffff',
                  focus='#16877d', disabled='#eef2f2', disabled_ink='#607277'),
    'night': dict(surface='#1a2428', panel='#222e33', ink='#e7eff0', muted='#afc0c3',
                  line='#384b51', edge='#657d84', hover='#2e4147', selected='#304e50',
                  accent='#79dfd1', accent_hover='#9ce9df', on_accent='#102e30',
                  focus='#79dfd1', disabled='#28363b', disabled_ink='#97aaae'),
}
WORKBENCH_STYLE = Template("""
QWidget#workbench, QDialog { background: $surface; color: $ink; }
QWidget#header, QWidget#footer, QWidget#sidebar, QWidget#inspectorPanel,
QWidget#viewSettings, QScrollArea#inspector { background: $panel; }
QWidget#header { border-bottom: 1px solid $line; }
QWidget#footer { border-top: 1px solid $line; }
QSplitter::handle { background: $line; }
QLabel { color: $ink; }
QLabel#appTitle { font-size: 17px; font-weight: 700; }
QLabel#pageTitle { font-size: 24px; font-weight: 700; }
QLabel#sectionTitle { font-size: 15px; font-weight: 600; }
QLabel#muted, QLabel#detailKey { color: $muted; }
QPushButton, QToolButton {
    min-height: 18px; padding: 5px 9px; border: 1px solid $edge; border-radius: 5px;
    font-size: 13px;
    color: $ink; background: $surface;
}
QToolButton#menuButton { padding: 5px 28px 5px 10px; }
QToolButton#menuButton::menu-indicator { image: none; width: 0; }
QPushButton:hover, QToolButton:hover { background: $hover; }
QPushButton:pressed, QToolButton:pressed, QToolButton:checked { background: $selected; }
QPushButton#primary { background: $accent; border-color: $accent; color: $on_accent; font-weight: 600; }
QPushButton#primary:hover { background: $accent_hover; }
QPushButton#stage:checked { background: $selected; border-color: $accent; font-weight: 600; }
QPushButton#quiet { border-color: transparent; background: transparent; }
QPushButton#quiet:hover { background: $hover; }
QPushButton#reviewAction { border-color: $accent; }
QPushButton:disabled, QToolButton:disabled, QPushButton#quiet:disabled,
QPushButton#stage:disabled, QPushButton#primary:disabled {
    background: $disabled; color: $disabled_ink; border-color: $line;
}
QPushButton#quiet:disabled { background: transparent; border-color: transparent; }
QPushButton:focus, QToolButton:focus, QPushButton#primary:focus,
QPushButton#quiet:focus, QPushButton#stage:focus, QPushButton#reviewAction:focus {
    border-color: $focus;
}
QPushButton#primary:focus { border-color: $on_accent; }
QPushButton#reviewAction:focus { background: $hover; }
QPushButton#disclosure {
    border: 1px solid transparent; border-top-color: $line; border-radius: 0;
    padding: 6px 28px 6px 2px; text-align: left; font-weight: 600; background: transparent;
}
QPushButton#disclosure:hover { background: $hover; }
QPushButton#disclosure:focus { border-color: $focus; }
QToolBar { background: transparent; border: 0; spacing: 2px; }
QToolBar::separator { background: $line; width: 1px; margin: 5px 3px; }
QToolBar QToolButton { min-width: 19px; padding: 3px; border-color: transparent; background: transparent; }
QToolBar QToolButton:hover { background: $hover; }
QToolBar QToolButton:checked { background: $selected; }
QToolBar QToolButton:disabled { background: transparent; border-color: transparent; }
QToolBar QToolButton:focus { border-color: $focus; }
QToolButton#plotZoom::menu-button { width: 16px; border: 0; }
QToolButton#plotZoom::menu-arrow { width: 9px; height: 9px; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    color: $ink; background: $surface; border: 1px solid $edge; border-radius: 5px;
    min-height: 18px; padding: 5px 7px;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: $focus; }
QComboBox { padding-right: 28px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: right center; width: 26px; border: 0; }
QComboBox::down-arrow { image: none; }
QComboBox QAbstractItemView { border: 1px solid $edge; outline: 0; }
QComboBox QAbstractItemView::item { min-height: 25px; padding: 2px 6px; }
QCheckBox { color: $ink; }
QMenu { color: $ink; background: $surface; border: 1px solid $edge; padding: 4px; }
QMenu::item { min-height: 18px; padding: 6px 12px 6px 20px; border-radius: 4px; }
QMenu::item:selected { color: $ink; background: $selected; }
QMenu::item:disabled { color: $disabled_ink; }
QMenu::separator { height: 1px; background: $line; margin: 4px 8px; }
QListWidget, QTableWidget {
    color: $ink; background: $surface; alternate-background-color: $panel; gridline-color: $line;
}
QListWidget#properties { border: 0; background: $panel; }
QListWidget#properties::item { padding: 7px 6px; border-radius: 5px; }
QListWidget::item:selected, QTableWidget::item:selected {
    color: $ink; background: $selected;
}
QHeaderView::section { color: $ink; background: $panel; padding: 5px; border: 0; }
QTabWidget::pane { border: 0; border-top: 1px solid $line; }
QTabWidget::tab-bar { alignment: left; }
QTabBar { background: $surface; }
QTabBar::tab {
    color: $muted; background: $surface; padding: 5px 10px; border-bottom: 2px solid transparent;
}
QTabBar::tab:selected { color: $accent; font-weight: 600; border-color: $accent; }
QTabBar::tab:focus { background: $hover; }
QScrollBar:vertical { background: $panel; width: 9px; margin: 0; }
QScrollBar:horizontal { background: $panel; height: 9px; margin: 0; }
QScrollBar::handle { background: $edge; border: 1px solid $panel; border-radius: 4px; min-width: 22px; min-height: 22px; }
QScrollBar::sub-line, QScrollBar::add-line { height: 0; width: 0; }
QScrollBar::sub-page, QScrollBar::add-page { background: none; }
QToolTip { color: $ink; background: $panel; border: 1px solid $edge; }
""")

PLOT_THEMES = {
    'light': dict(background='white', ink='black', muted='#4a6165', grid='#dbe7e6',
                  diagonal='#70818a', selection='#111', statuses=('#147a78', '#b9710a', '#b03748')),
    'night': dict(background='#151d20', ink='#e7eff0', muted='#afc0c3', grid='#394b51',
                  diagonal='#a9c4cb', selection='#f0f7f9', statuses=('#52d5c8', '#ffc260', '#ff8495')),
}
PLOT_STATUS_MARKERS = {'Retained': 'o', 'Candidate': 'D', 'Excluded': 'x'}


def draw_chevron(widget: W.QWidget, *, right: bool = False) -> None:
    painter = QtGui.QPainter(widget)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    pen = QtGui.QPen(widget.palette().buttonText().color())
    pen.setWidthF(1.5)
    pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.translate(widget.width() - 14, widget.height() / 2)
    if right:
        painter.rotate(-90)
    painter.drawPolyline([QtCore.QPointF(-4, -2), QtCore.QPointF(0, 2), QtCore.QPointF(4, -2)])
    painter.end()


class MenuButton(W.QToolButton):
    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        super().paintEvent(event)
        draw_chevron(self)


class DisclosureButton(W.QPushButton):
    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        super().paintEvent(event)
        draw_chevron(self, right=not self.isChecked())


class WorkbenchCanvas(FigureCanvasQTAgg):
    def __init__(self, figure: Figure, window: Window):
        super().__init__(figure)
        self._workbench = window

    def print_figure(self, *args, **kwargs):
        # Both Save Plot commands use this canvas. Keep their output independent of the screen theme.
        appearance = self._workbench.effective_appearance
        if appearance != 'night':
            return super().print_figure(*args, **kwargs)
        self._workbench.style_plot('light')
        try:
            return super().print_figure(*args, **kwargs)
        finally:
            self._workbench.style_plot(appearance)
            self.draw_idle()

class ReadableComboBox(W.QComboBox):
    """Reserve room for text and the macOS arrow; size menus to their content."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizeAdjustPolicy(W.QComboBox.AdjustToContents)
        self.setMinimumContentsLength(10)
        self.setSizePolicy(W.QSizePolicy.MinimumExpanding, W.QSizePolicy.Fixed)
        self.setView(W.QListView())
        self.view().setTextElideMode(QtCore.Qt.ElideNone)
        self.currentTextChanged.connect(self.setToolTip)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        super().paintEvent(event)
        draw_chevron(self)

    def minimumSizeHint(self):
        return self.sizeHint()

    def sizeHint(self):
        size=super().sizeHint()
        width=max([self.fontMetrics().horizontalAdvance(self.itemText(i)) for i in range(self.count())]+[90])
        size.setWidth(max(size.width(),width+48))
        return size

    def showPopup(self):
        width=max([self.view().fontMetrics().horizontalAdvance(self.itemText(i)) for i in range(self.count())]+[90])
        self.view().setMinimumWidth(max(self.width(),width+48))
        super().showPopup()


class PlotToolbar(NavigationToolbar2QT):
    """One magnifier with a selectable rectangle zoom direction."""
    navigation_changed = QtCore.Signal()

    def __init__(self, canvas, parent=None):
        self.zoom_direction = 'in'
        super().__init__(canvas, parent)
        menu = W.QMenu(self)
        self.direction_group = QtGui.QActionGroup(self)
        self.direction_group.setExclusive(True)
        self.direction_actions = {}
        for direction in ['in', 'out']:
            action = menu.addAction('Zoom '+direction+' — drag rectangle')
            action.setCheckable(True)
            action.setChecked(direction == 'in')
            self.direction_group.addAction(action)
            action.triggered.connect(lambda checked=False, d=direction: self.set_zoom_direction(d))
            self.direction_actions[direction] = action
        self.zoom_button = self.widgetForAction(self._actions['zoom'])
        self.zoom_button.setObjectName('plotZoom')
        self.zoom_button.setMenu(menu)
        self.zoom_button.setPopupMode(W.QToolButton.MenuButtonPopup)
        self.update_zoom_label()

    @contextmanager
    def _wait_cursor_for_draw_cm(self):
        # Avoid Qt's unstable wait cursor during macOS canvas redraws.
        if sys.platform == 'darwin':
            yield
        else:
            with super()._wait_cursor_for_draw_cm():
                yield

    def refresh_icons(self) -> None:
        for _text, _tooltip, icon, callback in self.toolitems:
            if icon is not None:
                self._actions[callback].setIcon(self._icon(icon + '.png'))

    def update_zoom_label(self):
        action = self._actions['zoom']
        action.setText('Zoom '+self.zoom_direction+' (rectangle)')
        action.setToolTip('Zoom '+self.zoom_direction+': drag a rectangle. Use the magnifier arrow to change direction.')

    def set_zoom_direction(self, direction):
        self.zoom_direction = direction
        self.direction_actions[direction].setChecked(True)
        self.update_zoom_label()
        if self.mode.name != 'ZOOM':
            self.zoom()

    def zoom(self, *args):
        super().zoom(*args)
        self.navigation_changed.emit()

    def pan(self, *args):
        super().pan(*args)
        self.navigation_changed.emit()

    def press_zoom(self, event):
        super().press_zoom(event)
        if self._zoom_info is not None and event.button == 1:
            self._zoom_info = self._zoom_info._replace(direction=self.zoom_direction)


class Worker(QtCore.QThread):
    done = QtCore.Signal(object)
    failed = QtCore.Signal(str)
    def __init__(self, fn):
        super().__init__();self.fn=fn
    def run(self):
        try:self.done.emit(self.fn())
        except Exception as exc:self.failed.emit(str(exc)+'\n\n'+traceback.format_exc())


class AutoWorker(Worker):
    progress = QtCore.Signal(int, int, str, str)
    def __init__(self, session):
        self.stop_requested = threading.Event()
        super().__init__(lambda: auto.run(session, self.progress.emit, self.stop_requested.is_set))


class Setup(W.QDialog):
    def __init__(self,parent=None):
        super().__init__(parent);self.setWindowTitle('New cleanup session');self.resize(680,500)
        self.setObjectName('setup')
        layout=W.QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        title = W.QLabel('Create a cleanup session', objectName='pageTitle')
        layout.addWidget(title)
        form=W.QFormLayout();layout.addLayout(form)
        self.source=W.QLineEdit();self.spectra=W.QLineEdit();self.output=W.QLineEdit(str(Path.home()/'Documents'/'MIR Cleanup'))
        for title,edit,kind in [('Reference workbook',self.source,'file'),('OPUS spectra folder',self.spectra,'dir'),('Session parent folder',self.output,'dir')]:
            row=W.QHBoxLayout();row.addWidget(edit);button=W.QPushButton('Browse…');row.addWidget(button)
            button.clicked.connect(lambda checked=False,e=edit,k=kind:self.browse(e,k));form.addRow(title,row)
        load=W.QPushButton('Read properties from workbook');load.clicked.connect(self.load_properties);layout.addWidget(load)
        self.all=W.QCheckBox('Select all property sheets');layout.addWidget(self.all)
        self.props=W.QScrollArea();self.props.setWidgetResizable(True);self.property_checks=[];layout.addWidget(self.props)
        self.read_status=W.QLabel('Choose a workbook, then read its properties.');layout.addWidget(self.read_status)
        self.all.toggled.connect(lambda yes:[c.setChecked(yes) for c in self.property_checks])
        layout.addWidget(W.QLabel('A new dated session folder will be created. Original inputs remain unchanged.'))
        buttons=W.QDialogButtonBox(W.QDialogButtonBox.Ok|W.QDialogButtonBox.Cancel);layout.addWidget(buttons)
        create = buttons.button(W.QDialogButtonBox.Ok)
        create.setText('Create session')
        create.setObjectName('primary')
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject)
    def browse(self,edit,kind):
        value=W.QFileDialog.getOpenFileName(self,'Reference workbook','','Excel (*.xlsx)')[0] if kind=='file' else W.QFileDialog.getExistingDirectory(self,'Select folder')
        if value:edit.setText(value)
    def load_properties(self):
        if getattr(self,'reader',None):
            return
        self.read_status.setText('Reading workbook…')
        source=self.source.text()
        self.reader=Worker(lambda:engine.workbook_properties(source))
        self.reader.done.connect(self.properties_loaded)
        self.reader.failed.connect(self.properties_failed)
        self.reader.finished.connect(self.properties_finished)
        self.reader.start()
    @QtCore.Slot(object)
    def properties_loaded(self, properties):
        panel=W.QWidget();rows=W.QVBoxLayout(panel);self.property_checks=[]
        for p in properties:
            item=W.QCheckBox(p);rows.addWidget(item);item.setChecked(self.all.isChecked() or p in ['202_STC','202_STN']);self.property_checks.append(item)
        rows.addStretch();self.props.setWidget(panel);self.read_status.setText(f'{len(properties)} property sheets available.')
    @QtCore.Slot(str)
    def properties_failed(self, message):
        self.read_status.setText('Workbook could not be read.');W.QMessageBox.warning(self,'Cannot read workbook',message.split('\n\n')[0])
    @QtCore.Slot()
    def properties_finished(self):
        self.reader.wait();self.reader.deleteLater();self.reader=None
    def reject(self):
        if getattr(self,'reader',None):
            W.QMessageBox.information(self,'Reading workbook','Please wait for the workbook read to finish.');return
        super().reject()
    def accept(self):
        if getattr(self,'reader',None):
            return
        if not any(c.isChecked() for c in self.property_checks) or not Path(self.spectra.text()).is_dir() or not Path(self.source.text()).is_file():
            W.QMessageBox.warning(self,'Inputs needed','Select valid inputs and at least one property.');return
        super().accept()


class Window(W.QMainWindow):
    STAGES = ('PCA', 'A', 'B')
    STAGE_LABELS = {'PCA': 'PCA', 'A': 'Half A', 'B': 'Half B'}

    def __init__(self, settings: QtCore.QSettings | None = None):
        super().__init__()
        self.settings = settings if settings is not None else QtCore.QSettings('Soil MIR', 'MIR Cleanup')
        stored_mode = self.settings.value(APPEARANCE_KEY, 'system', type=str)
        self.appearance = stored_mode if stored_mode in APPEARANCE_LABELS else 'system'
        self.effective_appearance = ''
        self.setWindowTitle('MIR Cleanup')
        self.resize(1280, 760)
        self.session = None
        self.undo_states = []
        self.worker = None
        self.rows = []
        self.selected = set()
        self.syncing = False
        self.visible = []
        self.filters = {}
        self.table_context = None
        self.colorbar = None
        self.plot_statuses = []
        self.record_samples = {}
        self.sample_files = {}
        self.pca_exclusions = set()
        self.rect = self.lasso = self.artist = None

        self.figure = Figure(figsize=(9, 5), facecolor='white')
        self.canvas = WorkbenchCanvas(self.figure, self)
        self.ax = self.figure.subplots()
        self.canvas.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.canvas.mpl_connect('button_press_event', self.plot_click)
        self.canvas.mpl_connect('key_press_event', self.plot_key)
        self.canvas.mpl_connect('pick_event', self.pick)
        self.canvas.mpl_connect('motion_notify_event', self.hover)

        root = W.QWidget(objectName='workbench')
        self.setCentralWidget(root)
        layout = W.QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.make_header())
        self.pages = W.QStackedWidget()
        layout.addWidget(self.pages, 1)
        self.welcome = self.make_welcome()
        self.review = self.make_review()
        self.auto_page, self.auto_layout = self.make_summary_page()
        self.export_page, self.export_layout = self.make_summary_page()
        self.result_page, self.result_layout = self.make_summary_page()
        for page in (self.welcome, self.review, self.auto_page, self.export_page, self.result_page):
            self.pages.addWidget(page)

        self.busy_label = self.label('')
        self.busy_label.setContentsMargins(14, 3, 14, 3)
        self.busy_label.hide()
        layout.addWidget(self.busy_label)
        self.pages.setCurrentWidget(self.welcome)
        self.session_actions.hide()
        self.style_hints = W.QApplication.styleHints()
        self.style_hints.colorSchemeChanged.connect(self.system_appearance_changed, QtCore.Qt.QueuedConnection)
        self.apply_appearance(self.style_hints.colorScheme())

    def set_appearance(self, mode: str) -> None:
        self.appearance = mode
        self.settings.setValue(APPEARANCE_KEY, mode)
        self.apply_appearance(self.style_hints.colorScheme())

    @QtCore.Slot(QtCore.Qt.ColorScheme)
    def system_appearance_changed(self, scheme: QtCore.Qt.ColorScheme) -> None:
        if self.appearance == 'system':
            self.apply_appearance(scheme)

    def apply_appearance(self, system_scheme: QtCore.Qt.ColorScheme) -> None:
        self.appearance_actions[self.appearance].setChecked(True)
        mode = self.appearance
        if mode == 'system':
            mode = 'night' if system_scheme == QtCore.Qt.ColorScheme.Dark else 'light'
        if mode == self.effective_appearance:
            return
        self.effective_appearance = mode

        theme = THEMES[mode]
        app = W.QApplication.instance()
        palette = app.palette()
        roles = QtGui.QPalette.ColorRole
        for role, token in {
            roles.Window: 'surface', roles.Base: 'surface', roles.Button: 'surface',
            roles.WindowText: 'ink', roles.Text: 'ink', roles.ButtonText: 'ink',
            roles.Highlight: 'selected', roles.HighlightedText: 'ink',
            roles.AlternateBase: 'panel', roles.PlaceholderText: 'muted',
            roles.ToolTipBase: 'panel', roles.ToolTipText: 'ink',
            roles.Light: 'edge', roles.Midlight: 'line', roles.Mid: 'edge',
            roles.Dark: 'line', roles.Shadow: 'edge', roles.BrightText: 'ink',
            roles.Link: 'accent', roles.LinkVisited: 'accent', roles.Accent: 'accent',
        }.items():
            palette.setColor(role, QtGui.QColor(theme[token]))
        for role in (roles.Text, roles.WindowText, roles.ButtonText):
            palette.setColor(QtGui.QPalette.Disabled, role, QtGui.QColor(theme['disabled_ink']))
        app.setPalette(palette)
        app.setStyleSheet(WORKBENCH_STYLE.substitute(theme))
        self.toolbar.refresh_icons()
        canvas_background = QtGui.QColor(PLOT_THEMES[mode]['background'])
        self.canvas.setPalette(QtGui.QPalette(canvas_background))
        self.style_plot(mode)
        self.canvas.draw_idle()

    def label(self, text: str, role: str = '') -> W.QLabel:
        label = W.QLabel(text)
        label.setTextFormat(QtCore.Qt.PlainText)
        if role:
            label.setObjectName(role)
        return label

    def wrap(self, text: str, role: str = '') -> W.QLabel:
        label = self.label(text, role)
        label.setWordWrap(True)
        return label

    def primary(self, button: W.QPushButton) -> None:
        button.setObjectName('primary')

    def menu_button(self, text: str, actions) -> W.QToolButton:
        button = MenuButton(objectName='menuButton')
        button.setText(text)
        button.setFocusPolicy(QtCore.Qt.StrongFocus)
        button.setPopupMode(W.QToolButton.InstantPopup)
        menu = W.QMenu(button)
        for item in actions:
            if item is None:
                menu.addSeparator()
            else:
                name, callback = item
                menu.addAction(name, callback)
        button.setMenu(menu)
        return button

    def make_header(self) -> W.QWidget:
        header = W.QWidget(objectName='header')
        row = W.QHBoxLayout(header)
        row.setContentsMargins(16, 9, 16, 9)
        row.addWidget(self.label('MIR Cleanup', 'appTitle'))
        self.session_name = self.label('', 'muted')
        self.session_name.setSizePolicy(W.QSizePolicy.Ignored, W.QSizePolicy.Preferred)
        row.addWidget(self.session_name, 1)
        self.session_actions = W.QWidget()
        actions = W.QHBoxLayout(self.session_actions)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.addWidget(self.menu_button('Session', [
            ('New session', self.new),
            ('Open session', self.open_session),
            None,
            ('Locate original workbook', self.relocate),
            None,
            ('Open results folder', self.open_folder),
            ('Open cleaned workbook', self.open_cleaned),
        ]))
        self.auto_button = self.button(actions, 'Auto clean eligible properties…', self.auto_clean)
        self.auto_results_button = self.button(actions, 'Cleanup results', self.show_auto_results)
        self.button(actions, 'Export overview', self.show_export_overview)
        row.addWidget(self.session_actions)
        appearance = self.menu_button('Appearance', [])
        group = QtGui.QActionGroup(appearance)
        self.appearance_actions = {}
        for mode, label in APPEARANCE_LABELS.items():
            action = appearance.menu().addAction(label)
            action.setCheckable(True)
            group.addAction(action)
            action.triggered.connect(lambda checked=False, value=mode: self.set_appearance(value))
            self.appearance_actions[mode] = action
        row.addWidget(appearance)
        return header

    def make_welcome(self) -> W.QWidget:
        page = W.QWidget()
        layout = W.QVBoxLayout(page)
        layout.setAlignment(QtCore.Qt.AlignCenter)
        panel = W.QWidget()
        panel.setFixedWidth(365)
        body = W.QVBoxLayout(panel)
        body.setSpacing(12)
        body.addWidget(self.label('Start a cleanup session', 'pageTitle'))
        body.addWidget(self.wrap('Review MIR spectra and prepare a cleaned reference workbook.', 'muted'))
        self.primary(self.button(body, 'New session', self.new))
        self.button(body, 'Open session', self.open_session)
        layout.addWidget(panel)

        return page

    def make_review(self) -> W.QWidget:
        self.prop = W.QComboBox(self)
        self.prop.hide()
        self.prop.currentTextChanged.connect(self.resume_property)
        self.stage = W.QComboBox(self)
        self.stage.addItems(self.STAGES)
        self.stage.hide()
        self.stage.currentTextChanged.connect(self.refresh)

        page = W.QWidget()
        body = W.QVBoxLayout(page)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        split = W.QSplitter(QtCore.Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.addWidget(self.make_properties())
        split.addWidget(self.make_chart())
        split.addWidget(self.make_inspector())
        split.setStretchFactor(1, 1)
        split.setSizes([205, 775, 274])
        body.addWidget(split, 1)

        footer = W.QWidget(objectName='footer')
        actions = W.QHBoxLayout(footer)
        actions.setContentsMargins(16, 8, 16, 8)
        self.review_status = self.wrap('', 'muted')
        actions.addWidget(self.review_status, 1)
        self.undo_button = self.button(actions, 'Undo decision', self.undo)
        self.undo_button.setObjectName('quiet')
        self.calc = self.button(actions, 'Refit PCA', self.calculate)
        self.finish = self.button(actions, 'Finish PCA review / split', self.finish_review)
        self.next_button = self.button(actions, '', self.advance_review)
        for button in (self.calc, self.finish, self.next_button):
            self.primary(button)
        body.addWidget(footer)
        return page

    def make_properties(self) -> W.QWidget:
        sidebar = W.QWidget(objectName='sidebar')
        sidebar.setMinimumWidth(152)
        layout = W.QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 14, 8, 10)
        layout.addWidget(self.label('Properties', 'sectionTitle'))
        self.properties = W.QListWidget()
        self.properties.setObjectName('properties')
        self.properties.setAccessibleName('Properties')
        self.properties.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.properties.currentRowChanged.connect(self.prop.setCurrentIndex)
        layout.addWidget(self.properties, 1)
        self.review_tools = self.menu_button('Review tools', [
            ('Concentration limit…', self.show_limit),
            ('Export review Excel', self.export_review),
            ('Import review Excel', self.import_review),
        ])
        layout.addWidget(self.review_tools)
        return sidebar

    def make_chart(self) -> W.QWidget:
        chart = W.QWidget(objectName='chart')
        layout = W.QVBoxLayout(chart)
        layout.setContentsMargins(14, 12, 14, 8)
        layout.setSpacing(8)
        stages = W.QHBoxLayout()
        self.stage_buttons = {}
        for stage, text in self.STAGE_LABELS.items():
            button = self.button(stages, text, lambda checked=False, value=stage: self.stage.setCurrentText(value))
            button.setCheckable(True)
            button.setObjectName('stage')
            self.stage_buttons[stage] = button
        layout.addLayout(stages)
        heading = W.QHBoxLayout()
        title = W.QVBoxLayout()
        title.setSpacing(2)
        self.property_title = self.wrap('', 'muted')
        self.stage_title = self.wrap('', 'pageTitle')
        title.addWidget(self.property_title)
        title.addWidget(self.stage_title)
        heading.addLayout(title, 1)
        view_button = W.QToolButton()
        view_button.setText('View settings')
        view_button.setFocusPolicy(QtCore.Qt.StrongFocus)
        view_button.setCheckable(True)
        heading.addWidget(view_button)
        heading.addWidget(self.menu_button('Plot tools', [
            ('Open offline PCA', self.open_pca),
            ('Save plot PNG/PDF', self.save_plot),
        ]))
        layout.addLayout(heading)
        self.plot_controls = self.make_plot_controls()
        self.plot_controls.hide()
        view_button.toggled.connect(self.plot_controls.setVisible)
        layout.addWidget(self.plot_controls)

        self.tabs = W.QTabWidget()
        self.tabs.tabBar().setDrawBase(False)
        layout.addWidget(self.tabs, 1)
        plot = W.QWidget()
        plot_layout = W.QVBoxLayout(plot)
        plot_layout.setContentsMargins(0, 4, 0, 0)
        tools = W.QHBoxLayout()
        self.toolbar = PlotToolbar(self.canvas, self)
        self.toolbar.setIconSize(QtCore.QSize(21, 21))
        tools.addWidget(self.toolbar)
        tools.addStretch(1)
        self.select_mode = ReadableComboBox()
        self.select_mode.setAccessibleName('Plot selection mode')
        self.select_mode.addItems(['Click points', 'Rectangle selection', 'Lasso selection'])
        self.select_mode.currentIndexChanged.connect(self.selection_mode)
        self.toolbar.navigation_changed.connect(self.selection_mode)
        tools.addWidget(self.select_mode)
        self.button(tools, 'Clear selection', self.clear_selection)
        plot_layout.addLayout(tools)
        plot_layout.addWidget(self.canvas, 1)
        self.chart_hint = self.wrap('', 'muted')
        plot_layout.addWidget(self.chart_hint)
        self.tabs.addTab(plot, 'Plot')

        self.table = W.QTableWidget()
        self.table.setSelectionBehavior(W.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(W.QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(W.QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self.table_selection)
        data = W.QWidget()
        data_layout = W.QVBoxLayout(data)
        data_layout.setContentsMargins(0, 4, 0, 0)
        table_controls = W.QHBoxLayout()
        table_controls.addWidget(self.wrap('Click a heading to sort. Double-click to filter.', 'muted'), 1)
        self.button(table_controls, 'Clear filters', self.clear_filters)
        self.button(table_controls, 'Clear selection', self.clear_selection)
        data_layout.addLayout(table_controls)
        data_layout.addWidget(self.table)
        self.tabs.addTab(data, 'Data sheet')
        header = self.table.horizontalHeader()
        header.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        header.customContextMenuRequested.connect(self.header_menu)
        header.sectionDoubleClicked.connect(self.header_filter)

        self.full_table = W.QTableWidget()
        self.full_table.setEditTriggers(W.QAbstractItemView.NoEditTriggers)
        self.full_table.setAlternatingRowColors(True)
        self.full = W.QWidget()
        full_layout = W.QVBoxLayout(self.full)
        full_layout.setContentsMargins(0, 4, 0, 0)
        self.full_summary = self.wrap('', 'muted')
        full_layout.addWidget(self.full_summary)
        self.full_search = W.QLineEdit()
        self.full_search.setPlaceholderText('Filter full dataset: sample, filename, half, status or reason')
        self.full_search.textChanged.connect(self.populate_full)
        full_layout.addWidget(self.full_search)
        full_layout.addWidget(self.full_table)
        self.tabs.addTab(self.full, 'Full dataset (A + B)')
        return chart

    def make_plot_controls(self) -> W.QWidget:
        panel = W.QWidget(objectName='viewSettings')
        layout = W.QGridLayout(panel)
        self.xpc = ReadableComboBox()
        self.ypc = ReadableComboBox()
        self.scale = ReadableComboBox()
        self.scale.addItems(['Modelled scale', 'Original units'])
        self.colour = ReadableComboBox()
        self.colour.addItems(['Status', 'Treatment', 'Reference value'])
        self.subset = ReadableComboBox()
        self.subset.addItems(['All in fitted model', 'Retained only', 'Excluded only'])
        controls = [('X PC', self.xpc), ('Y PC', self.ypc), ('Scale', self.scale),
                    ('Colour', self.colour), ('Show', self.subset)]
        self.plot_labels = {}
        for index, (text, widget) in enumerate(controls):
            row, column = divmod(index, 2)
            label = self.label(text)
            self.plot_labels[widget] = label
            widget.setAccessibleName(text)
            widget.currentIndexChanged.connect(self.draw)
            layout.addWidget(label, row, column * 2)
            layout.addWidget(widget, row, column * 2 + 1)
        return panel

    def make_inspector(self) -> W.QWidget:
        scroll = W.QScrollArea(objectName='inspector')
        scroll.setMinimumWidth(218)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(W.QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        panel = W.QWidget(objectName='inspectorPanel')
        scroll.setWidget(panel)
        body = W.QVBoxLayout(panel)
        body.setContentsMargins(12, 14, 12, 12)
        body.setSpacing(8)
        body.addWidget(self.label('Selection', 'sectionTitle'))
        self.selection_label = self.wrap('', 'muted')
        body.addWidget(self.selection_label)
        self.impact_label = self.wrap('', 'sectionTitle')
        body.addWidget(self.impact_label)

        self.decision_controls = W.QWidget()
        decision = W.QVBoxLayout(self.decision_controls)
        decision.setContentsMargins(0, 4, 0, 0)
        self.reason = ReadableComboBox()
        self.reason.addItems(['No reason', 'redundancy', 'spectral_quality', 'range', 'concentration'])
        self.unit = ReadableComboBox()
        self.unit.addItems(['spectrum', 'sample'])
        self.unit.setItemData(0, 'Only the selected spectra', QtCore.Qt.ToolTipRole)
        self.unit.setItemData(1, 'All eligible replicates of each selected sample', QtCore.Qt.ToolTipRole)
        self.unit_help = self.wrap('', 'muted')
        self.unit_help.setMinimumHeight(44)
        self.comment = W.QLineEdit()
        self.comment.setPlaceholderText('Optional comment')
        for title, widget in [('Exclusion unit', self.unit), ('Reason (optional)', self.reason)]:
            widget.setAccessibleName(title)
            decision.addWidget(self.label(title))
            decision.addWidget(widget)
            if widget is self.unit:
                decision.addWidget(self.unit_help)
        decision.addWidget(self.comment)
        self.exclude_button = self.button(decision, 'Review exclusion…', self.exclude)
        self.restore_button = self.button(decision, 'Restore selected…', self.restore)
        body.addWidget(self.decision_controls)
        self.unit.currentIndexChanged.connect(self.update_selection)
        self.tabs.currentChanged.connect(self.update_selection)

        self.exclude_button.setObjectName('reviewAction')
        self.restore_button.setObjectName('quiet')
        self.details_button = DisclosureButton('Model details', objectName='disclosure')
        self.details_button.setCheckable(True)
        body.addWidget(self.details_button)
        details_panel = W.QWidget()
        details_layout = W.QVBoxLayout(details_panel)
        details_layout.setContentsMargins(2, 0, 2, 0)
        self.detail_fields = W.QFormLayout()
        self.detail_fields.setLabelAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        self.detail_fields.setRowWrapPolicy(W.QFormLayout.RowWrapPolicy.WrapLongRows)
        self.detail_fields.setFieldGrowthPolicy(W.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        details_layout.addLayout(self.detail_fields)
        self.info = self.wrap('', 'muted')
        details_layout.addWidget(self.info)
        details_panel.hide()
        body.addWidget(details_panel)
        self.details_button.toggled.connect(details_panel.setVisible)
        body.addStretch(1)

        self.limit_dialog = W.QDialog(self, objectName='limitDialog')
        self.limit_dialog.setWindowTitle('Concentration limit')
        limit_layout = W.QVBoxLayout(self.limit_dialog)
        self.limit = W.QCheckBox('Enable concentration limit')
        self.percent = W.QDoubleSpinBox()
        self.percent.setRange(0, 100)
        self.percent.setDecimals(3)
        self.percent.setValue(1)
        self.percent.setSuffix(' %')
        limit_layout.addWidget(self.limit)
        limit_layout.addWidget(self.percent)
        limit_layout.addWidget(self.wrap('The limit counts affected samples across both halves of each property.'))
        limit_actions = W.QHBoxLayout()
        limit_layout.addLayout(limit_actions)
        self.button(limit_actions, 'Save limit', self.save_limit)
        self.button(limit_actions, 'Close', self.limit_dialog.close)
        return scroll

    def show_limit(self) -> None:
        self.limit_dialog.exec()

    def make_summary_page(self) -> tuple[W.QWidget, W.QVBoxLayout]:
        page = W.QWidget()
        layout = W.QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(12)
        return page, layout

    def reset_summary(self, layout: W.QVBoxLayout, title: str) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        layout.addWidget(self.label(title, 'pageTitle'))

    def summary_table(self, headings, rows) -> W.QTableWidget:
        table = W.QTableWidget(len(rows), len(headings))
        table.setHorizontalHeaderLabels(headings)
        table.setEditTriggers(W.QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(W.QAbstractItemView.SelectRows)
        table.setSelectionMode(W.QAbstractItemView.SingleSelection)
        table.setAlternatingRowColors(True)
        table.verticalHeader().hide()
        header = table.horizontalHeader()
        header.setSectionResizeMode(W.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(0, W.QHeaderView.Stretch)
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                table.setItem(row, column, W.QTableWidgetItem(str(value)))
        return table

    def summary_actions(self, layout: W.QVBoxLayout) -> W.QHBoxLayout:
        footer = W.QWidget()
        actions = W.QHBoxLayout(footer)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.addStretch(1)
        layout.addWidget(footer)
        return actions

    def review_property(self, prop: str) -> None:
        if self.prop.currentText() == prop:
            self.resume_property()
        else:
            self.prop.setCurrentText(prop)
        self.pages.setCurrentWidget(self.review)

    def review_selected_property(self, table: W.QTableWidget) -> None:
        item = table.item(table.currentRow(), 0)
        if item:
            self.review_property(item.text())

    def connect_summary_review(self, table: W.QTableWidget, button: W.QPushButton) -> None:
        button.setEnabled(False)
        table.itemSelectionChanged.connect(lambda: button.setEnabled(table.currentRow() >= 0))
        table.cellDoubleClicked.connect(lambda row, _: self.review_property(table.item(row, 0).text()))
        if table.rowCount():
            table.selectRow(0)

    def show_auto_results(self) -> None:
        if not self.session:
            return
        report = self.session.state.get('auto_cleanup')
        if not report:
            return
        self.reset_summary(self.auto_layout, 'Automatic cleanup')
        self.auto_layout.addWidget(self.wrap(f'Session copy: {self.session.folder}', 'muted'))
        issues = auto.readiness(self.session)
        ready = not issues and not report['stopped']
        self.auto_layout.addWidget(self.label('Ready to export' if ready else 'Further review needed', 'sectionTitle'))
        results = {item['property']: item for item in report['results']}
        status = {'completed': 'Completed', 'skipped': 'Skipped', 'failed': 'Needs review'}
        rows = []
        details = {}
        for prop in self.session.state['properties']:
            result = results.get(prop)
            if not result:
                rows.append((prop, 'Not processed', ''))
                continue
            key = result['status']
            counts = result.get('counts', {})
            summary = '; '.join(
                f"{half}: {count['samples']} samples, {count['excluded_spectra']} excluded spectra"
                for half, count in counts.items()
            )
            if key == 'skipped':
                summary = 'Existing A/B review'
            elif key == 'failed':
                summary = result.get('error', 'Calculation failed')
            rows.append((prop, status[key], summary))
            details[prop] = '\n'.join(
                f"{half}: {count['candidate_spectra']} candidate spectra; "
                f"{count['samples']} samples; {count['excluded_spectra']} excluded spectra"
                for half, count in counts.items()
            ) or summary
        if report['stopped']:
            self.auto_layout.addWidget(self.label('Stopped after the current property', 'muted'))
        table = self.summary_table(('Property', 'Status', 'Result'), rows)
        table.horizontalHeader().setSectionResizeMode(2, W.QHeaderView.Stretch)
        self.auto_layout.addWidget(table, 1)
        detail = self.wrap('', 'muted')
        self.auto_layout.addWidget(detail)
        table.currentCellChanged.connect(lambda row, *_: detail.setText(details.get(rows[row][0], '') if row >= 0 else ''))
        actions = self.summary_actions(self.auto_layout)
        self.button(actions, 'Export overview', self.show_export_overview)
        review = self.button(actions, 'Open selected property', lambda: self.review_selected_property(table))
        self.primary(review)
        self.connect_summary_review(table, review)
        for index, row in enumerate(rows):
            if row[1] in ('Needs review', 'Not processed') or any(issue.startswith(f'{row[0]}:') for issue in issues):
                table.selectRow(index)
                break
        self.pages.setCurrentWidget(self.auto_page)

    def show_export_overview(self) -> None:
        if self.session:
            session = self.session
            self.run(lambda: auto.readiness(session), self.render_export_overview)

    def render_export_overview(self, issues: list[str]) -> None:
        self.reset_summary(self.export_layout, 'Export overview')
        rows = []
        ready = 0
        for prop, state in self.session.state['properties'].items():
            excluded = self.session.excluded(prop)
            n_spectra = len(state['frame'])
            n_samples = len({row['Sample'] for row in state['frame'] if row['File Name'] in excluded})
            if not state['finished']['B']:
                status = 'Needs review'
            elif any(issue.startswith(f'{prop}:') for issue in issues):
                status = 'Check limit'
            else:
                status = 'Ready'
            ready += status == 'Ready'
            rows.append((prop, status, n_spectra - len(excluded), len(excluded), n_samples))
        self.export_layout.addWidget(self.label(f'{ready} of {len(rows)} properties ready', 'sectionTitle'))
        table = self.summary_table(('Property', 'Review status', 'Retained spectra', 'Excluded spectra', 'Affected samples'), rows)
        self.export_layout.addWidget(table, 1)
        if issues:
            blockers = W.QListWidget()
            blockers.setAccessibleName('Export blockers')
            blockers.addItems(issues)
            blockers.setMaximumHeight(116)
            self.export_layout.addWidget(self.label('Resolve before export', 'sectionTitle'))
            self.export_layout.addWidget(blockers)
            blockers.itemActivated.connect(lambda item: self.open_export_issue(item.text()))
            source_issue = any(issue.startswith('Source workbook ') for issue in issues)
        else:
            source_issue = False
            self.export_layout.addWidget(self.label('The session is ready to export.', 'muted'))
        actions = self.summary_actions(self.export_layout)
        if source_issue:
            self.button(actions, 'Locate original workbook', self.relocate_from_export)
        self.button(actions, 'Recheck readiness', self.show_export_overview)
        review = self.button(actions, 'Open selected property', lambda: self.review_selected_property(table))
        self.connect_summary_review(table, review)
        for index, row in enumerate(rows):
            if row[1] != 'Ready':
                table.selectRow(index)
                break
        export = self.button(actions, 'Export cleaned dataset', self.export)
        self.primary(export)
        export.setEnabled(not issues)
        self.pages.setCurrentWidget(self.export_page)

    def open_export_issue(self, issue: str) -> None:
        for prop in self.session.state['properties']:
            if issue.startswith(f'{prop}:'):
                self.review_property(prop)
                return
        if issue.startswith('Source workbook '):
            self.relocate_from_export()

    def relocate_from_export(self) -> None:
        self.relocate()
        self.show_export_overview()

    def show_export_result(self, folder: Path) -> None:
        self.reset_summary(self.result_layout, 'Export complete')
        self.result_layout.addWidget(self.wrap(f'Cleaned workbook and reports saved in:\n{folder}', 'muted'))
        self.result_layout.addStretch(1)
        actions = self.summary_actions(self.result_layout)
        self.button(actions, 'Back to review', lambda: self.pages.setCurrentWidget(self.review))
        self.button(actions, 'Show in Finder', self.open_folder)
        self.primary(self.button(actions, 'Open cleaned workbook', self.open_cleaned))
        self.pages.setCurrentWidget(self.result_page)

    def button(self,layout,text,fn):
        b=W.QPushButton(text);b.clicked.connect(fn);layout.addWidget(b);return b
    @QtCore.Slot(str)
    def error(self,message):
        box=W.QMessageBox(self);box.setWindowTitle('Action could not be completed');box.setIcon(W.QMessageBox.Warning)
        parts=message.split('\n\n',1);box.setText(parts[0]);
        if len(parts)>1:box.setDetailedText(parts[1])
        box.exec()
    def run(self,fn,done=None):
        if self.worker:return
        self.centralWidget().setEnabled(False);self.busy_label.setText('Working…');self.busy_label.show()
        self.worker=Worker(fn)
        self._completed_callback=done
        self.worker.done.connect(self.work_done);self.worker.failed.connect(self.error)
        self.worker.finished.connect(self.work_finished);self.worker.start()
    @QtCore.Slot(object)
    def work_done(self,result):
        if self._completed_callback:self._completed_callback(result)
    @QtCore.Slot()
    def work_finished(self):
        self.worker.wait();self.worker.deleteLater();self.worker=None;self.centralWidget().setEnabled(True);self.busy_label.hide();self.refresh()
        if getattr(self,'auto_progress',None):
            self.auto_progress.close();self.auto_progress=None

    def auto_clean(self):
        if not self.session or self.worker:return
        props = self.session.state['properties']
        skipped = [prop for prop, state in props.items() if auto.already_reviewed(state)]
        eligible = [prop for prop in props if prop not in skipped]
        message = (
            f'Create a session copy and clean {len(eligible)} of {len(props)} properties?\n\n'
            f'Will clean: {", ".join(eligible) or "None"}\n'
            f'Will skip (existing A/B review): {", ".join(skipped) or "None"}\n\n'
            'Existing PCA exclusions are preserved. Candidates are excluded as whole samples. '
            'Each half is processed once, using the current concentration limit.'
        )
        if W.QMessageBox.question(self,'Automatic cleanup',message)!=W.QMessageBox.Yes:return
        self.centralWidget().setEnabled(False);self.busy_label.setText('Working…');self.busy_label.show()
        self.auto_progress=W.QProgressDialog('Creating session copy…','Stop after current property',0,len(props),self)
        self.auto_progress.setWindowTitle('Automatic cleanup');self.auto_progress.setMinimumDuration(0)
        self.auto_progress.setAutoClose(False);self.auto_progress.setAutoReset(False)
        self.worker=AutoWorker(self.session);self._completed_callback=self.auto_completed
        self.auto_progress.canceled.connect(self.worker.stop_requested.set)
        self.worker.progress.connect(self.auto_update)
        self.worker.done.connect(self.work_done);self.worker.failed.connect(self.error)
        self.worker.finished.connect(self.work_finished);self.auto_progress.show();self.worker.start()

    @QtCore.Slot(int,int,str,str)
    def auto_update(self,index,total,prop,stage):
        if self.auto_progress:
            self.auto_progress.setMaximum(total);self.auto_progress.setValue(index-1)
            self.auto_progress.setLabelText(f'{index}/{total}: {prop} — {stage}')

    def auto_completed(self, session):
        self.bind(session)
        self.show_auto_results()

    def guard(self,fn):
        if not self.session:return
        try:fn()
        except Exception as exc:self.error(str(exc))
        self.refresh()
    def bind(self, session):
        self.session = session
        self.undo_states = []
        self.table_context = None
        self.prop.blockSignals(True)
        self.prop.clear()
        self.prop.addItems(list(session.state['properties']))
        self.prop.blockSignals(False)
        self.limit.setChecked(session.state['limit'] == 'enable')
        self.percent.setValue(session.state['percent'])
        self.session_name.setText(session.folder.name)
        self.session_name.setToolTip(str(session.folder))
        self.session_actions.show()
        self.auto_results_button.setVisible(bool(session.state.get('auto_cleanup')))
        self.pages.setCurrentWidget(self.review)
        self.resume_property()

    def review_stage(self, state: dict) -> str:
        if state['pca_dirty'] or not state['pca_done']:
            return 'PCA'
        return 'B' if state['finished']['A'] else 'A'

    def resume_property(self, *_args) -> None:
        if not self.session or not self.prop.currentText():
            return
        state = self.session.state['properties'][self.prop.currentText()]
        self.stage.blockSignals(True)
        self.stage.setCurrentText(self.review_stage(state))
        self.stage.blockSignals(False)
        self.refresh()

    def advance_review(self) -> None:
        stage = self.stage.currentText()
        if stage != 'B':
            self.stage.setCurrentText('A' if stage == 'PCA' else 'B')
            return
        props = self.session.state['properties']
        order = list(props)
        index = self.prop.currentIndex()
        next_props = order[index + 1:] + order[:index]
        for prop in next_props:
            if not props[prop]['finished']['B']:
                self.review_property(prop)
                return
        self.show_export_overview()

    def update_review_navigation(self, prop: str, state: dict, stage: str) -> None:
        props = self.session.state['properties']
        self.properties.blockSignals(True)
        if self.properties.count() != len(props):
            self.properties.clear()
            self.properties.addItems(list(props))
        for index, (name, data) in enumerate(props.items()):
            progress = 'Complete' if data['finished']['B'] else f'{self.STAGE_LABELS[self.review_stage(data)]} review'
            item = self.properties.item(index)
            item.setText(f'{name}\n{progress}')
            item.setToolTip(f'{name} · {progress}')
        self.properties.setCurrentRow(self.prop.currentIndex())
        self.properties.blockSignals(False)

        done = {'PCA': state['pca_done'], 'A': state['finished']['A'], 'B': state['finished']['B']}
        available = {'PCA': True, 'A': state['pca_done'] and not state['pca_dirty'], 'B': state['finished']['A']}
        for step, button in self.stage_buttons.items():
            label = self.STAGE_LABELS[step]
            button.setText(f'{label}  ✓' if done[step] else label)
            button.setChecked(step == stage)
            button.setEnabled(available[step])
            prerequisite = 'Finish PCA review first' if step == 'A' else 'Finish Half A review first'
            status = 'Complete' if done[step] else 'Available' if available[step] else prerequisite
            button.setToolTip(status)
            button.setAccessibleDescription(status)

        needs_calculation = state['pca_dirty'] if stage == 'PCA' else stage not in state['diagnostics']
        self.calc.setVisible(available[stage] and needs_calculation)
        self.finish.setVisible(available[stage] and not needs_calculation and not done[stage])
        self.next_button.setVisible(done[stage] and not needs_calculation)
        completed = sum(item['finished']['B'] for item in props.values())
        if stage == 'PCA':
            next_action = 'Review Half A'
        elif stage == 'A':
            next_action = 'Review Half B'
        else:
            next_action = 'Next property' if completed < len(props) else 'Export overview'
        self.next_button.setText(next_action)
        self.undo_button.setEnabled(bool(self.undo_states))
        self.review_status.setText(f'{self.STAGE_LABELS[stage]} review · {completed} of {len(props)} properties complete')
        self.property_title.setText(prop)
        self.stage_title.setText('PCA review' if stage == 'PCA' else f'Half {stage} calibration')
        if stage == 'PCA':
            self.chart_hint.setText('Decisions changed. Refit PCA before finishing this review.' if state['pca_dirty'] else
                                    f'PCA fit {state["pca_round"]} of 3 · Select unusual spectra to inspect them.')
        elif not available[stage]:
            self.chart_hint.setText('Finish the preceding review before starting this half.')
        elif needs_calculation:
            self.chart_hint.setText(f'Calculate Half {stage} to view its calibration plot and candidates.')
        else:
            self.chart_hint.setText('Candidate markers identify points for review. Selecting a point does not exclude it.')

    def new(self):
        dialog=Setup(self)
        if dialog.exec()!=W.QDialog.Accepted:return
        folder=Path(dialog.output.text())/datetime.now().strftime('session_%Y%m%d_%H%M%S_%f')
        self.run(lambda:engine.Session.create(dialog.source.text(),dialog.spectra.text(),folder,[i.text() for i in dialog.property_checks if i.isChecked()]),self.bind)
    def open_session(self):
        path=W.QFileDialog.getOpenFileName(self,'Open saved session','','Session (session.json)')[0]
        if path:
            try:self.bind(engine.Session.load(Path(path).parent))
            except Exception as exc:self.error(str(exc))
    def relocate(self):
        if not self.session:return
        path=W.QFileDialog.getOpenFileName(self,'Locate unchanged original workbook','','Excel (*.xlsx)')[0]
        if path:self.guard(lambda:self.session.relocate_source(path))
    def open_folder(self):
        if self.session:QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(self.session.state.get('last_export',str(self.session.folder))))
    def open_cleaned(self):
        if not self.session:return
        folder=self.session.state.get('last_export')
        if not folder or not (Path(folder)/'reference_cleaned.xlsx').exists():
            self.error('Export a cleaned dataset first, or locate the exported workbook in Finder.');return
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(Path(folder)/'reference_cleaned.xlsx')))
    def checkpoint(self):
        self.undo_states.append(copy.deepcopy(self.session.state))
    def undo(self):
        if not self.undo_states:return
        old=self.undo_states.pop();current=copy.deepcopy(self.session.state)
        self.session.state=old
        self.session.state['history'].append({'action':'Undo; previous revision archived','previous':current})
        self.session.save('Undo decision');self.refresh()
    def refresh(self,*args):
        if not self.session or not self.prop.currentText():return
        prop=self.prop.currentText();p=self.session.state['properties'][prop];stage=self.stage.currentText()
        self.selected = set()
        self.reason.setCurrentIndex(0)
        self.unit.setEnabled(True)
        self.unit.setCurrentText('spectrum' if stage == 'PCA' else 'sample')
        self.record_samples = {row['File Name']: row['Sample'] for row in p['frame']}
        self.sample_files = {}
        for filename, sample in self.record_samples.items():
            self.sample_files.setdefault(sample, set()).add(filename)
        self.pca_exclusions = self.session.excluded(prop, 'PCA')
        context=(prop,stage)
        if self.table_context != context:self.filters={};self.table_context=context
        for widget in (self.xpc, self.ypc, self.scale):
            visible = (widget is not self.scale) == (stage == 'PCA')
            widget.setVisible(visible)
            self.plot_labels[widget].setVisible(visible)
        self.calc.setText('Refit PCA' if stage=='PCA' else f'Calculate Half {stage}')
        self.finish.setText('Finish PCA review / split' if stage=='PCA' else f'Finish Half {stage} review')
        self.rows=p['pca']['rows'] if stage=='PCA' else p['diagnostics'].get(stage,{}).get('rows',[])
        if stage=='PCA':
            oldx,oldy=self.xpc.currentIndex(),self.ypc.currentIndex()
            for combo in [self.xpc,self.ypc]:
                combo.blockSignals(True);combo.clear()
                combo.addItems([f'PC{i+1} ({v*100:.2f}%)' for i,v in enumerate(p['pca']['variance'])]);combo.blockSignals(False)
            self.xpc.blockSignals(True);self.ypc.blockSignals(True)
            self.xpc.setCurrentIndex(max(0,min(oldx,self.xpc.count()-1)));self.ypc.setCurrentIndex(min(oldy if oldy>=0 else 1,self.ypc.count()-1))
            self.xpc.blockSignals(False);self.ypc.blockSignals(False)
        self.update_model_details(prop, p, stage)
        self.update_review_navigation(prop, p, stage)
        self.populate_full();self.draw()
    def update_model_details(self, prop: str, state: dict, stage: str) -> None:
        while self.detail_fields.rowCount():
            self.detail_fields.removeRow(0)
        fields = []
        if stage == 'PCA':
            fields = [('PCA fit', f'{state["pca_round"]}/3'),
                      ('PCA exclusions', str(len(self.session.excluded(prop, "PCA"))))]
            basis = ('Refit required: decisions changed. Coordinates still use the previous fit.'
                     if state['pca_dirty'] else 'Current PCA basis.')
            note = basis + ' Finish review before calibration.'
        elif self.rows:
            row = self.rows[0]
            rank = int(row['Diagnostic Rank'])
            fields = [('Preprocessing', row['Preprocessing']),
                      ('Selected rank', str(int(row['Selection Rank']))),
                      ('Diagnostic rank', str(rank)),
                      ('Transform', state['config']['transform']),
                      ('Opposite-half RMSEP (original units)', f'{row["Opposite-half RMSEP"]:.4g}')]
            note = 'Rank reduced: available calibration/spectral rank is below 15. ' if rank < 15 else ''
            if stage == 'B':
                note += 'B reuses A settings. '
            note += 'Exclusions mark the original fit; no automatic refit.'
        elif stage == 'B' and state['finished']['A']:
            a = state['diagnostics']['A']['rows'][0]
            fields = [('Preprocessing from A', a['Preprocessing']),
                      ('Selected rank from A', str(int(a['Selection Rank']))),
                      ('Maximum exclusion diagnostic rank', '15')]
            note = 'Calculate B using A settings. Any saved B exclusions are preserved for review.'
        else:
            prior = 'PCA' if stage == 'A' else 'A'
            note = f'Half {stage} has not been calculated. Finish {prior} review first.'
        if stage != 'PCA':
            note += ('\n\nCandidates use |studentised residual| > 2.5. Leverage is shown separately. '
                     'These are Python diagnostics, distinct from OPUS F statistics.')
        for key, value in fields:
            self.detail_fields.addRow(self.wrap(key, 'detailKey'), self.wrap(str(value)))
        self.info.setText(note)

    def style_plot(self, mode: str) -> None:
        """Change display colors in place so the current selection and view stay intact."""
        theme = PLOT_THEMES[mode]
        dark = mode == 'night'
        ink = theme['ink']
        background = theme['background']
        statuses = dict(zip(PLOT_STATUS_MARKERS, theme['statuses']))
        self.figure.set_facecolor(background)
        for axes in self.figure.axes:
            axes.set_facecolor(background)
            axes.tick_params(colors=ink)
            for label in (axes.title, axes.xaxis.label, axes.yaxis.label,
                          axes.xaxis.get_offset_text(), axes.yaxis.get_offset_text()):
                label.set_color(ink)
            for spine in axes.spines.values():
                spine.set_edgecolor(ink)
        for line in self.ax.get_xgridlines() + self.ax.get_ygridlines():
            line.set_color(theme['grid'])
        for line in self.ax.lines:
            if line.get_label() == '1:1 line':
                line.set_color(theme['diagonal'])
        for text in self.ax.texts:
            text.set_color(ink if self.visible else theme['muted'])
            box = text.get_bbox_patch()
            if box is not None:
                box.set_facecolor(background)
                box.set_edgecolor(ink)
        if self.artist is not None:
            if self.plot_statuses:
                self.artist.set_color([statuses[status] for status in self.plot_statuses])
            else:
                self.artist.set_edgecolor(theme['muted'] if dark else 'face')
        for collection in self.ax.collections:
            label = collection.get_label()
            if label in statuses and self.plot_statuses:
                collection.set_color(statuses[label])
            elif label in ('Selected', '_selection'):
                collection.set_edgecolor(theme['selection'])
        legend = self.ax.get_legend()
        if legend is not None:
            legend.get_frame().set_facecolor(background)
            legend.get_frame().set_edgecolor(theme['grid'] if dark else '#ccc')
            legend.get_title().set_color(ink)
            for text, handle in zip(legend.get_texts(), legend.legend_handles):
                text.set_color(ink)
                label = text.get_text()
                if label in statuses and self.plot_statuses:
                    handle.set_color(statuses[label])
                elif label == 'Selected':
                    handle.set_edgecolor(theme['selection'])
                elif label == '1:1 line':
                    handle.set_color(theme['diagonal'])
        selection_color = theme['selection']
        if self.rect is not None:
            self.rect.set_props(edgecolor=selection_color)
        if self.lasso is not None:
            self.lasso.set_props(color=selection_color)

    def draw(self,*args,refresh_table=True,preserve_view=False):
        if not self.session:return
        p=self.session.state['properties'][self.prop.currentText()];stage=self.stage.currentText()
        mode=self.subset.currentIndex();self.visible=[r for r in self.rows if (mode==0 or (r['File Name'] not in p['decisions'])==(mode==1)) and self.matches_filters(r,p)]
        self.selected.intersection_update(r['File Name'] for r in self.visible)
        limits=(self.ax.get_xlim(),self.ax.get_ylim()) if preserve_view else None
        if self.colorbar is not None:self.colorbar.remove();self.colorbar=None
        self.ax.clear()
        self.artist = None
        self.ax.spines[['top', 'right']].set_visible(False)
        self.ax.set_axisbelow(True)
        self.plot_statuses = []
        if self.visible:
            if stage=='PCA':
                ix=max(0,self.xpc.currentIndex());iy=max(0,self.ypc.currentIndex())
                x=[r['scores'][ix] for r in self.visible];y=[r['scores'][iy] for r in self.visible]
                xlabel=self.xpc.currentText();ylabel=self.ypc.currentText()
            else:
                trans=self.scale.currentIndex()==0
                x=[r['Transformed Reference' if trans else 'Reference Value'] for r in self.visible]
                y=[r['Transformed Prediction' if trans else 'Calibration Prediction'] for r in self.visible]
                unit=p['config']['transform']+' scale' if trans else p['config']['units']
                xlabel=f'Measured ({unit})';ylabel=f'Calibration fit ({unit})'
                lo=min(min(x),min(y));hi=max(max(x),max(y));self.ax.plot([lo,hi],[lo,hi],'--',color='#70818a',lw=1,label='1:1 line')
                self.ax.text(.02,.98,engine.metric_label(x,y),transform=self.ax.transAxes,va='top',fontsize=8,bbox=dict(facecolor='white',alpha=.9))
            if self.colour.currentText()=='Reference value':colors=[r['Reference Value'] for r in self.visible]
            elif self.colour.currentText()=='Treatment':
                groups=sorted(set(str(r['Group']) for r in self.visible));colors=[groups.index(str(r['Group'])) for r in self.visible]
                from matplotlib import colormaps
                for i,g in enumerate(groups):self.ax.scatter([],[],color=colormaps['viridis'](i/max(1,len(groups)-1)),label=g)
            else:
                status_colors = dict(zip(PLOT_STATUS_MARKERS, PLOT_THEMES['light']['statuses']))
                self.plot_statuses = ['Excluded' if row['File Name'] in p['decisions'] else
                            'Candidate' if row.get('Concentration Candidate') else 'Retained'
                            for row in self.visible]
                colors = [status_colors[status] for status in self.plot_statuses]
                for label, marker in PLOT_STATUS_MARKERS.items():
                    self.ax.scatter([], [], color=status_colors[label], marker=marker, label=label)
            self.xy=np.column_stack([x,y]);self.artist=self.ax.scatter(x,y,c=colors,s=32,picker=5,alpha=.85)
            if self.plot_statuses:
                markers = {status: MarkerStyle(marker) for status, marker in PLOT_STATUS_MARKERS.items()}
                paths = {status: marker.get_path().transformed(marker.get_transform())
                         for status, marker in markers.items()}
                self.artist.set_paths([paths[status] for status in self.plot_statuses])
            if self.colour.currentText()=='Reference value':
                self.colorbar=self.figure.colorbar(self.artist,ax=self.ax,pad=.02);self.colorbar.set_label('Reference value ('+p['config']['units']+')')
            self.ax.scatter([],[],s=90,facecolors='none',edgecolors='#111',label='Selected')
            self.ax.legend(loc='lower right',fontsize=8,title='Treatment' if self.colour.currentText()=='Treatment' else None)
            chosen=[i for i,r in enumerate(self.visible) if r['File Name'] in self.selected]
            if chosen:self.ax.scatter(np.array(x)[chosen],np.array(y)[chosen],s=90,facecolors='none',edgecolors='#111',lw=1.4,label='_selection')
            self.ax.set(xlabel=xlabel,ylabel=ylabel,title=f'{self.prop.currentText()} — {"PCA" if stage=="PCA" else "Calibration half "+stage}')
            self.ax.grid(color='#dbe7e6', linewidth=.65)
        else:
            self.ax.set_axis_off()
            message = 'No spectra match the current view.' if self.rows else 'No calibration plot yet.'
            self.ax.text(.5, .5, message, transform=self.ax.transAxes, ha='center', color='#4a6165')
        if self.visible:
            self.ax.set_axis_on()
        if limits:self.ax.set_xlim(limits[0]);self.ax.set_ylim(limits[1])
        self.annotation=self.ax.annotate('',xy=(0,0),xytext=(12,12),textcoords='offset points',bbox=dict(boxstyle='round',fc='white',alpha=.95),fontsize=8)
        self.annotation.set_visible(False)
        self.figure.tight_layout()
        if refresh_table:self.populate()
        else:self.update_selection()
        self.selection_mode()
        self.style_plot(self.effective_appearance)
        self.canvas.draw_idle()

    def populate(self):
        self.syncing=True;self.table.setSortingEnabled(False)
        stage=self.stage.currentText();p=self.session.state['properties'][self.prop.currentText()]
        columns=['Sample','File Name','Group','Reference Value','Status']
        columns+=['Nearest File','Nearest Distance','Same Sample Neighbour'] if stage=='PCA' else ['Calibration Prediction','Transformed Reference','Transformed Prediction','Transformed Residual','Studentised Residual','Leverage','Concentration Candidate','Diagnostic Rank']
        self.table.clear();self.table.setColumnCount(len(columns));self.table.setHorizontalHeaderLabels([k+(' ▾' if k in self.filters else '') for k in columns]);self.table.setRowCount(len(self.visible))
        self.columns=columns
        for i,r in enumerate(self.visible):
            for j,key in enumerate(columns):
                value=('Excluded' if r['File Name'] in p['decisions'] else 'Retained') if key=='Status' else r.get(key,'')
                item=W.QTableWidgetItem();item.setData(QtCore.Qt.DisplayRole,value);item.setData(QtCore.Qt.UserRole,r['File Name']);self.table.setItem(i,j,item)
            if r['File Name'] in self.selected:
                for j in range(len(columns)):self.table.item(i,j).setSelected(True)
        self.table.setSortingEnabled(True);self.table.resizeColumnsToContents();self.syncing=False
        self.update_selection()
    def matches_filters(self, row, prop):
        for key, text in self.filters.items():
            value = ('Excluded' if row['File Name'] in prop['decisions'] else 'Retained') if key == 'Status' else row.get(key, '')
            if text.casefold() not in str(value).casefold():
                return False
        return True
    def set_filter(self, column, text):
        text = text.strip()
        if text:self.filters[column] = text
        else:self.filters.pop(column, None)
        self.draw()
    def clear_filters(self):
        self.filters.clear();self.draw()
    def header_filter(self, column):
        if not hasattr(self,'columns') or column < 0:return
        name=self.columns[column]
        text,ok=W.QInputDialog.getText(self,'Filter '+name,'Show values containing (case-insensitive):',text=self.filters.get(name,''))
        if ok:self.set_filter(name,text)
    def header_menu(self, position):
        header=self.table.horizontalHeader();column=header.logicalIndexAt(position)
        if column < 0:return
        name=self.columns[column];menu=W.QMenu(self)
        asc=menu.addAction('Sort ascending');desc=menu.addAction('Sort descending')
        menu.addSeparator();filt=menu.addAction('Filter: contains…');clear=menu.addAction('Clear this filter')
        action=menu.exec(header.mapToGlobal(position))
        if action == asc:self.table.sortItems(column,QtCore.Qt.AscendingOrder)
        elif action == desc:self.table.sortItems(column,QtCore.Qt.DescendingOrder)
        elif action == clear:self.set_filter(name,'')
        elif action == filt:self.header_filter(column)
    def clear_selection(self):
        self.selected.clear()
        if self.session:self.draw(preserve_view=True)
    def plot_key(self,event):
        if event.key == 'escape':self.clear_selection()
    def plot_click(self,event):
        if event.inaxes != self.ax or event.button != 1 or self.select_mode.currentIndex()!=0:return
        if self.canvas.widgetlock.locked() or getattr(event, '_mir_point_picked', False):
            return
        if self.artist is None or not self.artist.contains(event)[0]:
            self.clear_selection()

    def pick(self,event):
        if event.artist is not self.artist or self.select_mode.currentIndex()!=0 or self.canvas.widgetlock.locked():return
        click = getattr(event, 'mouseevent', None)
        if click is not None:
            # This click already selected a point. A redraw can move the axes before plot_click runs.
            click._mir_point_picked = True
        for i in event.ind:
            f=self.visible[int(i)]['File Name']
            if f in self.selected:self.selected.remove(f)
            else:self.selected.add(f)
        self.draw(preserve_view=True)
    def hover(self,event):
        if not self.artist or event.inaxes!=self.ax:return
        hit,detail=self.artist.contains(event)
        if hit:
            i=int(detail['ind'][0]);r=self.visible[i];self.annotation.xy=tuple(self.xy[i]);self.annotation.set_text(f'{r["Sample"]} | {r["File Name"]}\nTreatment: {r["Group"]} | Reference: {r["Reference Value"]}\nX: {self.xy[i,0]:.5g} | Y: {self.xy[i,1]:.5g}');self.annotation.set_visible(True)
        else:self.annotation.set_visible(False)
        self.canvas.draw_idle()
    def table_selection(self):
        if self.syncing:return
        selected={item.data(QtCore.Qt.UserRole) for item in self.table.selectedItems()}
        if selected == self.selected:return
        self.selected=selected;self.draw(refresh_table=False,preserve_view=True)
    def selection_mode(self,*args):
        for selector in [self.rect,self.lasso]:
            if selector:selector.disconnect_events()
        self.rect=self.lasso=None
        if not self.visible or self.canvas.widgetlock.locked():return
        def rectangle(a,b):
            if None in (a.xdata,a.ydata,b.xdata,b.ydata):return
            mask=(self.xy[:,0]>=min(a.xdata,b.xdata))&(self.xy[:,0]<=max(a.xdata,b.xdata))&(self.xy[:,1]>=min(a.ydata,b.ydata))&(self.xy[:,1]<=max(a.ydata,b.ydata))
            self.toggle_points(mask)
        def lasso(vertices):
            mask=PlotPath(vertices).contains_points(self.xy);self.toggle_points(mask)
        if self.select_mode.currentIndex()==1:self.rect=RectangleSelector(self.ax,rectangle,useblit=False,button=[1])
        if self.select_mode.currentIndex()==2:self.lasso=LassoSelector(self.ax,lasso,useblit=False,button=1)
        if self.effective_appearance == 'night':
            if self.rect is not None:
                self.rect.set_props(edgecolor=PLOT_THEMES['night']['selection'])
            if self.lasso is not None:
                self.lasso.set_props(color=PLOT_THEMES['night']['selection'])
    def toggle_points(self, mask):
        self.selected.symmetric_difference_update(r['File Name'] for r,hit in zip(self.visible,mask) if hit)
        self.draw(preserve_view=True)
    def populate_full(self,*args):
        if not self.session:return
        prop=self.prop.currentText();rows=engine.combined_rows(self.session,prop);total=len(rows)
        query=self.full_search.text().strip().casefold()
        rows=[r for r in rows if not query or any(query in str(v).casefold() for v in r.values())]
        columns=['Sample','File Name','Half','Group','Reference Value','Status','Exclusion Stage','Reason','Unit','Calibration Prediction','Diagnostic Rank']
        table=self.full_table;table.setSortingEnabled(False);table.clear();table.setColumnCount(len(columns));table.setHorizontalHeaderLabels(columns);table.setRowCount(len(rows))
        for i,row in enumerate(rows):
            for j,key in enumerate(columns):
                item=W.QTableWidgetItem();item.setData(QtCore.Qt.DisplayRole,row.get(key,''));table.setItem(i,j,item)
        table.setSortingEnabled(True);table.resizeColumnsToContents()
        excluded=len(self.session.excluded(prop))
        self.full_summary.setText(f'{prop}: {total} total spectra; {excluded} excluded; {total-excluded} retained; {len(rows)} shown. A/B predictions come from separate calibration fits. Review decisions in their original stage.')
    def calculate(self):
        if not self.session:return
        prop=self.prop.currentText();stage=self.stage.currentText()
        self.run(lambda:self.session.refit_pca(prop) if stage=='PCA' else self.session.calculate(prop,stage))
    def finish_review(self):
        def action():
            self.checkpoint();prop=self.prop.currentText();stage=self.stage.currentText()
            if stage=='PCA':self.session.finish_pca(prop);self.stage.setCurrentText('A')
            else:
                self.session.finish_half(prop,stage)
                if stage=='A':self.stage.setCurrentText('B')
        self.guard(action)
    def decision_targets(self) -> set[str]:
        targets = set(self.selected)
        if self.unit.currentText() == 'sample':
            samples = {self.record_samples[name] for name in targets}
            targets = set().union(*(self.sample_files[sample] for sample in samples))
        if self.stage.currentText() != 'PCA':
            targets -= self.pca_exclusions
        return targets

    def update_selection(self, *_args) -> None:
        if not self.session:
            return
        full = self.tabs.currentWidget() is self.full
        self.decision_controls.setVisible(bool(self.selected) and not full)
        if full:
            self.impact_label.clear()
            self.selection_label.setText('Full dataset is read-only. Make decisions in the original PCA, A or B stage.')
            return
        if not self.selected:
            self.impact_label.clear()
            self.selection_label.setText(f'{len(self.visible)} visible spectra. Select points or table rows to inspect them.')
            return
        targets = self.decision_targets()
        samples = {self.record_samples[name] for name in targets}
        selected_unit = 'spectrum' if len(self.selected) == 1 else 'spectra'
        self.selection_label.setText(f'{len(self.selected)} selected {selected_unit} · {len(self.visible)} visible')
        sample_label = 'sample' if len(samples) == 1 else 'samples'
        spectra_label = 'spectrum' if len(targets) == 1 else 'spectra'
        self.impact_label.setText(f'{len(samples)} {sample_label} · {len(targets)} {spectra_label}')
        self.impact_label.setToolTip(', '.join(sorted(map(str, samples))))
        if self.unit.currentText() == 'sample':
            message = 'Includes all replicates of the selected samples.'
            if self.stage.currentText() != 'PCA':
                message += ' Earlier PCA exclusions are kept.'
        else:
            message = 'Applies to the selected spectra.'
        self.unit_help.setText(message)

    def decision(self,restore=False):
        if not self.session or not self.selected:return
        prop = self.prop.currentText()
        stage = self.stage.currentText()
        targets = self.decision_targets()
        samples = len({self.record_samples[name] for name in targets})
        text = f'{"Restore" if restore else "Exclude"} {len(targets)} spectra from {samples} sample(s) in {prop}?'
        if targets:
            text += '\n\n' + '\n'.join(sorted(targets)[:18])
            if len(targets) > 18:
                text += f'\n… and {len(targets) - 18} more'
        if stage == 'PCA':
            text += '\n\nA changed decision requires a PCA refit and invalidates the split and both calibration reviews.'
        elif stage == 'A':
            text += '\n\nA changed decision invalidates the Half B calculation and review.'
        else:
            text += '\n\nA changed decision requires finishing the Half B review again.'
        if W.QMessageBox.question(self,'Confirm reviewed decision',text)!=W.QMessageBox.Yes:return
        def action():
            self.checkpoint();self.session.decide(prop,stage,self.selected,self.reason.currentText() if self.reason.currentIndex() else '',self.unit.currentText(),self.comment.text(),restore)
        self.guard(action)
    def exclude(self):self.decision(False)
    def restore(self):self.decision(True)
    def save_limit(self):self.guard(lambda:self.session.set_limit(self.limit.isChecked(),self.percent.value()))
    def save_plot(self):
        path=W.QFileDialog.getSaveFileName(self,'Save current plot','calibration.png','PNG (*.png);;PDF (*.pdf)')[0]
        if path:
            try:self.figure.savefig(path,dpi=180)
            except Exception as exc:self.error(str(exc))
    def open_pca(self):
        if not self.session:return
        path=self.session.folder/'PCA_viewer.html'
        self.run(lambda:core.render_viewer(self.session.payload(),path),lambda _:QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path))))
    def export_review(self):
        if not self.session:return
        path=W.QFileDialog.getSaveFileName(self,'Export review workbook',str(self.session.folder/'review.xlsx'),'Excel (*.xlsx)')[0]
        if path:self.run(lambda:self.session.export_review(path))
    def import_review(self):
        if not self.session:return
        path=W.QFileDialog.getOpenFileName(self,'Import saved Excel decisions','','Excel (*.xlsx)')[0]
        if path:
            self.checkpoint();self.run(lambda:self.session.import_review(path))
    def export(self):
        if not self.session:return
        lines=[]
        for prop,p in self.session.state['properties'].items():
            n=len(self.session.frame(prop));excluded=len(self.session.excluded(prop));lines.append(f'{prop}: {excluded} spectra excluded; {n-excluded} retained')
        if W.QMessageBox.question(self,'Preview cleaned dataset','\n'.join(lines)+'\n\nExport a new workbook and reports?')!=W.QMessageBox.Yes:return
        parent=W.QFileDialog.getExistingDirectory(self,'Choose export parent folder',str(self.session.folder))
        if parent:
            dest=Path(parent)/datetime.now().strftime('cleaned_%Y%m%d_%H%M%S_%f')
            self.run(lambda:self.session.export(dest),self.show_export_result)
    def closeEvent(self,event):
        if self.worker:
            W.QMessageBox.information(self,'Calculation in progress','Please wait for the current calculation to finish before closing.');event.ignore()
        else:event.accept()


def main():
    app=W.QApplication(sys.argv);app.setApplicationName('MIR Cleanup');app.setOrganizationName('Soil MIR')
    app.setApplicationVersion('1.4.0')
    icon_path = Path(__file__).resolve().parent / 'assets' / 'mir-cleanup-icon.png'
    if icon_path.exists():
        app.setWindowIcon(QtGui.QIcon(str(icon_path)))
    if '--verify-windows' in sys.argv:
        from mir_windows_verify import run
        sys.exit(run(app, sys.argv[1:]))
    window=Window();window.show()
    if '--open-session' in sys.argv:
        window.bind(engine.Session.load(sys.argv[sys.argv.index('--open-session')+1]))
    if '--verify-session' in sys.argv:
        # Developer verification operates on a temporary copy, never the supplied session.
        import tempfile, shutil, json
        source=Path(sys.argv[sys.argv.index('--verify-session')+1])
        output=Path(sys.argv[sys.argv.index('--verification-output')+1]);output.mkdir(parents=True,exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(prefix='mir-bundle-check-') as temp:
                folder=Path(temp)/'session'
                original=engine.Session.load(source)
                if 'spectra_dir' in original.state:
                    session=engine.Session.create(original.state['source'],original.state['spectra_dir'],folder,list(original.state['properties']))
                else:
                    shutil.copytree(source,folder);session=engine.Session.load(folder)
                for prop,p in session.state['properties'].items():
                    p['diagnostics']={};p['finished']={'A':False,'B':False}
                    session.finish_pca(prop)
                    session.calculate(prop,'A');session.finish_half(prop,'A');session.calculate(prop,'B');session.finish_half(prop,'B')
                window.bind(session);window.stage.setCurrentText('A');app.processEvents()
                window.grab().save(str(output/'app-calibration.png'))
                window.stage.setCurrentText('PCA');app.processEvents();window.grab().save(str(output/'app-pca.png'))
                session.export(output/'export')
                (output/'verification.json').write_text(json.dumps({'passed':True,'properties':list(session.state['properties'])}), encoding='utf-8')
            window.close();return
        except Exception:
            (output/'verification-error.txt').write_text(traceback.format_exc(), encoding='utf-8');raise
    sys.exit(app.exec())


if __name__=='__main__':main()
