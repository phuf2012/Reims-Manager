# Reims Manager

Reims Manager is a native GTK desktop app for managing virtual machines created by [Reims vGPU](https://github.com/steelbrain/reims-vgpu). It currently targets Linux desktop systems such as Ubuntu and other Linux distros (ones that support `.deb`).

## Reims Manager 1.0.2-5 — Pre-Release

- Give the native GTK app a consistent Reims Manager dark theme instead of inheriting most colors from the desktop theme.
- Count up to four physical USB devices per VM; the VM's virtual keyboard and mouse are not counted.
- For Apple devices, match QEMU passthrough by physical USB port and vendor when available, so a phone that re-enumerates at a new USB address can remain associated with its port.
- Detect and disable the duplicate Apple-device row when the phone reappears on the same port, with a clear “Already connected” status.
- Show USB slot use in both interfaces and reject a fifth device before unmounting or releasing anything from Linux.
- Add package-format-aware update asset selection for `.deb`, `.rpm`, and `.AppImage` release assets; this build remains a `.deb` and does not install updates automatically.
- Record Apple Watch and distro update-manager support as explicit groundwork only. Watch pairing and signed distro repositories are not implemented in this release.

## Reims Manager 1.0.2-4 — Pre-Release

This pre-release focuses on USB passthrough, Apple mobile devices, and clearer graphics choices.

- Connect a device to the running VM or return it to Linux with one clearly labeled action.
- USB devices are rescanned every five seconds while the USB page is open.
- Attach and detach actions are serialized, checked against the current USB device identity, and protected against Linux reusing a bus/address for a different device.
- USB troubleshooting details are tucked into an optional section; the main list focuses on the device, its status, and the action.
- USB state files are written atomically with private file permissions.
- Improved progress and status messages in the GTK and browser interfaces.
- Safely unmounts mounted USB drive volumes from Linux during connection, then passes the whole USB device to the VM.
- Restores Mint's Apple USB service after an interrupted iPhone attach when QEMU no longer has a manager-owned USB device attached.
- Detects the VM's active USB controller and hotplugs to that bus; it no longer assumes every VM has a dedicated `hostpass.0` controller.
- Correctly recognizes mounted partitions belonging to a USB disk before attempting the safe unmount.
- Gives connected iPhone/iPad devices specific unlock, Trust, and passcode guidance in the USB list.
- Adds an explicit graphics backend setting: Reims vGPU for accelerated graphics, or QEMU VMware SVGA as a compatibility fallback without acceleration.
- Stable builds no longer offer prereleases as updates. Update checks use the official GitHub Releases API over HTTPS and link directly to the matching package-format asset.

The guest operating system still needs its own drivers to recognize a passed-through device. Linux gives up access while the VM owns it. USB volumes that Linux currently has mounted are unmounted before passthrough; open files or transfers can make Linux refuse the unmount, in which case the app explains what to close. The manager does not install system rules or persist device permissions.

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

The **Updates** section has a **Check for Updates** action and an opt-in automatic check setting. Enabling it checks immediately, then at app launch no more than once per day. It links to the newer matching package asset; Reims Manager never installs an update without your action. Update checks contact the public GitHub Releases API for `phuf2012/Reims-Manager` over HTTPS. Appearing in Linux distribution update managers requires signed package repositories for each supported package ecosystem; this GitHub-release workflow does not configure them.

### Beta and future ideas

- **Apple Watch passthrough is not supported in this release.** Apple Watch setup and pairing are handled through a paired iPhone, so exposing a USB device alone would not make watchOS pairing work. This remains a research item, not a working beta feature.
- Integration with distro update managers is a future item. Each package ecosystem needs its own signed repository and release metadata. Until those exist, this app only checks GitHub Releases and links to the matching published package asset.

## Scope

This is a focused app, not a Virt Manager replacement. Reims does not use libvirt, and Reims Manager does not provide libvirt networks, snapshots, storage pools, XML editing, or SPICE redirection. Reims vGPU must be installed separately. Windows support is not available yet; this app and the current Reims host integration target Linux.

## First use

1. Install Reims vGPU by following its [upstream instructions](https://github.com/steelbrain/reims-vgpu).
2. Install Reims Manager from the `.deb` attached to a GitHub release, or run it from a source checkout with `python3 native_app.py`.
3. Create a VM with Reims if you have not already. Reims Manager operates VMs created by Reims; it does not create VMs or download macOS.
4. Open Reims Manager, select a VM, and choose **Start**. For USB passthrough, open **USB devices**, select a listed device, and choose **Connect to VM**. Choose **Return to Linux** when finished.

The Debian package declares GTK 3, Python GTK bindings, `usbutils`, `acl`, `udisks2`, and PolicyKit dependencies. Samba is a suggested optional package for shared folders. The package does not install Reims or create persistent host USB rules.

## USB notes

Attaching a physical USB device gives it to the VM; Linux may lose access until you detach it or stop the VM. Safely eject storage in Linux first and close host apps that use the phone. Do not attach the keyboard or mouse needed to control the host. Temporary permission to a selected USB device may trigger a system authorization prompt; the app does not create a persistent USB permission rule.

For iPhone/iPad passthrough, unlock the device and approve **Trust** in the guest if prompted. The app may temporarily stop Mint's `usbmuxd.service` if it is active, then restore it after the Apple USB device is detached or the VM stops. No persistent host service setting is changed. USB behavior inside the guest depends on the guest OS and its drivers.

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
