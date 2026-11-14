# Reims Manager

Reims Manager is a native GTK desktop app for managing virtual machines created by [Reims vGPU](https://github.com/steelbrain/reims-vgpu). It currently targets Linux desktop systems such as Linux Mint and Ubuntu.

## Stable 1.0.0

The stable 1.0.0 app can:

- List Reims VMs and show their state and virtual hardware.
- Start and stop a VM. Starting uses the host display resolution and borderless mode.
- List host USB devices and attach or detach a selected device while a VM is running.
- Show guest USB diagnostics and recent Reims/QEMU logs.

The stable app has **Overview**, **USB devices**, and **Logs** sections. It does not include a VM settings editor.

## 1.0.1-1 pre-release

The [Reims-Manager 1.0.1-1 Pre-Release](https://github.com/phuf2012/Reims-Manager/releases/tag/1.0.1-1) has a redesigned interface and adds a **Settings** section. It lets you edit supported CPU, RAM, GPU, resolution, HiDPI, borderless, audio, network, and logging settings for a stopped VM. Changes apply on the VM's next start. These settings are not available in stable 1.0.0.

## Scope

This is a focused app, not a Virt Manager replacement. Reims does not use libvirt, and Reims Manager does not provide libvirt networks, snapshots, storage pools, XML editing, or SPICE redirection. Reims vGPU must be installed separately. Windows support is not available yet; this app and the current Reims host integration target Linux.

## First use

1. Install Reims vGPU by following its [upstream instructions](https://github.com/steelbrain/reims-vgpu).
2. Install Reims Manager from the `.deb` attached to a GitHub release, or run it from a source checkout with `python3 native_app.py`.
3. Create a VM with Reims if you have not already. Reims Manager operates VMs created by Reims; it does not create VMs or download macOS.
4. Open Reims Manager, select a VM, and choose **Start**. For USB passthrough, select the **USB devices** section, scan, choose a device, and attach it.

The Debian package declares GTK 3, Python GTK bindings, `usbutils`, `acl`, and PolicyKit dependencies. It does not install Reims or create persistent host USB rules.

## USB notes

Attaching a physical USB device gives it to the VM; Linux may lose access until you detach it or stop the VM. Safely eject storage in Linux first and close host apps that use the phone. Do not attach the keyboard or mouse needed to control the host. Temporary permission to a selected USB device may trigger a system authorization prompt; the app does not create a persistent USB permission rule.

For iPhone passthrough, the app may temporarily stop Mint's `usbmuxd.service` if it is active, then restore it after the Apple USB device is detached or the VM stops. No persistent host service setting is changed. USB behavior inside the guest depends on the guest OS and its drivers.

## Development

On Debian or Ubuntu based systems, install the desktop dependencies:

```sh
sudo apt install python3 python3-gi gir1.2-gtk-3.0 usbutils acl policykit-1
```

Run the app from the project directory:

```sh
python3 native_app.py
```

To build a `.deb`, install `debhelper` and run:

```sh
sudo apt install debhelper
dpkg-buildpackage -us -uc -b
```

The `.deb` is written to the parent directory. The project is maintained by one person; use GitHub issues to report problems or suggest features. The MIT license permits reuse and independent forks with attribution and preservation of the license notice.

## License

MIT. See [LICENSE](LICENSE).
