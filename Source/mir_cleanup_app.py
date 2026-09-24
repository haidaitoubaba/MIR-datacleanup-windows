"""Mac/Windows desktop interface for staged MIR cleanup."""
from __future__ import annotations
import copy
import sys
import traceback
from datetime import datetime
from pathlib import Path
import numpy as np
from matplotlib.figure import Figure
from matplotlib.widgets import RectangleSelector, LassoSelector
from matplotlib.path import Path as PlotPath
import mir_cleanup_session as engine
import soil_mir_data_cleanup as core
from PySide6 import QtCore, QtGui, QtWidgets as W
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT


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
        self.zoom_button.setMenu(menu)
        self.zoom_button.setPopupMode(W.QToolButton.MenuButtonPopup)
        self.update_zoom_label()

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


class Setup(W.QDialog):
    def __init__(self,parent=None):
        super().__init__(parent);self.setWindowTitle('New cleanup session');self.resize(680,500)
        layout=W.QVBoxLayout(self);form=W.QFormLayout();layout.addLayout(form)
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
    def __init__(self):
        super().__init__();self.setWindowTitle('MIR Cleanup');self.resize(1320,820)
        self.session=None;self.undo_states=[];self.worker=None;self.rows=[];self.selected=set();self.syncing=False;self.visible=[];self.filters={};self.table_context=None
        self.colorbar=None
        self.figure=Figure(figsize=(9,5));self.canvas=FigureCanvasQTAgg(self.figure);self.ax=self.figure.subplots();self.canvas.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.canvas.mpl_connect('button_press_event',self.plot_click);self.canvas.mpl_connect('key_press_event',self.plot_key);self.canvas.mpl_connect('pick_event',self.pick);self.canvas.mpl_connect('motion_notify_event',self.hover)
        root=W.QWidget();self.setCentralWidget(root);layout=W.QVBoxLayout(root);layout.setContentsMargins(18,12,18,12)
        title=W.QLabel('MIR Cleanup');title.setStyleSheet('font-size:26px;font-weight:600;color:#164457');layout.addWidget(title)
        self.banner=W.QLabel('PCA review → Half A → Half B → Export • Explicit confirmation required for every exclusion');layout.addWidget(self.banner)
        top=W.QHBoxLayout();layout.addLayout(top)
        self.button(top,'New session',self.new);self.button(top,'Open session',self.open_session)
        self.button(top,'Locate original workbook',self.relocate)
        self.button(top,'Open results folder',self.open_folder)
        self.button(top,'Open cleaned workbook',self.open_cleaned)
        self.busy_label=W.QLabel('');top.addWidget(self.busy_label,1)
        controls=W.QHBoxLayout();layout.addLayout(controls)
        self.prop=W.QComboBox();self.prop.currentTextChanged.connect(self.refresh)
        self.stage=W.QComboBox();self.stage.addItems(['PCA','A','B']);self.stage.currentTextChanged.connect(self.refresh)
        self.xpc=W.QComboBox();self.ypc=W.QComboBox();self.xpc.currentIndexChanged.connect(self.draw);self.ypc.currentIndexChanged.connect(self.draw)
        self.scale=W.QComboBox();self.scale.addItems(['Modelled scale','Original units']);self.scale.currentIndexChanged.connect(self.draw)
        self.colour=W.QComboBox();self.colour.addItems(['Status','Treatment','Reference value']);self.colour.currentIndexChanged.connect(self.draw)
        self.subset=W.QComboBox();self.subset.addItems(['All in fitted model','Retained only','Excluded only']);self.subset.currentIndexChanged.connect(self.draw)
        for label,widget in [('Property',self.prop),('Stage',self.stage),('X PC',self.xpc),('Y PC',self.ypc),('Scale',self.scale),('Colour',self.colour),('Show',self.subset)]:
            controls.addWidget(W.QLabel(label));controls.addWidget(widget)
        self.info=W.QLabel('Start a new session or open an existing saved session.');self.info.setWordWrap(True);layout.addWidget(self.info)
        actions=W.QHBoxLayout();layout.addLayout(actions)
        self.calc=self.button(actions,'Refit PCA',self.calculate)
        self.finish=self.button(actions,'Finish PCA review',self.finish_review)
        self.button(actions,'Undo decision',self.undo)
        self.button(actions,'Open offline PCA',self.open_pca)
        self.button(actions,'Save plot PNG/PDF',self.save_plot)
        self.tabs=W.QTabWidget();layout.addWidget(self.tabs,1)
        plot=W.QWidget();pl=W.QVBoxLayout(plot);pl.setContentsMargins(0,0,0,0)
        self.toolbar=PlotToolbar(self.canvas,self);pl.addWidget(self.toolbar);pl.addWidget(self.canvas)
        self.select_mode=W.QComboBox();self.select_mode.addItems(['Click points','Rectangle selection','Lasso selection']);self.select_mode.currentIndexChanged.connect(self.selection_mode);self.toolbar.navigation_changed.connect(self.selection_mode)
        selection_controls=W.QHBoxLayout();selection_controls.addWidget(self.select_mode);self.button(selection_controls,'Clear selection',self.clear_selection);pl.addLayout(selection_controls);self.tabs.addTab(plot,'Plot')
        self.table=W.QTableWidget();self.table.setSelectionBehavior(W.QAbstractItemView.SelectRows);self.table.setSelectionMode(W.QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(W.QAbstractItemView.NoEditTriggers);self.table.itemSelectionChanged.connect(self.table_selection)
        data=W.QWidget();dl=W.QVBoxLayout(data);dl.setContentsMargins(0,0,0,0)
        table_controls=W.QHBoxLayout();table_controls.addWidget(W.QLabel('Click a heading to sort; double-click a heading to filter.'),1)
        self.button(table_controls,'Clear filters',self.clear_filters);self.button(table_controls,'Clear selection',self.clear_selection);dl.addLayout(table_controls);dl.addWidget(self.table);self.tabs.addTab(data,'Data sheet')
        header=self.table.horizontalHeader();header.setContextMenuPolicy(QtCore.Qt.CustomContextMenu);header.customContextMenuRequested.connect(self.header_menu);header.sectionDoubleClicked.connect(self.header_filter)
        self.full_table=W.QTableWidget();self.full_table.setEditTriggers(W.QAbstractItemView.NoEditTriggers);self.full_table.setAlternatingRowColors(True)
        full=W.QWidget();fl=W.QVBoxLayout(full);self.full_summary=W.QLabel();self.full_summary.setWordWrap(True);fl.addWidget(self.full_summary);fl.addWidget(self.full_table);self.tabs.addTab(full,'Full dataset (A + B)')
        self.full_search=W.QLineEdit();self.full_search.setPlaceholderText('Filter full dataset: sample, filename, half, status or reason');self.full_search.textChanged.connect(self.populate_full);fl.insertWidget(1,self.full_search)
        self.selection_label=W.QLabel('No records selected');layout.addWidget(self.selection_label)
        decision=W.QHBoxLayout();layout.addLayout(decision)
        self.reason=W.QComboBox();self.reason.addItems(['','redundancy','spectral_quality','range','concentration'])
        self.unit=W.QComboBox();self.unit.addItems(['spectrum','sample'])
        self.comment=W.QLineEdit();self.comment.setPlaceholderText('Optional comment / supporting evidence')
        for label,widget in [('Reason (optional)',self.reason),('Unit',self.unit)]:decision.addWidget(W.QLabel(label));decision.addWidget(widget)
        decision.addWidget(self.comment,1);self.exclude_button=self.button(decision,'Confirm exclusion',self.exclude);self.restore_button=self.button(decision,'Restore selected',self.restore)
        self.tabs.currentChanged.connect(lambda _: [b.setEnabled(self.tabs.currentWidget()!=full) for b in [self.exclude_button,self.restore_button]])
        bottom=W.QHBoxLayout();layout.addLayout(bottom)
        self.limit=W.QCheckBox('Enable concentration limit');self.percent=W.QDoubleSpinBox();self.percent.setRange(0,100);self.percent.setDecimals(3);self.percent.setValue(1);self.percent.setSuffix(' %')
        bottom.addWidget(self.limit);bottom.addWidget(self.percent);self.button(bottom,'Save limit',self.save_limit)
        self.button(bottom,'Export review Excel',self.export_review);self.button(bottom,'Import review Excel',self.import_review)
        bottom.addStretch();self.button(bottom,'Export cleaned dataset',self.export)
        note=W.QLabel('Python concentration candidates: |studentised residual| > 2.5; leverage shown separately. These are not OPUS F statistics.');note.setStyleSheet('color:#626c74');layout.addWidget(note)
        self.setStyleSheet('QPushButton {padding:6px 10px;} QComboBox,QLineEdit {padding:4px;} QTableWidget {alternate-background-color:#f0f6f8;}')
        self.table.setAlternatingRowColors(True);self.rect=None;self.lasso=None;self.artist=None
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
        self.centralWidget().setEnabled(False);self.busy_label.setText('Working…');W.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        self.worker=Worker(fn)
        self._completed_callback=done
        self.worker.done.connect(self.work_done);self.worker.failed.connect(self.error)
        self.worker.finished.connect(self.work_finished);self.worker.start()
    @QtCore.Slot(object)
    def work_done(self,result):
        if self._completed_callback:self._completed_callback(result)
    @QtCore.Slot()
    def work_finished(self):
        self.worker.wait();self.worker.deleteLater();self.worker=None;self.centralWidget().setEnabled(True);self.busy_label.setText('');W.QApplication.restoreOverrideCursor();self.refresh()
    def guard(self,fn):
        if not self.session:return
        try:fn()
        except Exception as exc:self.error(str(exc))
        self.refresh()
    def bind(self,session):
        self.session=session;self.undo_states=[];self.prop.blockSignals(True);self.prop.clear();self.prop.addItems(list(session.state['properties']));self.prop.blockSignals(False)
        self.limit.setChecked(session.state['limit']=='enable');self.percent.setValue(session.state['percent']);self.stage.setCurrentText('PCA');self.refresh()
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
        self.selected=set();self.reason.setCurrentText('')
        self.unit.setEnabled(True);self.unit.setCurrentText('spectrum' if stage=='PCA' else 'sample')
        context=(prop,stage)
        if self.table_context != context:self.filters={};self.table_context=context
        self.xpc.setVisible(stage=='PCA');self.ypc.setVisible(stage=='PCA');self.scale.setVisible(stage!='PCA')
        self.calc.setText('Refit PCA' if stage=='PCA' else f'Calculate half {stage}')
        self.finish.setText('Finish PCA review / split' if stage=='PCA' else f'Finish {stage} review')
        self.rows=p['pca']['rows'] if stage=='PCA' else p['diagnostics'].get(stage,{}).get('rows',[])
        if stage=='PCA':
            oldx,oldy=self.xpc.currentIndex(),self.ypc.currentIndex()
            for combo in [self.xpc,self.ypc]:
                combo.blockSignals(True);combo.clear()
                combo.addItems([f'PC{i+1} ({v*100:.2f}%)' for i,v in enumerate(p['pca']['variance'])]);combo.blockSignals(False)
            self.xpc.blockSignals(True);self.ypc.blockSignals(True)
            self.xpc.setCurrentIndex(max(0,min(oldx,self.xpc.count()-1)));self.ypc.setCurrentIndex(min(oldy if oldy>=0 else 1,self.ypc.count()-1))
            self.xpc.blockSignals(False);self.ypc.blockSignals(False)
            self.info.setText(f'{prop} • PCA fit {p["pca_round"]}/3 • '+('REFIT REQUIRED: decisions changed; coordinates still use the previous fit.' if p['pca_dirty'] else 'Current PCA basis.')+
                f' {len(self.session.excluded(prop,"PCA"))} PCA exclusions. Finish review before calibration.')
        elif self.rows:
            r=self.rows[0];rank=int(r['Diagnostic Rank']);note=' Rank reduced: available calibration/spectral rank is below 15.' if rank<15 else ''
            self.info.setText(f'{prop} • Calibration {stage} • {r["Preprocessing"]} • selected rank {int(r["Selection Rank"])} • diagnostic rank {rank} • transform: {p["config"]["transform"]} • opposite-half RMSEP (original units): {r["Opposite-half RMSEP"]:.4g}.{note} {'B reuses A settings. ' if stage=='B' else ''}Exclusions mark the original fit; no automatic refit.')
        elif stage=='B' and p['finished']['A']:
            a=p['diagnostics']['A']['rows'][0]
            self.info.setText(f'Calculate B using A settings: {a["Preprocessing"]}, selected rank {int(a["Selection Rank"])}; exclusion diagnostic maximum rank 15. Any saved B exclusions are preserved for review.')
        else:self.info.setText(f'Half {stage} has not been calculated. Finish '+('PCA review first.' if stage=='A' else 'A review first.'))
        self.banner.setText(f'PCA: {"finished" if p["pca_done"] else "review"} → A: {"finished" if p["finished"]["A"] else "review"} → B: {"finished" if p["finished"]["B"] else "review"} → Export')
        self.populate_full();self.draw()
    def draw(self,*args,refresh_table=True,preserve_view=False):
        if not self.session:return
        p=self.session.state['properties'][self.prop.currentText()];stage=self.stage.currentText()
        mode=self.subset.currentIndex();self.visible=[r for r in self.rows if (mode==0 or (r['File Name'] not in p['decisions'])==(mode==1)) and self.matches_filters(r,p)]
        self.selected.intersection_update(r['File Name'] for r in self.visible)
        limits=(self.ax.get_xlim(),self.ax.get_ylim()) if preserve_view else None
        if self.colorbar is not None:self.colorbar.remove();self.colorbar=None
        self.ax.clear();self.artist=None
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
                self.ax.legend(title='Treatment',fontsize=8,loc='lower right')
            else:
                colors=['#bd4146' if r['File Name'] in p['decisions'] else '#e6a12d' if r.get('Concentration Candidate') else '#218697' for r in self.visible]
                for label,col in [('Retained','#218697'),('Candidate','#e6a12d'),('Excluded','#bd4146')]:self.ax.scatter([],[],color=col,label=label)
                self.ax.legend(fontsize=8,loc='lower right')
            self.xy=np.column_stack([x,y]);self.artist=self.ax.scatter(x,y,c=colors,s=32,picker=5,alpha=.85)
            if self.colour.currentText()=='Reference value':
                self.colorbar=self.figure.colorbar(self.artist,ax=self.ax,pad=.02);self.colorbar.set_label('Reference value ('+p['config']['units']+')')
            self.ax.scatter([],[],s=90,facecolors='none',edgecolors='#111',label='Selected')
            self.ax.legend(loc='lower right',fontsize=8,title='Treatment' if self.colour.currentText()=='Treatment' else None)
            chosen=[i for i,r in enumerate(self.visible) if r['File Name'] in self.selected]
            if chosen:self.ax.scatter(np.array(x)[chosen],np.array(y)[chosen],s=90,facecolors='none',edgecolors='#111',lw=1.4)
            self.ax.set(xlabel=xlabel,ylabel=ylabel,title=f'{self.prop.currentText()} — {"PCA" if stage=="PCA" else "Calibration half "+stage}')
            self.ax.grid(alpha=.18)
        if limits:self.ax.set_xlim(limits[0]);self.ax.set_ylim(limits[1])
        self.annotation=self.ax.annotate('',xy=(0,0),xytext=(12,12),textcoords='offset points',bbox=dict(boxstyle='round',fc='white',alpha=.95),fontsize=8)
        self.annotation.set_visible(False);self.figure.tight_layout();self.canvas.draw_idle()
        if refresh_table:self.populate()
        else:self.selection_label.setText(f'{len(self.selected)} selected spectra • {len(self.visible)} visible • selecting does not exclude')
        self.selection_mode()
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
        self.selection_label.setText(f'{len(self.selected)} selected spectra • {len(self.visible)} visible • selecting does not exclude')
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
        if self.canvas.widgetlock.locked():return
        if self.artist is None or not self.artist.contains(event)[0]:self.clear_selection()
    def pick(self,event):
        if event.artist is not self.artist or self.select_mode.currentIndex()!=0 or self.canvas.widgetlock.locked():return
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
    def decision(self,restore=False):
        if not self.session or not self.selected:return
        prop=self.prop.currentText();stage=self.stage.currentText();frame=self.session.frame(prop)
        targets=set(self.selected)
        if self.unit.currentText()=='sample':targets=set(frame.loc[frame.Sample.isin(frame.loc[frame['File Name'].isin(targets),'Sample']),'File Name'])
        samples=frame.loc[frame['File Name'].isin(targets),'Sample'].nunique()
        text=f'{"Restore" if restore else "Exclude"} {len(targets)} spectra from {samples} sample(s) in {prop}?\n'+ '\n'.join(sorted(targets)[:18])
        text+='\nEarlier-stage changes invalidate dependent models and later confirmations.'
        if W.QMessageBox.question(self,'Confirm reviewed decision',text)!=W.QMessageBox.Yes:return
        def action():
            self.checkpoint();self.session.decide(prop,stage,self.selected,self.reason.currentText(),self.unit.currentText(),self.comment.text(),restore)
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
            self.run(lambda:self.session.export(dest),lambda p:W.QMessageBox.information(self,'Export complete',f'Cleaned workbook and reports saved in:\n{p}'))
    def closeEvent(self,event):
        if self.worker:
            W.QMessageBox.information(self,'Calculation in progress','Please wait for the current calculation to finish before closing.');event.ignore()
        else:event.accept()


def main():
    app=W.QApplication(sys.argv);app.setApplicationName('MIR Cleanup');app.setOrganizationName('Soil MIR')
    app.setApplicationVersion('1.2.1 Windows build 1')
    icon_path=Path(__file__).resolve().parent/'assets'/'mir-cleanup-icon.png'
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
