#!/usr/bin/env python3
"""Native GTK front end for Reims Manager."""

from __future__ import annotations

import re
import sys
import threading
import time

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk

import app as backend


class ReimsManager(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="local.reims.Manager")
        self.vm_rows = []
        self.gpu_rows = []
        self.action_in_progress = False
        self.usb_action_in_progress = False
        self.usb_scan_in_progress = False
        self.status_after_refresh = None
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
        self.status.set_line_wrap(True)
        self.status.set_selectable(True)
        root.pack_start(self.status, False, False, 0)

        tabs = Gtk.Notebook()
        root.pack_start(tabs, True, True, 0)
        tabs.append_page(self.build_overview_page(), Gtk.Label(label="Overview"))
        tabs.append_page(self.build_settings_page(), Gtk.Label(label="Settings"))
        tabs.append_page(self.build_shared_folder_page(), Gtk.Label(label="Shared folder"))
        tabs.append_page(self.build_updates_page(), Gtk.Label(label="Updates"))
        tabs.append_page(self.build_usb_page(), Gtk.Label(label="USB devices"))
        tabs.append_page(self.build_logs_page(), Gtk.Label(label="Logs"))

        self.window.show_all()
        self.refresh_vms()
        self.load_update_preferences()

    def build_updates_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        page.set_border_width(18)
        heading = Gtk.Label()
        heading.set_markup("<big><b>Reims Manager updates</b></big>")
        heading.set_xalign(0)
        page.pack_start(heading, False, False, 0)

        explanation = Gtk.Label(
            label="Check GitHub for a newer Reims Manager release. Enabling automatic checks checks now and on app launch, at most once per day. Updates are never downloaded or installed without your action.",
            xalign=0,
        )
        explanation.set_line_wrap(True)
        page.pack_start(explanation, False, False, 0)

        preference_row = Gtk.Box(spacing=12)
        preference_label = Gtk.Label(label="Automatically check for updates", xalign=0)
        preference_label.set_hexpand(True)
        preference_row.pack_start(preference_label, True, True, 0)
        self.auto_update_switch = Gtk.Switch()
        self.auto_update_switch.connect("notify::active", self.on_auto_update_changed)
        preference_row.pack_start(self.auto_update_switch, False, False, 0)
        page.pack_start(preference_row, False, False, 0)

        self.check_updates_button = Gtk.Button(label="Check for Updates")
        self.check_updates_button.set_halign(Gtk.Align.START)
        self.check_updates_button.connect("clicked", lambda *_: self.check_for_updates())
        page.pack_start(self.check_updates_button, False, False, 0)

        self.update_status = Gtk.Label(label=f"Installed version: {backend.APP_VERSION}", xalign=0)
        self.update_status.set_line_wrap(True)
        self.update_status.set_selectable(True)
        page.pack_start(self.update_status, False, False, 0)

        self.update_link = Gtk.LinkButton.new_with_label(
            "https://github.com/phuf2012/Reims-Manager/releases",
            "Open GitHub releases",
        )
        self.update_link.set_halign(Gtk.Align.START)
        self.update_link.set_no_show_all(True)
        self.update_link.set_visible(False)
        page.pack_start(self.update_link, False, False, 0)
        return page

    def load_update_preferences(self):
        def done(settings, error):
            if error:
                self.update_status.set_text(error)
                return False
            self.loading_update_preferences = True
            self.auto_update_switch.set_active(settings["auto_check"])
            self.loading_update_preferences = False
            if settings["last_checked"]:
                self.update_status.set_text(
                    f"Installed version: {backend.APP_VERSION}. Last checked: "
                    f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(settings['last_checked']))}."
                )
            if settings["auto_check"] and settings["check_due"]:
                self.check_for_updates()
            return False

        self.background(backend.update_settings_status, done, set_status=False)

    def on_auto_update_changed(self, switch, *_):
        if getattr(self, "loading_update_preferences", False):
            return
        enabled = switch.get_active()
        self.update_status.set_text("Saving update preference…")

        def done(settings, error):
            if error:
                self.update_status.set_text(error)
            else:
                self.update_status.set_text(
                    "Automatic update checks are on." if settings["auto_check"]
                    else "Automatic update checks are off."
                )
                if settings["auto_check"]:
                    self.check_for_updates()
            return False

        self.background(lambda: backend.save_update_settings(enabled), done, set_status=False)

    def check_for_updates(self):
        self.check_updates_button.set_sensitive(False)
        self.update_status.set_text("Checking GitHub releases…")
        self.update_link.set_visible(False)

        def done(result, error):
            self.check_updates_button.set_sensitive(True)
            if error:
                self.update_status.set_text(error)
                return False
            if result["update_available"]:
                self.update_status.set_text(
                    f"Update available: {result['release_name']} (version {result['latest_version']})."
                )
                self.update_link.set_uri(result["download_url"] or result["release_url"])
                self.update_link.set_label(
                    "Download .deb" if result["download_url"] else "Open release page"
                )
                self.update_link.set_visible(True)
            else:
                self.update_status.set_text(
                    f"You're up to date. Installed version: {result['current_version']}; "
                    f"latest release: {result['latest_version']}."
                )
            return False

        self.background(backend.check_for_updates, done, set_status=False)

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
        self.video_acceleration_switch = Gtk.Switch()
        self.add_setting_row(grid, 3, "Video acceleration", self.video_acceleration_switch)

        self.resolution_combo = Gtk.ComboBoxText()
        for value, label in (
            ("host", "Host display"),
            ("1920x1080", "1920 × 1080"),
            ("1600x900", "1600 × 900"),
            ("1280x800", "1280 × 800"),
            ("1280x720", "1280 × 720"),
        ):
            self.resolution_combo.append(value, label)
        self.add_setting_row(grid, 4, "Resolution", self.resolution_combo)

        self.refresh_combo = Gtk.ComboBoxText()
        self.refresh_combo.append("host", "Host refresh rate")
        self.refresh_combo.append("60", "60 Hz")
        self.refresh_combo.append("120", "120 Hz")
        self.add_setting_row(grid, 5, "Refresh rate", self.refresh_combo)

        self.hidpi_switch = Gtk.Switch()
        self.add_setting_row(grid, 6, "HiDPI display", self.hidpi_switch)
        self.borderless_switch = Gtk.Switch()
        self.add_setting_row(grid, 7, "Borderless window", self.borderless_switch)
        self.audio_switch = Gtk.Switch()
        self.add_setting_row(grid, 8, "Audio", self.audio_switch)
        self.network_switch = Gtk.Switch()
        self.add_setting_row(grid, 9, "Network", self.network_switch)
        self.logs_switch = Gtk.Switch()
        self.add_setting_row(grid, 10, "Diagnostic logs", self.logs_switch)

        self.save_settings_button = Gtk.Button(label="Save settings")
        self.save_settings_button.set_halign(Gtk.Align.START)
        self.save_settings_button.connect("clicked", self.save_settings)
        page.pack_start(self.save_settings_button, False, False, 0)
        self.settings_controls.append(self.save_settings_button)
        self.set_settings_sensitive(False)
        return page

    def build_shared_folder_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        page.set_border_width(18)
        heading = Gtk.Label()
        heading.set_markup("<big><b>Share a Linux folder with macOS</b></big>")
        heading.set_xalign(0)
        page.pack_start(heading, False, False, 0)

        explanation = Gtk.Label(
            label="The selected folder is writable from the guest while this VM runs. QEMU exposes it only on a private virtual network; it is not shared to your local network. Stop the VM before changing the folder.",
            xalign=0,
        )
        explanation.set_line_wrap(True)
        page.pack_start(explanation, False, False, 0)

        self.share_path_label = Gtk.Label(label="No folder selected", xalign=0)
        self.share_path_label.set_selectable(True)
        page.pack_start(self.share_path_label, False, False, 0)

        self.share_status_label = Gtk.Label(xalign=0)
        self.share_status_label.set_line_wrap(True)
        page.pack_start(self.share_status_label, False, False, 0)

        actions = Gtk.Box(spacing=8)
        self.share_choose_button = Gtk.Button(label="Choose folder…")
        self.share_choose_button.connect("clicked", self.choose_shared_folder)
        actions.pack_start(self.share_choose_button, False, False, 0)
        self.share_remove_button = Gtk.Button(label="Remove share")
        self.share_remove_button.connect("clicked", lambda *_: self.set_shared_folder(""))
        actions.pack_start(self.share_remove_button, False, False, 0)
        page.pack_start(actions, False, False, 0)
        self.share_controls = [self.share_choose_button, self.share_remove_button]
        for control in self.share_controls:
            control.set_sensitive(False)

        self.share_connect_label = Gtk.Label(
            label=f"In macOS, open Finder → Go → Connect to Server and enter {backend.SHARE_URL}.",
            xalign=0,
        )
        self.share_connect_label.set_line_wrap(True)
        page.pack_start(self.share_connect_label, False, False, 0)
        return page

    def choose_shared_folder(self, *_):
        dialog = Gtk.FileChooserDialog(
            title="Choose a folder to share with macOS",
            parent=self.window,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
            buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, "Share folder", Gtk.ResponseType.OK),
        )
        try:
            if dialog.run() == Gtk.ResponseType.OK:
                self.set_shared_folder(dialog.get_filename())
        finally:
            dialog.destroy()

    def set_shared_folder(self, path):
        name = self.selected_vm()
        if not name:
            return

        for control in self.share_controls:
            control.set_sensitive(False)
        self.share_status_label.set_text("Saving shared-folder settings…")

        def done(result, error):
            self.share_status_label.set_text(error or result or "Shared-folder settings saved.")
            self.status_after_refresh = error or result or "Shared folder settings saved."
            self.refresh_vms()
            return False

        self.background(
            lambda: backend.configure_shared_folder(name, path),
            done,
            status="Saving shared folder…",
        )

    def show_shared_folder(self, details):
        try:
            path = backend.shared_folder_path(details)
        except backend.ManagerError as exc:
            self.share_path_label.set_text("Could not read the saved share setting.")
            self.share_status_label.set_text(str(exc))
            return
        self.share_path_label.set_text(path or "No folder selected")
        if path and not backend.smbd_path():
            self.share_status_label.set_text(
                "Samba is needed for QEMU folder sharing. Install it with `sudo apt install samba`; Reims Manager will not install it."
            )
        elif path:
            self.share_status_label.set_text("Ready. The guest gets read and write access while the VM is running.")
        else:
            self.share_status_label.set_text(
                "Requires Samba's smbd on the Linux host. Choose a folder to make it available in Finder."
            )

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
            label="Select a device, then choose Connect to VM. Choose Return to Linux when you are done. Mounted USB drives are safely unmounted from Linux while connecting. Linux cannot use a device while it is connected to the VM. Do not pass through the keyboard or mouse you use to control this computer.",
            xalign=0,
        )
        hint.set_line_wrap(True)
        page.pack_start(hint, False, False, 0)

        self.usb_store = Gtk.ListStore(str, str, str, str, str, bool)
        self.usb_view = Gtk.TreeView(model=self.usb_store)
        for title, col in (("Device", 0), ("Status", 3)):
            renderer = Gtk.CellRendererText()
            self.usb_view.append_column(Gtk.TreeViewColumn(title, renderer, text=col))
        self.usb_view.get_selection().connect("changed", self.on_usb_selection)
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.add(self.usb_view)
        page.pack_start(scroll, True, True, 0)

        toolbar = Gtk.Box(spacing=8)
        page.pack_start(toolbar, False, False, 0)
        scan = Gtk.Button(label="Scan now")
        scan.connect("clicked", lambda *_: self.refresh_usb())
        toolbar.pack_start(scan, False, False, 0)
        self.usb_scan_button = scan
        self.usb_action_button = Gtk.Button(label="Connect to VM")
        self.usb_action_button.set_sensitive(False)
        self.usb_action_button.connect("clicked", self.on_usb_action)
        toolbar.pack_start(self.usb_action_button, False, False, 0)
        troubleshooting = Gtk.Expander(label="USB troubleshooting")
        advanced = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        diag = Gtk.Button(label="Check guest USB bus")
        diag.set_halign(Gtk.Align.START)
        diag.connect("clicked", lambda *_: self.refresh_diagnostics())
        advanced.pack_start(diag, False, False, 0)
        hint = Gtk.Label(
            label="If connected here but missing in macOS, check System Settings → General → About → System Report → USB. For drives, check Disk Utility → View → Show All Devices. Do not erase a disk unless you intend to wipe it.",
            xalign=0,
        )
        hint.set_line_wrap(True)
        advanced.pack_start(hint, False, False, 0)
        self.diagnostics = self.text_panel()
        advanced.pack_start(self.diagnostics[0], True, True, 0)
        troubleshooting.add(advanced)
        page.pack_start(troubleshooting, True, True, 0)
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

    def background(self, work, done, status="Working…", set_status=True):
        if set_status:
            self.status.set_text(status)

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
                for control in getattr(self, "share_controls", []):
                    control.set_sensitive(False)
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
                if self.status_after_refresh:
                    self.status.set_text(self.status_after_refresh)
                    self.status_after_refresh = None
            else:
                self.status.set_text("No Reims VMs found. Create one with Reims, then refresh.")
                self.overview.set_text("No virtual machines found\n\nCreate a VM with Reims, then choose Refresh.")
                self.start_button.set_sensitive(False)
                self.stop_button.set_sensitive(False)
                self.set_settings_sensitive(False)
                for control in self.share_controls:
                    control.set_sensitive(False)

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
        self.start_button.set_sensitive(not running and not self.action_in_progress)
        self.stop_button.set_sensitive(running and not self.action_in_progress)
        self.set_settings_sensitive(not running and not self.action_in_progress)
        for control in self.share_controls:
            control.set_sensitive(not running and not self.action_in_progress)
        self.show_shared_folder(details)
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
        refresh = re.search(r"(\d+)\s*Hz", display, re.IGNORECASE)
        refresh_id = refresh.group(1) if refresh else "host"
        self.refresh_combo.set_active_id(refresh_id if refresh_id in ("60", "120") else "host")
        self.borderless_switch.set_active("borderless" in display.lower())
        self.hidpi_switch.set_active("hidpi" in display.lower())
        self.video_acceleration_switch.set_active(
            details.get("video", "on").lower().startswith("on")
        )
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
        self.set_settings_sensitive(False)
        self.status.set_text("Saving VM settings…")
        payload = {
            "cpus": self.cpu_spin.get_value_as_int(),
            "memory": self.memory_combo.get_active_id() or "16",
            "gpu": self.gpu_combo.get_active_id() or "auto",
            "resolution": self.resolution_combo.get_active_id() or "host",
            "refresh": self.refresh_combo.get_active_id() or "host",
            "video_acceleration": self.video_acceleration_switch.get_active(),
            "hidpi": self.hidpi_switch.get_active(),
            "borderless": self.borderless_switch.get_active(),
            "audio": self.audio_switch.get_active(),
            "network": self.network_switch.get_active(),
            "logs": self.logs_switch.get_active(),
        }

        def done(result, error):
            self.status_after_refresh = error or result or "Settings saved. They apply the next time the VM starts."
            self.refresh_vms()
            return False

        self.background(lambda: backend.apply_settings(name, payload), done)

    def run_action(self, action):
        name = self.selected_vm()
        if not name or self.action_in_progress:
            return
        self.action_in_progress = True
        self.vm_select.set_sensitive(False)
        self.refresh_button.set_sensitive(False)
        self.start_button.set_sensitive(False)
        self.stop_button.set_sensitive(False)
        self.set_settings_sensitive(False)
        verb = "Starting" if action == "start" else "Stopping"
        self.background(
            lambda: backend.do_action(name, action),
            lambda result, error: self.action_done(result, error),
            status=f"{verb} {name}…",
        )

    def action_done(self, result, error):
        self.action_in_progress = False
        self.vm_select.set_sensitive(True)
        self.refresh_button.set_sensitive(True)
        self.status_after_refresh = error or result or "Done"
        self.refresh_vms()
        return False

    def refresh_usb(self):
        name = self.selected_vm()
        if not name or self.usb_scan_in_progress:
            return
        self.usb_scan_in_progress = True
        self.usb_scan_button.set_sensitive(False)

        def done(rows, error):
            self.usb_scan_in_progress = False
            self.usb_scan_button.set_sensitive(True)
            self.usb_store.clear()
            if error:
                self.usb_store.append([error, "", "", "", "", False])
                return
            for device in rows:
                description = device["description"].lower()
                if device["vendor"] == "1d6b" or "keyboard" in description or "mouse" in description:
                    continue
                state = (
                    "Connected to VM" if device.get("attached_to_running_vm") and device.get("available_on_host", True)
                    else "In use by VM" if device.get("attached_to_running_vm")
                    else "Returned to Linux" if device.get("attached")
                    else "In use by another app" if not device.get("available_on_host", True)
                    else "Available in Linux"
                )
                self.usb_store.append([
                    device["description"],
                    "",
                    "",
                    state,
                    device["id"],
                    bool(device.get("attached")),
                ])

        self.background(lambda: backend.list_usb_devices(name), done)

    def on_usb_selection(self, selection):
        model, itr = selection.get_selected()
        if self.usb_action_in_progress:
            self.usb_action_button.set_sensitive(False)
            return
        running = any(row["name"] == self.selected_vm() and row["state"] == "running" for row in self.vm_rows)
        available = bool(itr) and (model[itr][5] or running)
        self.usb_action_button.set_sensitive(available and not self.usb_action_in_progress)
        if itr:
            self.usb_action_button.set_label("Return to Linux" if model[itr][5] else "Connect to VM")

    def on_usb_action(self, *_):
        if self.usb_action_in_progress:
            return
        model, itr = self.usb_view.get_selection().get_selected()
        if not itr:
            return
        name = self.selected_vm()
        usb_id = model[itr][4]
        if not usb_id:
            self.status.set_text("Rescan USB devices and select a device again.")
            return
        action = "detach" if model[itr][5] else "attach"
        self.usb_action_in_progress = True
        self.usb_action_button.set_sensitive(False)
        self.usb_scan_button.set_sensitive(False)
        self.usb_action_button.set_label("Returning…" if action == "detach" else "Connecting…")
        self.background(
            lambda: backend.usb_action(name, action, usb_id),
            lambda result, error: self.usb_done(result, error),
        )

    def usb_done(self, result, error):
        self.usb_action_in_progress = False
        self.status.set_text(error or result or "Done")
        self.refresh_usb()
        self.refresh_diagnostics()
        return False

    def refresh_diagnostics(self):
        name = self.selected_vm()
        if name:
            self.background(lambda: backend.usb_diagnostics(name), self.diagnostics_done)

    def diagnostics_done(self, result, error):
        value = error or f"Passthrough controller: {result.get('hotplug_bus') or 'not found'}\n\nGuest USB:\n{result['guest_usb']}\n\nQEMU devices:\n{result['passthrough_devices']}"
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
