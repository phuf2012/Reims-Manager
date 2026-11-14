#!/usr/bin/env python3
"""Native GTK front end for Reims Manager."""

from __future__ import annotations

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
        self.set_flags(Gio.ApplicationFlags.NON_UNIQUE)

    def do_activate(self):
        if getattr(self, "window", None):
            self.window.present()
            return
        self.window = Gtk.ApplicationWindow(application=self, title="Reims Manager")
        self.window.set_default_size(920, 650)
        self.window.set_border_width(12)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.window.add(root)

        top = Gtk.Box(spacing=8)
        root.pack_start(top, False, False, 0)
        self.vm_select = Gtk.ComboBoxText()
        self.vm_select.set_hexpand(True)
        self.vm_select.connect("changed", self.on_vm_changed)
        top.pack_start(self.vm_select, True, True, 0)
        self.refresh_button = Gtk.Button(label="Refresh")
        self.refresh_button.connect("clicked", lambda *_: self.refresh_vms())
        top.pack_start(self.refresh_button, False, False, 0)
        self.start_button = Gtk.Button(label="Start")
        self.start_button.connect("clicked", lambda *_: self.run_action("start"))
        top.pack_start(self.start_button, False, False, 0)
        self.stop_button = Gtk.Button(label="Stop")
        self.stop_button.connect("clicked", lambda *_: self.run_action("stop"))
        top.pack_start(self.stop_button, False, False, 0)

        self.status = Gtk.Label(xalign=0)
        root.pack_start(self.status, False, False, 0)
        tabs = Gtk.Notebook()
        root.pack_start(tabs, True, True, 0)

        overview_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        overview_page.set_margin_start(14)
        overview_page.set_margin_top(14)
        overview_page.set_margin_end(14)
        overview_page.set_margin_bottom(14)
        self.overview = Gtk.Label(xalign=0, yalign=0)
        self.overview.set_selectable(True)
        self.overview.set_line_wrap(True)
        overview_page.pack_start(self.overview, True, True, 0)
        guide = Gtk.LinkButton.new_with_label(
            "https://github.com/steelbrain/reims-vgpu",
            "Open Reims installation and setup guide",
        )
        guide.set_halign(Gtk.Align.START)
        overview_page.pack_start(guide, False, False, 0)
        tabs.append_page(overview_page, Gtk.Label(label="VM"))

        usb_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        usb_box.set_margin_top(10)
        usb_box.set_margin_start(10)
        usb_box.set_margin_end(10)
        usb_hint = Gtk.Label(
            label="Select a device, then choose Attach selected. Attached devices leave the Linux host until detached or the VM stops. Do not pass through the keyboard or mouse you use to control this computer.",
            xalign=0,
        )
        usb_hint.set_line_wrap(True)
        usb_box.pack_start(usb_hint, False, False, 0)
        self.usb_store = Gtk.ListStore(str, str, str, str, str, bool)
        usb_view = Gtk.TreeView(model=self.usb_store)
        for title, col in (("Device", 0), ("USB ID", 1), ("Bus / address", 2), ("State", 3)):
            renderer = Gtk.CellRendererText()
            usb_view.append_column(Gtk.TreeViewColumn(title, renderer, text=col))
        usb_view.get_selection().connect("changed", self.on_usb_selection)
        usb_scroll = Gtk.ScrolledWindow()
        usb_scroll.set_vexpand(True)
        usb_scroll.add(usb_view)
        usb_box.pack_start(usb_scroll, True, True, 0)
        toolbar = Gtk.Box(spacing=8)
        usb_box.pack_start(toolbar, False, False, 0)
        scan = Gtk.Button(label="Scan USB")
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
        usb_box.pack_start(self.diagnostics[0], True, True, 0)
        tabs.append_page(usb_box, Gtk.Label(label="USB devices"))

        log_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.logs = self.text_panel()
        log_box.pack_start(self.logs[0], True, True, 0)
        log_refresh = Gtk.Button(label="Refresh logs")
        log_refresh.connect("clicked", lambda *_: self.refresh_logs())
        log_box.pack_start(log_refresh, False, False, 0)
        tabs.append_page(log_box, Gtk.Label(label="Logs"))

        self.window.show_all()
        self.refresh_vms()

    @staticmethod
    def text_panel():
        view = Gtk.TextView()
        view.set_editable(False)
        view.set_cursor_visible(False)
        view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_height(150)
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
                self.overview.set_text(
                    "Welcome to Reims Manager\n\n"
                    "To get started, install Reims vGPU and create a VM. This app manages VMs that Reims has already created; it does not download macOS or create the VM for you.\n\n"
                    f"Setup check: {error}\n\n"
                    "After installing Reims, close and reopen this app, then choose Refresh."
                )
                return
            self.vm_rows = rows
            self.vm_select.remove_all()
            for row in rows:
                self.vm_select.append(row["name"], row["name"])
            if rows:
                names = [r["name"] for r in rows]
                self.vm_select.set_active_id(previous if previous in names else names[0])
            else:
                self.status.set_text("Reims is ready, but no VMs were found.")
                self.overview.set_text(
                    "No Reims VMs found\n\n"
                    "Create a VM with Reims first. Once it appears in `reims-ctl list`, choose Refresh here.\n\n"
                    "This manager is an early, focused app for starting and stopping Reims VMs and attaching USB devices."
                )
        self.background(backend.list_vms, done)

    def on_vm_changed(self, *_):
        name = self.selected_vm()
        row = next((r for r in self.vm_rows if r["name"] == name), None)
        if not row:
            return
        details = row.get("details", {})
        self.status.set_text(f"{name} — {row.get('state', 'unknown')}")
        self.overview.set_text("\n".join(f"{key}: {value}" for key, value in details.items()))
        self.start_button.set_sensitive(row.get("state") != "running")
        self.stop_button.set_sensitive(row.get("state") == "running")
        self.refresh_usb()

    def run_action(self, action):
        name = self.selected_vm()
        if not name:
            return
        self.background(lambda: backend.do_action(name, action), lambda result, error: self.action_done(result, error))

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
            for d in rows:
                if d["vendor"] == "1d6b" or "keyboard" in d["description"].lower() or "mouse" in d["description"].lower():
                    continue
                state = "Attached to VM" if d.get("attached_to_running_vm") else ("In use by host" if not d.get("available_on_host", True) else "Available")
                self.usb_store.append([d["description"], f"{d['vendor']}:{d['product']}", f"{d['bus']} / {d['address']}", state, d["id"], bool(d.get("attached"))])
        self.background(lambda: backend.list_usb_devices(name), done)

    def on_usb_selection(self, selection):
        model, itr = selection.get_selected()
        self.usb_action_button.set_sensitive(bool(itr))
        if itr:
            self.usb_action_button.set_label("Detach selected" if model[itr][5] else "Attach selected")

    def on_usb_action(self, *_):
        notebook = next((w for w in self.window.get_children()[0].get_children() if isinstance(w, Gtk.Notebook)), None)
        if not notebook:
            return
        view = notebook.get_nth_page(1).get_children()[0].get_child()
        model, itr = view.get_selection().get_selected()
        if not itr:
            return
        name = self.selected_vm()
        usb_id = model[itr][4]
        if not usb_id:
            self.status.set_text("Rescan USB devices and select the device again.")
            return
        action = "detach" if model[itr][5] else "attach"
        self.background(lambda: backend.usb_action(name, action, usb_id), lambda result, error: self.usb_done(result, error))

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
        self.set_text(self.diagnostics, error or f"Guest USB:\n{result['guest_usb']}\n\nQEMU devices:\n{result['passthrough_devices']}")
        return False

    def refresh_logs(self):
        name = self.selected_vm()
        if name:
            self.background(lambda: backend.run_reims("logs", name, "-n", "100"), lambda result, error: self.logs_done(result, error))

    def logs_done(self, result, error):
        self.set_text(self.logs, error or result)
        return False


if __name__ == "__main__":
    ReimsManager().run(sys.argv)
