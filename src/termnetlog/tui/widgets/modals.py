from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Markdown, Select, TextArea

from termnetlog.config import NetDefaults
from termnetlog.models import Operator


class NoteModal(ModalScreen[str | None]):
    """Multi-line note editor. Returns the text, or None if cancelled."""

    BINDINGS = [
        Binding("ctrl+s", "save", "Save", priority=True),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, title: str, text: str = ""):
        super().__init__()
        self.title_text = title
        self.initial = text

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.title_text, classes="dialog-title")
            yield TextArea(self.initial, id="note-text")
            with Horizontal(classes="buttons"):
                yield Button("Save (ctrl+s)", variant="primary", id="save")
                yield Button("Cancel (esc)", id="cancel")

    def on_mount(self) -> None:
        ta = self.query_one(TextArea)
        ta.focus()
        ta.move_cursor(ta.document.end)

    def action_save(self) -> None:
        self.dismiss(self.query_one(TextArea).text.strip())

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.action_save() if event.button.id == "save" else self.action_cancel()


class InputModal(ModalScreen[str | None]):
    """Single-line prompt."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, title: str, value: str = "", placeholder: str = ""):
        super().__init__()
        self.title_text = title
        self.initial = value
        self.placeholder = placeholder

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog small"):
            yield Label(self.title_text, classes="dialog-title")
            yield Input(self.initial, placeholder=self.placeholder)

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmModal(ModalScreen[bool]):
    BINDINGS = [
        Binding("y", "answer(True)", "Yes"),
        Binding("n,escape", "answer(False)", "No"),
    ]

    def __init__(self, question: str):
        super().__init__()
        self.question = question

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog small"):
            yield Label(self.question, classes="dialog-title")
            with Horizontal(classes="buttons"):
                yield Button("Yes (y)", variant="error", id="yes")
                yield Button("No (n)", id="no")

    def on_mount(self) -> None:
        self.query_one("#no", Button).focus()

    def action_answer(self, value: bool) -> None:
        self.dismiss(value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")


class NewNetModal(ModalScreen[dict | None]):
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "start", "Start", priority=True),
    ]

    def __init__(self, defaults: NetDefaults):
        super().__init__()
        self.defaults = defaults

    def compose(self) -> ComposeResult:
        d = self.defaults
        with Vertical(classes="dialog"):
            yield Label("Start a new net", classes="dialog-title")
            with Grid(classes="form"):
                yield Label("Net name")
                yield Input(d.name, id="name")
                yield Label("Frequency")
                yield Input(d.frequency, id="frequency")
                yield Label("Band")
                yield Input(d.band, id="band")
                yield Label("Mode")
                yield Input(d.mode, id="mode")
                yield Label("My role")
                yield Select(
                    [("Net control", "ncs"), ("Participant", "participant")],
                    value=d.role if d.role in ("ncs", "participant") else "ncs",
                    allow_blank=False,
                    id="role",
                )
                yield Label("NCS callsign")
                yield Input(d.ncs_callsign, id="ncs", placeholder="who is running the net")
            with Horizontal(classes="buttons"):
                yield Button("Start net (ctrl+s)", variant="primary", id="start")
                yield Button("Cancel (esc)", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#ncs" if not self.defaults.ncs_callsign else "#name", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.action_start()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.action_start() if event.button.id == "start" else self.action_cancel()

    def action_start(self) -> None:
        values = {k: self.query_one(f"#{k}", Input).value.strip() for k in ("name", "frequency", "band", "mode")}
        if not values["name"]:
            self.notify("Net name is required", severity="error")
            return
        values["ncs_callsign"] = self.query_one("#ncs", Input).value.strip().upper()
        values["my_role"] = str(self.query_one("#role", Select).value)
        self.dismiss(values)

    def action_cancel(self) -> None:
        self.dismiss(None)


class OperatorEditModal(ModalScreen[dict | None]):
    """Edit operator data by hand. Returns changed fields."""

    FIELDS = [
        ("name", "Full name"),
        ("first_name", "First name"),
        ("nickname", "Nickname"),
        ("city", "City"),
        ("state", "State"),
        ("county", "County"),
        ("country", "Country"),
        ("grid", "Grid"),
        ("license_class", "Class"),
    ]
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "save", "Save", priority=True),
    ]

    def __init__(self, operator: Operator):
        super().__init__()
        self.operator = operator

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(f"Edit {self.operator.callsign}", classes="dialog-title")
            with Grid(classes="form"):
                for key, label in self.FIELDS:
                    yield Label(label)
                    yield Input(getattr(self.operator, key) or "", id=key)
            yield Label("Saving marks this operator as manually edited; lookups won't overwrite it.", classes="hint")
            with Horizontal(classes="buttons"):
                yield Button("Save (ctrl+s)", variant="primary", id="save")
                yield Button("Cancel (esc)", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#name", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.action_save()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.action_save() if event.button.id == "save" else self.action_cancel()

    def action_save(self) -> None:
        changed = {}
        for key, _ in self.FIELDS:
            value = self.query_one(f"#{key}", Input).value.strip()
            if value != (getattr(self.operator, key) or ""):
                changed[key] = value
        self.dismiss(changed)

    def action_cancel(self) -> None:
        self.dismiss(None)


HELP = """\
# termnetlog keys

## Logging (call entry focused)
| Key | Action |
|---|---|
| type + **enter** | log a check-in |
| **→** | accept callsign suggestion |
| **↑ / ↓** | move selection in the check-in list |
| **tab** / **esc** | jump to the check-in list |

Entry syntax: `CALL [flags] [via RELAY] [note…]`
e.g. `k9xyz/m t r` or `n0call via w1aw weak signal`.
Flag letters: **t** traffic · **s** short time · **r** ragchew · **c** recognized · **m** mobile · **p** portable

## Check-in list focused
| Key | Action |
|---|---|
| **t s r c m p** | toggle flag on selected check-in |
| **enter** | edit check-in note |
| **o** | edit persistent operator notes |
| **e** | edit operator details |
| **l** | re-run QRZ/HamDB lookup |
| **v** | set relayed-via |
| **delete** | remove check-in |
| **shift+↑ / shift+↓** | reorder |
| any other letter/digit | start typing a new call |

## Anywhere on the net screen
| Key | Action |
|---|---|
| **ctrl+e** | export net (text + ADIF) and copy roster |
| **ctrl+g** | edit net notes |
| **ctrl+x** | end net |
| **ctrl+b** | back to menu |
| **f1** | this help |
"""


class HelpModal(ModalScreen[None]):
    BINDINGS = [Binding("escape,f1,q", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog help"):
            yield Markdown(HELP)
            yield Button("Close (esc)", id="close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss()
