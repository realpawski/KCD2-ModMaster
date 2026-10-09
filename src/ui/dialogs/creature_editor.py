"""Editor for a custom NPC or animal: look, body, behaviour and strength."""
from __future__ import annotations

import copy
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from creatures import generator
from creatures.gamedata import BaseBody, same_skeleton
from creatures.model import STAT_NAMES, CreatureDefinition, attitude, attitudes_for
from ui.widgets import StatusPill, button, label


@dataclass
class ModelOption:
    asset_id: str
    name: str
    path: str
    skeleton: str


def _section(title: str) -> QWidget:
    return label(title, "Section")


class CreatureEditorDialog(QDialog):
    def __init__(self, creature: CreatureDefinition, bodies: dict[str, BaseBody], models: list[ModelOption],
                 parent=None):
        super().__init__(parent)
        self.creature = copy.deepcopy(creature)
        self.bodies = bodies
        self.models = models
        self.saved: CreatureDefinition | None = None
        self.setWindowTitle(f"Creature — {creature.name}")
        self.setModal(True)
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.resize(min(1100, screen.width() - 80), min(820, screen.height() - 80))

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 18)
        root.setSpacing(14)
        head = QHBoxLayout()
        self.lbl_title = label(creature.name, "H1")
        head.addWidget(self.lbl_title)
        self.pill_kind = StatusPill("", "accent")
        head.addWidget(self.pill_kind)
        head.addStretch(1)
        root.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(18)
        form = QWidget()
        self.form = QVBoxLayout(form)
        self.form.setContentsMargins(0, 0, 8, 0)
        self.form.setSpacing(10)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(form)
        body.addWidget(scroll, 1)
        body.addWidget(self._build_summary())
        root.addLayout(body, 1)

        self._build_identity()
        self._build_look()
        self._build_body()
        self._build_behaviour()
        self._build_strength()
        self.form.addStretch(1)

        foot = QHBoxLayout()
        foot.addStretch(1)
        cancel = button("Cancel")
        cancel.clicked.connect(self.reject)
        foot.addWidget(cancel)
        self.btn_save = button("Save creature", "check", "Primary")
        self.btn_save.clicked.connect(self._save)
        foot.addWidget(self.btn_save)
        root.addLayout(foot)

        self._fill_bodies()
        self._update()

    # --- form ----------------------------------------------------------------------------------------------
    def _build_identity(self) -> None:
        self.form.addWidget(_section("NAME"))
        self.txt_name = QLineEdit(self.creature.name)
        self.txt_name.setPlaceholderText("Shown in the in-game spawn menu")
        self.txt_name.textChanged.connect(self._update)
        self.form.addWidget(self.txt_name)

    def _build_look(self) -> None:
        self.form.addWidget(_section("LOOK"))
        self.cb_model = QComboBox()
        self.cb_model.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cb_model.setMinimumContentsLength(24)
        self.cb_model.addItem("The body's own game look", "")
        for m in self.models:
            self.cb_model.addItem(f"{m.name}  ·  {m.path}", m.path)
        index = self.cb_model.findData(self.creature.model_path)
        self.cb_model.setCurrentIndex(max(0, index))
        self.cb_model.currentIndexChanged.connect(self._fill_bodies)
        self.form.addWidget(self.cb_model)
        self.form.addWidget(label("Your rigged models appear here after Export to KCD2 with Rigged selected.",
                                  "Muted", wrap=True))

    def _build_body(self) -> None:
        self.form.addWidget(_section("BODY"))
        self.cb_body = QComboBox()
        self.cb_body.currentIndexChanged.connect(self._body_changed)
        self.form.addWidget(self.cb_body)
        self.lbl_temperament = label("", "Muted", wrap=True)
        self.form.addWidget(self.lbl_temperament)

    def _build_behaviour(self) -> None:
        self.form.addWidget(_section("BEHAVIOUR"))
        self.behaviour_box = QVBoxLayout()
        self.behaviour_box.setSpacing(6)
        self.form.addLayout(self.behaviour_box)
        self.attitude_group = QButtonGroup(self)
        self.attitude_group.buttonClicked.connect(lambda _b: self._update())

    def _build_strength(self) -> None:
        self.form.addWidget(_section("STRENGTH"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        self.sl_combat = QSlider(Qt.Horizontal)
        self.sl_combat.setRange(0, 100)
        self.sl_combat.setValue(round(self.creature.combat_level * 100))
        self.sl_combat.valueChanged.connect(self._update)
        self.lbl_combat = label("", "Muted")
        grid.addWidget(label("Fighting skill"), 0, 0)
        grid.addWidget(self.sl_combat, 0, 1)
        grid.addWidget(self.lbl_combat, 0, 2)
        self.sp_health = QSpinBox()
        self.sp_health.setRange(1, 10000)
        self.sp_health.setValue(self.creature.health)
        self.sp_health.setSuffix(" HP")
        self.sp_health.valueChanged.connect(self._update)
        grid.addWidget(label("Health"), 1, 0)
        grid.addWidget(self.sp_health, 1, 1)
        grid.addWidget(label("100 is a normal creature", "Muted"), 1, 2)
        self.stat_spins: dict[str, QSpinBox] = {}
        for row, name in enumerate(STAT_NAMES, start=2):
            spin = QSpinBox()
            spin.setRange(0, 30)
            spin.setSpecialValueText("Game default")
            spin.setValue(getattr(self.creature, name))
            spin.valueChanged.connect(self._update)
            self.stat_spins[name] = spin
            grid.addWidget(label(name.title()), row, 0)
            grid.addWidget(spin, row, 1)
        grid.addWidget(label("Strength hits harder, Agility is quicker, Vitality lasts longer. Game levels "
                             "run up to 30.", "Muted", wrap=True), 2, 2, 3, 1)
        grid.setColumnStretch(1, 1)
        self.form.addLayout(grid)

    def _build_summary(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(330)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(label("IN GAME", "Section"))
        self.lbl_summary = label("", wrap=True)
        self.lbl_summary.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        lay.addWidget(self.lbl_summary)
        lay.addWidget(label("CHECKS", "Section"))
        self.lbl_issues = label("", "Muted", wrap=True)
        lay.addWidget(self.lbl_issues)
        lay.addStretch(1)
        return panel

    # --- behaviour ------------------------------------------------------------------------------------------
    def _model(self) -> ModelOption | None:
        path = self.cb_model.currentData()
        return next((m for m in self.models if m.path == path), None)

    def _fill_bodies(self) -> None:
        model = self._model()
        current = self.cb_body.currentData() or self.creature.base_class
        options = [b for b in self.bodies.values() if model is None or same_skeleton(b.skeleton, model.skeleton)]
        if model is not None and not options:
            options = list(self.bodies.values())
        self.cb_body.blockSignals(True)
        self.cb_body.clear()
        for b in sorted(options, key=lambda b: b.entity_class):
            self.cb_body.addItem(b.entity_class, b.entity_class)
        self.cb_body.setCurrentIndex(max(0, self.cb_body.findData(current)))
        self.cb_body.blockSignals(False)
        self._body_changed()

    def _body_changed(self) -> None:
        body = self.bodies.get(self.cb_body.currentData())
        self.lbl_temperament.setText(body.temperament if body else "")
        chosen = self.attitude_group.checkedButton()
        key = chosen.property("key") if chosen else self.creature.attitude
        for b in self.attitude_group.buttons():
            self.attitude_group.removeButton(b)
        while self.behaviour_box.count():
            item = self.behaviour_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        base = self.cb_body.currentData() or ""
        selected = attitude(base, key).key
        for a in attitudes_for(base):
            radio = QRadioButton(a.label)
            radio.setProperty("key", a.key)
            radio.setChecked(a.key == selected)
            self.attitude_group.addButton(radio)
            self.behaviour_box.addWidget(radio)
            hint = label(a.description, "Muted", wrap=True)
            hint.setContentsMargins(26, 0, 0, 4)
            self.behaviour_box.addWidget(hint)
        self._update()

    def _collect(self) -> CreatureDefinition:
        c = copy.deepcopy(self.creature)
        c.name = self.txt_name.text().strip() or c.name
        c.model_path = self.cb_model.currentData() or ""
        model = self._model()
        c.workspace_asset_id = model.asset_id if model else ""
        c.base_class = self.cb_body.currentData() or c.base_class
        chosen = self.attitude_group.checkedButton()
        c.attitude = chosen.property("key") if chosen else c.attitude
        c.combat_level = self.sl_combat.value() / 100
        c.health = self.sp_health.value()
        for name, spin in self.stat_spins.items():
            setattr(c, name, spin.value())
        return c

    def _update(self) -> None:
        c = self._collect()
        self.lbl_title.setText(c.name)
        self.pill_kind.set("NPC" if c.is_human else "Animal", "accent")
        self.lbl_combat.setText(f"{self.sl_combat.value()} %")
        body = self.bodies.get(c.base_class)
        att = attitude(c.base_class, c.attitude)
        stats = ", ".join(f"{k.title()} {v}" for k, v in c.stats().items()) or "game default stats"
        look = f"your model {c.model_path.rsplit('/', 1)[-1]}" if c.model_path else f"the {c.base_class} look"
        self.lbl_summary.setText(
            f"<b>{c.name}</b> spawns from the ModMaster menu under "
            f"<b>{'NPCs' if c.is_human else 'Animals'}</b> with {look}.<br><br>"
            f"<b>Moves and fights like a {c.base_class}.</b> {body.temperament if body else ''}<br><br>"
            f"<b>{att.label}:</b> {att.description}<br><br>"
            f"Fighting skill {self.sl_combat.value()} %, {c.health} HP, {stats}.")
        models = {m.path: m.skeleton for m in self.models}
        issues = generator.validate([c], self.bodies, models)
        self.lbl_issues.setText("<br>".join(f"{'Error' if s == generator.ERROR else 'Hint'}: {m}"
                                            for s, _n, m in issues) or "Ready to build.")
        self.btn_save.setEnabled(not any(s == generator.ERROR for s, _n, _m in issues))

    def _save(self) -> None:
        self.saved = self._collect()
        self.accept()
