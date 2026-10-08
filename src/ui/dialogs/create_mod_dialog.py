"""Create a mod project or edit its details later."""
from __future__ import annotations

import re

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
)

from mods.project import ModManager, ModProject, slugify_mod_id
from ui.context import AppContext
from ui.widgets import button, label

VERSION = re.compile(r"^\d+(\.\d+){0,3}$")


class CreateModDialog(QDialog):
    def __init__(self, ctx: AppContext, parent=None, mod: ModProject | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.mod = mod
        self.mod_manager = ModManager(ctx.settings.workspace)
        self.created_mod: ModProject | None = None
        editing = mod is not None

        self.setWindowTitle("Mod details" if editing else "New mod")
        self.setModal(True)
        self.setMinimumWidth(560)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 20)
        lay.setSpacing(14)
        lay.addWidget(label("Mod details" if editing else "New mod", "H1"))
        lay.addWidget(label(
            "These details are written to mod.manifest and shown in the game's mod list."
            if editing else "Name your mod. You can change everything except the mod ID later.",
            "Dim", wrap=True))

        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        self.txt_name = QLineEdit(mod.name if mod else "")
        self.txt_name.setPlaceholderText("e.g. Better Longswords")
        self.txt_name.textChanged.connect(self._on_name_changed)
        form.addRow("Name", self.txt_name)

        self.txt_id = QLineEdit(mod.id if mod else "")
        self.txt_id.setPlaceholderText("better_longswords")
        self.txt_id.setReadOnly(editing)
        self.txt_id.setToolTip("Lowercase letters and underscores only. Used as the folder name in KCD2/Mods.")
        self.txt_id.textEdited.connect(lambda _: self._validate())
        form.addRow("Mod ID", self.txt_id)

        self.txt_author = QLineEdit(mod.author if mod else self.ctx.settings.default_author)
        self.txt_author.setPlaceholderText("Your name")
        form.addRow("Author", self.txt_author)

        self.txt_version = QLineEdit(mod.version if mod else "0.1.0")
        self.txt_version.textChanged.connect(lambda _: self._validate())
        form.addRow("Version", self.txt_version)

        self.txt_desc = QPlainTextEdit(mod.description if mod else "")
        self.txt_desc.setPlaceholderText("What does this mod change?")
        self.txt_desc.setFixedHeight(90)
        form.addRow("Description", self.txt_desc)
        lay.addLayout(form)

        self.lbl_error = label("", "Error", wrap=True)
        lay.addWidget(self.lbl_error)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = button("Cancel")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        self.btn_ok = button("Save" if editing else "Create mod", "check" if editing else "plus", "Primary")
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self._submit)
        row.addWidget(self.btn_ok)
        lay.addLayout(row)
        self._validate()

    def _on_name_changed(self, text: str) -> None:
        if self.mod is None and not self.txt_id.isModified():
            self.txt_id.setText(slugify_mod_id(text) if text.strip() else "")
        self._validate()

    def _validate(self) -> bool:
        problem = ""
        mod_id = self.txt_id.text().strip()
        if not self.txt_name.text().strip():
            problem = " "
        elif not re.fullmatch(r"[a-z][a-z_]{0,63}", mod_id):
            problem = "The mod ID may only contain lowercase letters and underscores and must start with a letter."
        elif self.mod is None and self.mod_manager.get_mod(mod_id):
            problem = f"A mod with the ID '{mod_id}' already exists."
        elif not VERSION.fullmatch(self.txt_version.text().strip()):
            problem = "Use a version like 1.0 or 1.0.2."
        self.lbl_error.setText(problem.strip())
        self.btn_ok.setEnabled(not problem)
        return not problem

    def _submit(self) -> None:
        if not self._validate():
            return
        name = self.txt_name.text().strip()
        author = self.txt_author.text().strip()
        version = self.txt_version.text().strip()
        description = self.txt_desc.toPlainText().strip()
        if author:
            self.ctx.settings.default_author = author
            self.ctx.settings.save()
        if self.mod is not None:
            self.mod.name, self.mod.author = name, author
            self.mod.version, self.mod.description = version, description
            self.mod.save()
            self.created_mod = self.mod
        else:
            self.created_mod = self.mod_manager.create_mod(
                name=name, mod_id=self.txt_id.text().strip(), author=author,
                version=version, description=description)
        self.accept()
