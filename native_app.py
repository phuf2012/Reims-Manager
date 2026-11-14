#!/usr/bin/env python3
"""Native GTK front end for Reims Manager."""

from __future__ import annotations

import re
import sys
import threading

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk

import app as backend


class ReimsManager(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="local.reims.Manager")
        self.vm_rows = []
        self.gpu_rows = []
        self.set_flags(Gio.ApplicationFlags.NON_UNIQUE)

    def do_activate(self):
        if getattr(self, "window", None):
            self.window.present()
            return

        self.window = Gtk.ApplicationWindow(application=self, title="Reims Manager")
        self.window.set_default_size(860, 620)
        header = Gtk.HeaderBar()
        header.set_title("Reims Manager")
        header.set_show_close_button(True)
        self.window.set_titlebar(header)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        root.set_border_width(16)
        self.window.add(root)

        top = Gtk.Box(spacing=8)
        root.pack_start(top, False, False, 0)
        vm_label = Gtk.Label(label="Virtual machine")
        top.pack_start(vm_label, False, False, 0)
        self.vm_select = Gtk.ComboBoxText()
        self.vm_select.set_hexpand(True)
        self.vm_select.connect("changed", self.on_vm_changed)
        top.pack_start(self.vm_select, True, True, 0)

        self.refresh_button = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
        self.refresh_button.set_tooltip_text("Refresh virtual machines")
        self.refresh_button.connect("clicked", lambda *_: self.refresh_vms())
        top.pack_start(self.refresh_button, False, False, 0)
        self.start_button = Gtk.Button(label="Start")
        self.start_button.connect("clicked", lambda *_: self.run_action("start"))
        top.pack_start(self.start_button, False, False, 0)
        self.stop_button = Gtk.Button(label="Stop")
        self.stop_button.connect("clicked", lambda *_: self.run_action("stop"))
        top.pack_start(self.stop_button, False, False, 0)
        self.start_button.set_sensitive(False)
        self.stop_button.set_sensitive(False)

        self.status = Gtk.Label(xalign=0)
        root.pack_start(self.status, False, False, 0)

        tabs = Gtk.Notebook()
        root.pack_start(tabs, True, True, 0)
        tabs.append_page(self.build_overview_page(), Gtk.Label(label="Overview"))
        tabs.append_page(self.build_settings_page(), Gtk.Label(label="Settings"))
        tabs.append_page(self.build_usb_page(), Gtk.Label(label="USB devices"))
        tabs.append_page(self.build_logs_page(), Gtk.Label(label="Logs"))

        self.window.show_all()
        self.refresh_vms()

    def build_overview_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        page.set_border_width(18)
        heading = Gtk.Label()
        heading.set_markup("<big><b>Virtual machine</b></big>")
        heading.set_xalign(0)
        page.pack_start(heading, False, False, 0)
        self.overview = Gtk.Label(xalign=0, yalign=0)
        self.overview.set_selectable(True)
        self.overview.set_line_wrap(True)
        page.pack_start(self.overview, False, False, 0)
        guide = Gtk.LinkButton.new_with_label(
            "https://github.com/steelbrain/reims-vgpu",
            "Reims installation and setup guide",
        )
        guide.set_halign(Gtk.Align.START)
        page.pack_start(guide, False, False, 0)
        return page

    def build_settings_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        page.set_border_width(18)
        hint = Gtk.Label(
            label="These changes apply the next time the VM starts. Stop the VM before saving.",
            xalign=0,
        )
        hint.set_line_wrap(True)
        page.pack_start(hint, False, False, 0)

        grid = Gtk.Grid(column_spacing=18, row_spacing=12)
        page.pack_start(grid, False, False, 0)
        self.settings_controls = []

        self.cpu_spin = Gtk.SpinButton.new_with_range(1, 4, 1)
        self.add_setting_row(grid, 0, "CPU cores", self.cpu_spin)

        self.memory_combo = Gtk.ComboBoxText()
        for value in ("4", "8", "12", "16"):
            self.memory_combo.append(value, f"{value} GB")
        self.add_setting_row(grid, 1, "Memory", self.memory_combo)

        self.gpu_combo = Gtk.ComboBoxText()
        self.gpu_combo.append("auto", "Auto select")
        self.add_setting_row(grid, 2, "Graphics device", self.gpu_combo)

        self.resolution_combo = Gtk.ComboBoxText()
        for value, label in (
            ("host", "Host display"),
            ("1920x1080", "1920 × 1080"),
            ("1600x900", "1600 × 900"),
            ("1280x800", "1280 × 800"),
            ("1280x720", "1280 × 720"),
        ):
            self.resolution_combo.append(value, label)
        self.add_setting_row(grid, 3, "Resolution", self.resolution_combo)

        self.hidpi_switch = Gtk.Switch()
        self.add_setting_row(grid, 4, "HiDPI display", self.hidpi_switch)
        self.borderless_switch = Gtk.Switch()
        self.add_setting_row(grid, 5, "Borderless window", self.borderless_switch)
        self.audio_switch = Gtk.Switch()
        self.add_setting_row(grid, 6, "Audio", self.audio_switch)
        self.network_switch = Gtk.Switch()
        self.add_setting_row(grid, 7, "Network", self.network_switch)
        self.logs_switch = Gtk.Switch()
        self.add_setting_row(grid, 8, "Diagnostic logs", self.logs_switch)

        self.save_settings_button = Gtk.Button(label="Save settings")
        self.save_settings_button.set_halign(Gtk.Align.START)
        self.save_settings_button.connect("clicked", self.save_settings)
        page.pack_start(self.save_settings_button, False, False, 0)
        self.settings_controls.append(self.save_settings_button)
        self.set_settings_sensitive(False)
        return page

    def add_setting_row(self, grid, row, title, control):
        label = Gtk.Label(label=title, xalign=0)
        label.set_hexpand(True)
        grid.attach(label, 0, row, 1, 1)
        grid.attach(control, 1, row, 1, 1)
        self.settings_controls.append(control)

    def set_settings_sensitive(self, sensitive):
        for widget in self.settings_controls:
            widget.set_sensitive(sensitive)

    def build_usb_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        page.set_border_width(14)
        hint = Gtk.Label(
            label="Attach gives the selected device to the VM. Linux cannot use it until it is detached or the VM stops. Do not attach the keyboard or mouse you use to control this computer.",
            xalign=0,
        )
        hint.set_line_wrap(True)
        page.pack_start(hint, False, False, 0)

        self.usb_store = Gtk.ListStore(str, str, str, str, str, bool)
        self.usb_view = Gtk.TreeView(model=self.usb_store)
        for title, col in (("Device", 0), ("USB ID", 1), ("Bus / address", 2), ("State", 3)):
            renderer = Gtk.CellRendererText()
            self.usb_view.append_column(Gtk.TreeViewColumn(title, renderer, text=col))
        self.usb_view.get_selection().connect("changed", self.on_usb_selection)
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.add(self.usb_view)
        page.pack_start(scroll, True, True, 0)

        toolbar = Gtk.Box(spacing=8)
        page.pack_start(toolbar, False, False, 0)
        scan = Gtk.Button(label="Scan USB devices")
        scan.connect("clicked", lambda *_: self.refresh_usb())
        toolbar.pack_start(scan, False, False, 0)
        self.usb_action_button = Gtk.Button(label="Attach selected")
        self.usb_action_button.set_sensitive(False)
        self.usb_action_button.connect("clicked", self.on_usb_action)
        toolbar.pack_start(self.usb_action_button, False, False, 0)
        diag = Gtk.Button(label="Check guest USB bus")
        diag.connect("clicked", lambda *_: self.refresh_diagnostics())
        toolbar.pack_start(diag, False, False, 0)

        self.diagnostics = self.text_panel()
        page.pack_start(self.diagnostics[0], True, True, 0)
        return page

    def build_logs_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        page.set_border_width(14)
        self.logs = self.text_panel()
        page.pack_start(self.logs[0], True, True, 0)
        refresh = Gtk.Button(label="Refresh logs")
        refresh.set_halign(Gtk.Align.START)
        refresh.connect("clicked", lambda *_: self.refresh_logs())
        page.pack_start(refresh, False, False, 0)
        return page

    @staticmethod
    def text_panel():
        view = Gtk.TextView()
        view.set_editable(False)
        view.set_cursor_visible(False)
        view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_height(130)
        scroll.add(view)
        return scroll, view.get_buffer()

    def selected_vm(self):
        return self.vm_select.get_active_id()

    def set_text(self, panel, value):
        panel[1].set_text(str(value))

    def background(self, work, done):
        self.status.set_text("Working…")

        def task():
            try:
                result = work()
                GLib.idle_add(done, result, None)
            except Exception as exc:
                GLib.idle_add(done, None, str(exc))

        threading.Thread(target=task, daemon=True).start()

    def refresh_vms(self):
        previous = self.selected_vm()

        def done(rows, error):
            if error:
                self.status.set_text(error)
                self.vm_rows = []
                self.vm_select.remove_all()
                self.start_button.set_sensitive(False)
                self.stop_button.set_sensitive(False)
                self.set_settings_sensitive(False)
                self.overview.set_text(
                    "Welcome to Reims Manager\n\n"
                    "Install Reims vGPU and create a VM to get started. This app manages VMs created by Reims; it does not create a VM or download macOS.\n\n"
                    f"Setup check: {error}"
                )
                return

            self.vm_rows = rows
            self.vm_select.remove_all()
            for row in rows:
                self.vm_select.append(row["name"], row["name"])
            if rows:
                names = [row["name"] for row in rows]
                self.vm_select.set_active_id(previous if previous in names else names[0])
            else:
                self.status.set_text("No Reims VMs found. Create one with Reims, then refresh.")
                self.overview.set_text("No virtual machines found\n\nCreate a VM with Reims, then choose Refresh.")
                self.start_button.set_sensitive(False)
                self.stop_button.set_sensitive(False)
                self.set_settings_sensitive(False)

        self.background(backend.list_vms, done)

    def on_vm_changed(self, *_):
        name = self.selected_vm()
        row = next((item for item in self.vm_rows if item["name"] == name), None)
        if not row:
            return
        details = row.get("details", {})
        state = row.get("state", "unknown")
        self.status.set_text(f"{name}  ·  {state.title()}")
        fields = (
            ("Status", state.title()),
            ("CPU cores", details.get("cpus", "Unknown")),
            ("Memory", details.get("memory", "Unknown")),
            ("Graphics", details.get("gpu", "Unknown")),
            ("Display", details.get("displays", "Unknown")),
            ("Audio", details.get("audio", "Unknown")),
            ("Network", details.get("network", "Unknown")),
        )
        self.overview.set_text("\n".join(f"{label}:  {value}" for label, value in fields))
        running = state == "running"
        self.start_button.set_sensitive(not running)
        self.stop_button.set_sensitive(running)
        self.set_settings_sensitive(not running)
        self.refresh_usb()
        self.load_settings(name, details)

    def load_settings(self, name, details):
        self.cpu_spin.set_value(self.as_number(details.get("cpus"), 4))
        memory = re.search(r"\d+", details.get("memory", ""))
        memory_id = memory.group(0) if memory else "16"
        self.memory_combo.set_active_id(memory_id if memory_id in ("4", "8", "12", "16") else "16")
        display = details.get("displays", "")
        resolution = re.search(r"(?:host|\d+x\d+)", display)
        resolution_id = resolution.group(0) if resolution else "host"
        self.resolution_combo.set_active_id(resolution_id if resolution_id in ("host", "1920x1080", "1600x900", "1280x800", "1280x720") else "host")
        self.borderless_switch.set_active("borderless" in display.lower())
        self.hidpi_switch.set_active("hidpi" in display.lower())
        self.audio_switch.set_active(details.get("audio", "off").lower() == "on")
        self.network_switch.set_active(details.get("network", "off").lower() not in ("off", "disabled", "none"))
        self.logs_switch.set_active(details.get("logs", "off").lower() == "on")

        def get_gpus():
            return backend.gpu_list()

        def done(gpus, error):
            if error or self.selected_vm() != name:
                return False
            self.gpu_rows = gpus
            self.gpu_combo.remove_all()
            self.gpu_combo.append("auto", "Auto select")
            active_id = "auto"
            current = details.get("gpu", "").lower()
            for gpu in gpus:
                number = str(gpu["number"])
                label = gpu["label"]
                self.gpu_combo.append(number, label)
                if current and current in label.lower():
                    active_id = number
            self.gpu_combo.set_active_id(active_id)
            return False

        self.background(get_gpus, done)

    @staticmethod
    def as_number(value, fallback):
        match = re.search(r"\d+", str(value or ""))
        return int(match.group(0)) if match else fallback

    def save_settings(self, *_):
        name = self.selected_vm()
        if not name:
            return
        payload = {
            "cpus": self.cpu_spin.get_value_as_int(),
            "memory": self.memory_combo.get_active_id() or "16",
            "gpu": self.gpu_combo.get_active_id() or "auto",
            "resolution": self.resolution_combo.get_active_id() or "host",
            "hidpi": self.hidpi_switch.get_active(),
            "borderless": self.borderless_switch.get_active(),
            "audio": self.audio_switch.get_active(),
            "network": self.network_switch.get_active(),
            "logs": self.logs_switch.get_active(),
        }

        def done(result, error):
            self.status.set_text(error or result or "Settings saved. They apply the next time the VM starts.")
            self.refresh_vms()
            return False

        self.background(lambda: backend.apply_settings(name, payload), done)

    def run_action(self, action):
        name = self.selected_vm()
        if not name:
            return
        self.background(
            lambda: backend.do_action(name, action),
            lambda result, error: self.action_done(result, error),
        )

    def action_done(self, result, error):
        self.status.set_text(error or result or "Done")
        self.refresh_vms()
        return False

    def refresh_usb(self):
        name = self.selected_vm()
        if not name:
            return

        def done(rows, error):
            self.usb_store.clear()
            if error:
                self.usb_store.append([error, "", "", "", "", False])
                return
            for device in rows:
                description = device["description"].lower()
                if device["vendor"] == "1d6b" or "keyboard" in description or "mouse" in description:
                    continue
                state = (
                    "Attached to VM" if device.get("attached_to_running_vm")
                    else "In use by host" if not device.get("available_on_host", True)
                    else "Available"
                )
                self.usb_store.append([
                    device["description"],
                    f"{device['vendor']}:{device['product']}",
                    f"{device['bus']} / {device['address']}",
                    state,
                    device["id"],
                    bool(device.get("attached")),
                ])

        self.background(lambda: backend.list_usb_devices(name), done)

    def on_usb_selection(self, selection):
        model, itr = selection.get_selected()
        self.usb_action_button.set_sensitive(bool(itr))
        if itr:
            self.usb_action_button.set_label("Detach selected" if model[itr][5] else "Attach selected")

    def on_usb_action(self, *_):
        model, itr = self.usb_view.get_selection().get_selected()
        if not itr:
            return
        name = self.selected_vm()
        usb_id = model[itr][4]
        if not usb_id:
            self.status.set_text("Rescan USB devices and select a device again.")
            return
        action = "detach" if model[itr][5] else "attach"
        self.background(
            lambda: backend.usb_action(name, action, usb_id),
            lambda result, error: self.usb_done(result, error),
        )

    def usb_done(self, result, error):
        self.status.set_text(error or result or "Done")
        self.refresh_usb()
        self.refresh_diagnostics()
        return False

    def refresh_diagnostics(self):
        name = self.selected_vm()
        if name:
            self.background(lambda: backend.usb_diagnostics(name), self.diagnostics_done)

    def diagnostics_done(self, result, error):
        value = error or f"Guest USB:\n{result['guest_usb']}\n\nQEMU devices:\n{result['passthrough_devices']}"
        self.set_text(self.diagnostics, value)
        return False

    def refresh_logs(self):
        name = self.selected_vm()
        if name:
            self.background(
                lambda: backend.run_reims("logs", name, "-n", "100"),
                lambda result, error: self.logs_done(result, error),
            )

    def logs_done(self, result, error):
        self.set_text(self.logs, error or result)
        return False


if __name__ == "__main__":
    ReimsManager().run(sys.argv)
