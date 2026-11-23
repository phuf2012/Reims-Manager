# Reims Manager

Reims Manager is a native GTK desktop app for managing virtual machines created by [Reims vGPU](https://github.com/steelbrain/reims-vgpu). It currently targets Linux desktop systems such as Linux Mint and Ubuntu.

## Reims Manager 1.0.2-1 — Pre-Release

This pre-release focuses on USB passthrough reliability and a simpler connect/return workflow.

- Connect a device to the running VM or return it to Linux with one clearly labeled action.
- USB devices are rescanned every five seconds while the USB page is open.
- Attach and detach actions are serialized, checked against the current USB device identity, and protected against Linux reusing a bus/address for a different device.
- USB troubleshooting details are tucked into an optional section; the main list focuses on the device, its status, and the action.
- USB state files are written atomically with private file permissions.
- Improved progress and status messages in the GTK and browser interfaces.

The guest operating system still needs its own drivers to recognize a passed-through device. Linux gives up access while the VM owns it. The manager does not install system rules or persist device permissions.

## Reims Manager 1.0.1 — Stable

The stable app can:

- List Reims VMs and show their state and virtual hardware.
- Start and stop a VM. Starting uses the host display resolution and borderless mode.
- List host USB devices and attach or detach a selected device while a VM is running.
- Show guest USB diagnostics and recent Reims/QEMU logs.
- Edit supported CPU, RAM, GPU, video acceleration, resolution, refresh rate, HiDPI, borderless, audio, network, and logging settings for a stopped VM.
- Share a selected Linux folder with macOS through QEMU's SMB support.
- Check GitHub for updates, with optional automatic checks.

Settings apply on the VM's next start, and **Start** preserves them instead of silently forcing host resolution. Start and shutdown show progress and prevent duplicate clicks.

The **Shared folder** section can expose one Linux folder to macOS with QEMU's private SMB network. The guest can read and write the selected folder while the VM runs. It requires Samba's `smbd` on the host (`sudo apt install samba`); Reims Manager does not install or enable Samba. Without `smbd`, the app shows that requirement and will not save an unusable share. In macOS Finder, use **Go → Connect to Server** and enter `smb://10.0.3.4/qemu`. The share uses a private VM network and is not available from your local network.

The **Updates** section has a **Check for Updates** action and an opt-in automatic check setting. Enabling it checks immediately, then at app launch no more than once per day. It links to the newer release `.deb`; Reims Manager never downloads or installs an update without your action. Update checks contact the public GitHub Releases API for `phuf2012/Reims-Manager`.

## Scope

This is a focused app, not a Virt Manager replacement. Reims does not use libvirt, and Reims Manager does not provide libvirt networks, snapshots, storage pools, XML editing, or SPICE redirection. Reims vGPU must be installed separately. Windows support is not available yet; this app and the current Reims host integration target Linux.

## First use

1. Install Reims vGPU by following its [upstream instructions](https://github.com/steelbrain/reims-vgpu).
2. Install Reims Manager from the `.deb` attached to a GitHub release, or run it from a source checkout with `python3 native_app.py`.
3. Create a VM with Reims if you have not already. Reims Manager operates VMs created by Reims; it does not create VMs or download macOS.
4. Open Reims Manager, select a VM, and choose **Start**. For USB passthrough, open **USB devices**, select a listed device, and choose **Connect to VM**. Choose **Return to Linux** when finished.

The Debian package declares GTK 3, Python GTK bindings, `usbutils`, `acl`, and PolicyKit dependencies. Samba is a suggested optional package for shared folders. The package does not install Reims or create persistent host USB rules.

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
