# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'resources/ui/open_session.ui'
#
# Created by: PyQt5 UI code generator 5.11.3
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_DialogOpenSession(object):
    def setupUi(self, DialogOpenSession):
        DialogOpenSession.setObjectName("DialogOpenSession")
        DialogOpenSession.setWindowModality(QtCore.Qt.NonModal)
        DialogOpenSession.resize(290, 402)
        DialogOpenSession.setModal(False)
        self.verticalLayout = QtWidgets.QVBoxLayout(DialogOpenSession)
        self.verticalLayout.setObjectName("verticalLayout")
        self.horizontalLayout_3 = QtWidgets.QHBoxLayout()
        self.horizontalLayout_3.setObjectName("horizontalLayout_3")
        self.verticalLayout_2 = QtWidgets.QVBoxLayout()
        self.verticalLayout_2.setSpacing(0)
        self.verticalLayout_2.setObjectName("verticalLayout_2")
        self.labelSessionsFolder = QtWidgets.QLabel(DialogOpenSession)
        self.labelSessionsFolder.setAlignment(QtCore.Qt.AlignRight|QtCore.Qt.AlignTrailing|QtCore.Qt.AlignVCenter)
        self.labelSessionsFolder.setObjectName("labelSessionsFolder")
        self.verticalLayout_2.addWidget(self.labelSessionsFolder)
        self.horizontalLayout = QtWidgets.QHBoxLayout()
        self.horizontalLayout.setObjectName("horizontalLayout")
        self.currentSessionsFolder = QtWidgets.QLabel(DialogOpenSession)
        self.currentSessionsFolder.setStyleSheet("font-style :  italic")
        self.currentSessionsFolder.setAlignment(QtCore.Qt.AlignRight|QtCore.Qt.AlignTrailing|QtCore.Qt.AlignVCenter)
        self.currentSessionsFolder.setObjectName("currentSessionsFolder")
        self.horizontalLayout.addWidget(self.currentSessionsFolder)
        self.verticalLayout_2.addLayout(self.horizontalLayout)
        self.horizontalLayout_3.addLayout(self.verticalLayout_2)
        self.toolButtonFolder = QtWidgets.QToolButton(DialogOpenSession)
        icon = QtGui.QIcon.fromTheme("folder-open")
        self.toolButtonFolder.setIcon(icon)
        self.toolButtonFolder.setObjectName("toolButtonFolder")
        self.horizontalLayout_3.addWidget(self.toolButtonFolder)
        self.verticalLayout.addLayout(self.horizontalLayout_3)
        self.widgetSpacer = QtWidgets.QWidget(DialogOpenSession)
        self.widgetSpacer.setObjectName("widgetSpacer")
        self.verticalLayout_3 = QtWidgets.QVBoxLayout(self.widgetSpacer)
        self.verticalLayout_3.setContentsMargins(-1, 0, -1, 0)
        self.verticalLayout_3.setSpacing(0)
        self.verticalLayout_3.setObjectName("verticalLayout_3")
        spacerItem = QtWidgets.QSpacerItem(20, 26, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Minimum)
        self.verticalLayout_3.addItem(spacerItem)
        self.verticalLayout.addWidget(self.widgetSpacer)
        self.progressBar = QtWidgets.QProgressBar(DialogOpenSession)
        self.progressBar.setProperty("value", 24)
        self.progressBar.setTextVisible(False)
        self.progressBar.setOrientation(QtCore.Qt.Horizontal)
        self.progressBar.setInvertedAppearance(False)
        self.progressBar.setTextDirection(QtWidgets.QProgressBar.BottomToTop)
        self.progressBar.setObjectName("progressBar")
        self.verticalLayout.addWidget(self.progressBar)
        self.horizontalLayout_2 = QtWidgets.QHBoxLayout()
        self.horizontalLayout_2.setObjectName("horizontalLayout_2")
        self.label = QtWidgets.QLabel(DialogOpenSession)
        self.label.setObjectName("label")
        self.horizontalLayout_2.addWidget(self.label)
        self.filterBar = OpenSessionFilterBar(DialogOpenSession)
        self.filterBar.setObjectName("filterBar")
        self.horizontalLayout_2.addWidget(self.filterBar)
        self.verticalLayout.addLayout(self.horizontalLayout_2)
        self.sessionList = QtWidgets.QTreeWidget(DialogOpenSession)
        self.sessionList.setAlternatingRowColors(False)
        self.sessionList.setRootIsDecorated(False)
        self.sessionList.setHeaderHidden(True)
        self.sessionList.setObjectName("sessionList")
        self.sessionList.headerItem().setText(0, "1")
        self.verticalLayout.addWidget(self.sessionList)
        self.buttonBox = QtWidgets.QDialogButtonBox(DialogOpenSession)
        self.buttonBox.setEnabled(True)
        self.buttonBox.setOrientation(QtCore.Qt.Horizontal)
        self.buttonBox.setStandardButtons(QtWidgets.QDialogButtonBox.Cancel|QtWidgets.QDialogButtonBox.Ok)
        self.buttonBox.setObjectName("buttonBox")
        self.verticalLayout.addWidget(self.buttonBox)

        self.retranslateUi(DialogOpenSession)
        self.buttonBox.accepted.connect(DialogOpenSession.accept)
        self.buttonBox.rejected.connect(DialogOpenSession.reject)
        QtCore.QMetaObject.connectSlotsByName(DialogOpenSession)

    def retranslateUi(self, DialogOpenSession):
        _translate = QtCore.QCoreApplication.translate
        DialogOpenSession.setWindowTitle(_translate("DialogOpenSession", "Open Session"))
        self.labelSessionsFolder.setText(_translate("DialogOpenSession", "<html><head/><body><p><span style=\" font-size:9pt; font-weight:600;\">Sessions Folder :</span></p></body></html>"))
        self.currentSessionsFolder.setText(_translate("DialogOpenSession", "/home/user/Ray Sessions"))
        self.toolButtonFolder.setText(_translate("DialogOpenSession", "Folder"))
        self.progressBar.setFormat(_translate("DialogOpenSession", "%p%"))
        self.label.setText(_translate("DialogOpenSession", "Filter :"))

from surclassed_widgets import OpenSessionFilterBar
