# Reims Manager

Reims Manager is a native GTK desktop app for managing virtual machines created by [Reims vGPU](https://github.com/steelbrain/reims-vgpu). It currently targets Linux desktop systems such as Linux Mint and Ubuntu. This project is in pre-release; use the `1.0-1` package for the updated interface.

## What it can do

- List Reims VMs and show their state and virtual hardware.
- Start and stop a VM.
- In the **Settings** tab, change CPU cores, RAM, host GPU, resolution, HiDPI, borderless mode, audio, network, and diagnostic logging for a stopped VM. Changes take effect the next time the VM starts.
- List host USB devices and attach or detach a selected device while a VM is running.
- Show guest USB diagnostics and recent Reims/QEMU logs.

The native window has four sections: **Overview**, **Settings**, **USB devices**, and **Logs**. The VM selector and Start/Stop buttons stay at the top of the window.

This is a focused early release, not a Virt Manager replacement. Reims does not use libvirt, and this app does not provide libvirt networks, snapshots, storage pools, XML editing, or SPICE redirection. Reims vGPU must be installed separately. Windows support is not available yet; the Reims host support and this app's USB integration currently target Linux.

## First use

1. Install Reims vGPU by following its current [upstream instructions](https://github.com/steelbrain/reims-vgpu).
2. Install Reims Manager from the `.deb` in the **Reims-Manager 1.0-1 Pre-Release**, or run it from this checkout with `python3 native_app.py`.
3. Open **Reims Manager** from your applications menu.
4. Create a VM with Reims if you have not already. The manager operates VMs created by Reims; it does not download macOS or create a VM itself.
5. Select a VM. Open **Settings** to adjust its configuration while it is stopped, or press **Start**. To pass a USB device, open **USB devices**, scan, select the device, and attach it.

If the app reports a missing dependency, install the relevant package and reopen it. The Debian package declares GTK 3, Python GTK bindings, `usbutils`, `acl`, and PolicyKit dependencies. It does not install Reims or modify host USB rules.

## USB notes

Attaching a physical USB device gives it to the VM; Linux may lose access until you detach it or stop the VM. Safely eject storage in Linux first and close host apps that use the phone. Do not attach the keyboard or mouse needed to control the host. Temporary permission to a selected USB device may trigger a system authorization prompt; the app does not create a persistent USB permission rule.

For iPhone passthrough, the app may temporarily stop Mint's `usbmuxd.service` if it is active, then restore it after the Apple USB device is detached or the VM stops. No persistent host service setting is changed. USB behavior inside the guest depends on the guest OS and its drivers.

## Development

Requirements on Debian or Ubuntu based systems:

```sh
sudo apt install python3 python3-gi gir1.2-gtk-3.0 usbutils acl policykit-1
```

Run the desktop app from the project directory:

```sh
python3 native_app.py
```

To build a local Debian package on Debian or Ubuntu based systems, install `debhelper` and run:

```sh
sudo apt install debhelper
dpkg-buildpackage -us -uc -b
```

The `.deb` is written to the parent directory. The Debian metadata uses the GitHub repository URL `https://github.com/phuf2012/Reims-Manager`.

The project is maintained by one person. Please use issues to report problems or suggest features; outside pull requests are not expected. The MIT license permits reuse and independent forks with attribution and preservation of the license notice.

## License

MIT. See [LICENSE](LICENSE).
