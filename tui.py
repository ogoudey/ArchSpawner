"""
Terminal UI for the container spawner. Plain terminal app (Textual) -- works
fine over SSH, no browser needed. Polls the spawner's HTTP API and lets you
inspect and kill instances interactively.

Run:
    python tui.py                                  # talks to http://127.0.0.1:9000
    SPAWNER_API_URL=http://host:9000 python tui.py  # talks to a remote spawner
"""
import os
from typing import Dict, List

import httpx
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Footer, DataTable, Static, Button, Label
from textual.reactive import reactive
from textual.screen import ModalScreen

API_URL = os.environ.get("SPAWNER_API_URL", "http://127.0.0.1:9000")
REFRESH_INTERVAL = float(os.environ.get("SPAWNER_TUI_REFRESH", "2"))

COLUMNS = ["id", "type_key", "name", "port", "status", "container", "started_at_human"]
HEADERS = ["ID", "TYPE", "NAME", "PORT", "STATUS", "CONTAINER", "STARTED"]


class ConfirmKill(ModalScreen[bool]):
    """Simple yes/no confirmation dialog before killing a container."""

    def __init__(self, label: str):
        super().__init__()
        self._label = label

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Label(f"Kill instance {self._label}?")
            with Horizontal():
                yield Button("Yes, kill", id="yes", variant="error")
                yield Button("Cancel", id="no", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")


class SpawnerTUI(App):
    CSS = """
    #confirm-box {
        align: center middle;
        width: 50;
        height: 7;
        border: heavy $error;
        background: $surface;
        padding: 1 2;
    }
    #status-bar {
        height: 1;
        background: $boost;
        color: $text-muted;
        padding: 0 1;
    }
    """
    BINDINGS = [
        ("k", "kill_selected", "Kill selected"),
        ("r", "refresh_now", "Refresh"),
        ("q", "quit", "Quit"),
    ]

    instances: reactive[List[Dict]] = reactive(list)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(f"API: {API_URL}   |   [k] kill  [r] refresh  [q] quit", id="status-bar")
        yield DataTable(zebra_stripes=True, cursor_type="row")
        yield Footer()

    async def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns(*HEADERS)
        self._client = httpx.AsyncClient(timeout=5)
        await self.refresh_instances()
        self.set_interval(REFRESH_INTERVAL, self.refresh_instances)

    async def refresh_instances(self) -> None:
        status_bar = self.query_one("#status-bar", Static)
        try:
            resp = await self._client.get(f"{API_URL}/instances")
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            status_bar.update(f"API: {API_URL}  |  ERROR reaching spawner: {e}")
            return

        self.instances = data
        table = self.query_one(DataTable)
        table.clear()
        for inst in data:
            row = [str(inst.get(c, "")) for c in COLUMNS]
            row[COLUMNS.index("container")] = inst.get("container_id", "")[:12]
            table.add_row(*row, key=inst["id"])
        status_bar.update(
            f"API: {API_URL}   |   {len(data)} instance(s)   |   [k] kill  [r] refresh  [q] quit"
        )

    async def action_refresh_now(self) -> None:
        await self.refresh_instances()

    async def action_kill_selected(self) -> None:
        table = self.query_one(DataTable)
        if table.cursor_row is None or table.row_count == 0:
            return
        row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        instance_id = row_key.value
        inst = next((i for i in self.instances if i["id"] == instance_id), None)
        label = f'{inst["name"]} ({inst["type_key"]}, port {inst["port"]})' if inst else instance_id

        confirmed = await self.push_screen_wait(ConfirmKill(label))
        if not confirmed:
            return

        status_bar = self.query_one("#status-bar", Static)
        try:
            resp = await self._client.delete(f"{API_URL}/instances/{instance_id}")
            resp.raise_for_status()
        except Exception as e:
            status_bar.update(f"Kill failed: {e}")
            return
        await self.refresh_instances()


if __name__ == "__main__":
    SpawnerTUI().run()
