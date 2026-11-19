# Frame Runbook: PF1007L Root, Kiosk and Host

This runbook tells you how to get root on a PF1007L photo frame and install
the kiosk. It also tells you how to connect the frame to the RAD Frame host
service. It follows the
procedure that made the frame `pf1007l-01` work on 2026-10-14.

ARCHITECTURE §14 gives the design of this procedure. The record of the first
unit is in `frames/pf1007l-01/changes.jsonl` (ignored by git).

## 1. Read this first

### 1.1 Warnings

- **WARNING: An incorrect write to the eMMC can make the frame unserviceable.**
  Make a verified full backup before the first write (Phase 3).
- **WARNING: An incorrect raw write on the workstation can erase the data on a different disk.**
  Before each raw write, make sure of the disk number, the size, the bus and
  the model. Disk numbers and drive letters can change after a restart.
- **CAUTION: Do not connect the frame to a network before Phase 11.** The
  stock firmware has vendor software that sends data to the internet, and a
  file service on TCP 8086.

### 1.2 Scope

This procedure is for one configuration only:

| Item | Necessary value |
| --- | --- |
| Frame | PF1007L / AiMOR, Allwinner A33, Android 6.0.1 |
| Firmware | Suffix `20260113` (January) on the About screen |
| Stock USB mode | `1f3a:1000` (mass storage), no ADB |
| Ports | One USB-C port and one microSD slot |
| Host | Windows 11 with WSL2 and PowerShell 7 |

If your frame has a different firmware, stop. The sector values in this
runbook are correct only for the January firmware. If `adb devices` shows the
frame on the stock firmware, Phases 2 to 5 are not necessary. Go to Phase 6.

### 1.3 Values for one unit and one card

The tools contain values for the first unit and for the first microSD card.
Before you use the tools on a different frame, change these values.

| File | Value | Change to |
| --- | --- | --- |
| `tools/frame/fel_card.ps1` | `$CardLetter`, `$CardName`, `$CardSize` | The drive letter, the model and the byte size of your card |
| `tools/frame/emmc_backup.ps1` | `backups\pf1007l-01` | `backups\<unit>` |
| `tools/frame/sector_fel.ps1` | `-Unit` default | Your unit name, or give `-Unit <unit>` |
| `tools/frame/kiosk_install.ps1` | `-Unit` default | Your unit name, or give `-Unit <unit>` |
| `tools/frame/capture.ps1` | `-Unit` default | Your unit name, or give `-Unit <unit>` |
| `tools/frame/test_sector_scripts.sh` | `SYS_START`, `SYS_SECTORS` | The system partition of your backup (Phase 4) |
| `config/radframe.toml` | `[frame] adb_serial` | The ADB serial of your frame |

In this runbook, `<unit>` is your unit name, for example `pf1007l-02`.
`<serial>` is the USB serial of your frame.

### 1.4 Rules for each step

1. **Stop at the first difference.** If an output is not the expected
   output, stop. Do not do the next step. Find the cause first.
2. **No write without a backup.** Do not write to the frame before Phase 3
   gives a verified backup.
3. **One approval for each write.** The write tools refuse to run without
   `-ApproveWrite` or `--approve-write`. Give this flag only when you agree
   with that one write.
4. **Record the undo.** Each write tool adds two lines to
   `frames/<unit>/changes.jsonl`: one line before the write, with the undo
   command, and one line after the write, with the result. If you do a
   write by hand, add the two lines with a text editor.
5. **Test the recovery path before you close the access path.** Test the
   kiosk escape to Android Settings with your finger before you disable the
   vendor app (Phase 8). `input tap` and `screencap` do not prove the escape.

### 1.5 Phase list

| Phase | Result | Writes to the frame |
| --- | --- | --- |
| 0 | Host tools | No |
| 1 | Frame identity | No |
| 2 | FEL tools and FEL card | No (writes to the microSD card) |
| 3 | Verified full eMMC backup | No |
| 4 | Sector scripts, with a sandbox test | No |
| 5 | Root ADB through USB | Yes, one sector |
| 6 | WebView 106 | Yes, `/system` |
| 7 | Host service | No |
| 8 | Kiosk and escape test | Yes, one app |
| 9 | Kiosk as Home, vendor apps off | Yes, package settings |
| 10 | Boot fixes and frame firewall | Yes, `/system` and `/data` |
| 11 | Frame network | Yes, Wi-Fi and kiosk settings |
| 12 | Host start at logon | No |

## 2. Equipment

- A PF1007L frame and its power supply.
- A USB-A to USB-C data cable. Connect it to a USB port on the workstation
  directly, not through a hub. A USB-C to USB-C cable gives no power and no
  data to this frame.
- A microSD card of 32 GB or smaller, and an SD card reader. The procedure
  writes 8192 bytes to the card. Do not use a card with important data.
- About 35 GB of free disk space for the backup files.
- A router that can make a network for the frame only, with egress rules
  (Phase 11).

## 3. Phase 0: Host tools

All commands start from the project root, `G:\git\RAD_PhotoFrame_AI`, in
PowerShell 7, unless the step says WSL.

1. Get the upstream example repository at the pinned commit:

   ```powershell
   git clone https://github.com/wesbos/photo-frame-dashboard background\photo-frame-dashboard
   git -C background\photo-frame-dashboard checkout 0c0defb
   ```

   The FEL patches, the U-Boot script and the boot-fix scripts come from this
   repository. Do not move the pin before you read the upstream diff.

2. Install the Android tools:
   - Android command-line tools in
     `%LOCALAPPDATA%\Android\Sdk\cmdline-tools\latest`.
   - `sdkmanager "platform-tools" "build-tools;34.0.0" "platforms;android-34"`.
   - Temurin JDK 17 (`winget install EclipseAdoptium.Temurin.17.JDK`).
   - Set the user variable `ANDROID_HOME` to `%LOCALAPPDATA%\Android\Sdk`, and
     put `%ANDROID_HOME%\platform-tools` on the user `PATH`.

3. Compare the SHA-256 of each download with `tools/frame/bom.toml`. If a
   hash is different, stop.

4. Open a new terminal. Make sure that the tools start:

   ```powershell
   adb version
   java -version
   ```

   Expected: adb 1.0.41 or newer, and Java 17.

5. Install Python 3.12 or newer, then the host packages:

   ```powershell
   python -m pip install fastapi uvicorn jinja2 markupsafe httpx psutil nvidia-ml-py `
     icalendar recurring-ical-events python-docx garminconnect
   ```

6. Make a clean WSL distribution for the builds. Do not use a WSL
   distribution that has other work in it.

   ```powershell
   wsl --install -d Ubuntu-24.04 --name RAD_PhotoFrame_Build
   ```

   If `wsl --install` gives TLS errors, download the image with `curl`,
   compare its hash with `bom.toml`, and use `wsl --import`.

7. In the WSL distribution, install the build packages. The build scripts
   do not install packages. This list is the usual U-Boot and mingw-w64 set.
   If a build stops for a missing tool, install it and run the build again:

   ```bash
   sudo apt-get update
   sudo apt-get install -y build-essential gcc-arm-linux-gnueabihf mingw-w64 \
     bison flex swig python3-dev python3-setuptools libssl-dev libgnutls28-dev \
     u-boot-tools device-tree-compiler e2fsprogs pkg-config git curl
   ```

**NOTE:** Start `wsl` from PowerShell, not from Git Bash. Git Bash changes
the `/mnt/...` paths. Do not put commands with `$` in
`wsl -- bash -c '...'`. Put them in a script file.

## 4. Phase 1: Frame identity (no write)

1. Disconnect the frame from all networks. If the frame knows a Wi-Fi
   network, turn off Wi-Fi in Android Settings.
2. On the frame, open the About screen. Write down the model and the
   firmware string. The firmware string must end in `20260113`.
3. Connect the frame to the workstation with the USB-A to USB-C cable.
4. In Device Manager, find the frame USB device. Write down the VID:PID and
   the serial.
   - Expected: `1f3a:1000`, with two empty storage drives.
5. Run `adb devices`.
   - Expected: no device. If the frame shows, it has stock ADB (see §1.2).
6. Make the folder `frames\<unit>\`. Write `frames\<unit>\identity.json` by
   hand. Use `frames\pf1007l-01\identity.json` as the model. Record at
   minimum: `unit`, `usb.vid_pid`, `usb.serial`, `about_screen.model` and
   `about_screen.firmware_suffix`.
7. Add the first lines to `frames\<unit>\changes.jsonl`, one JSON object on
   each line, with the fields `time`, `step`, `class`, `action` and
   `result`.

## 5. Phase 2: FEL tools and the FEL card (no write to the frame)

FEL is the USB boot mode of the A33 ROM. A small stub on the microSD card
puts the frame in FEL at power-on. Then `sunxi-fel` loads a read-only U-Boot
into RAM. Nothing goes to the eMMC in this phase.

1. Build `sunxi-fel.exe` for Windows:

   ```powershell
   wsl -d RAD_PhotoFrame_Build -- bash /mnt/g/git/RAD_PhotoFrame_AI/tools/frame/build_sunxi_fel.sh
   ```

   Output: `diagnostics\sunxi-fel\sunxi-fel.exe` and the stub
   `fel-sdboot.sunxi`. The script compares each download with its pinned
   hash.

2. Build the RAM-only, read-only U-Boot:

   ```powershell
   wsl -d RAD_PhotoFrame_Build -- bash /mnt/g/git/RAD_PhotoFrame_AI/tools/frame/build_uboot.sh
   ```

   Output: `diagnostics\u-boot-out\u-boot-sunxi-with-spl.bin` and
   `ums-readonly.scr`. Compare the two hashes with `[fel.u_boot]` in
   `bom.toml`. If you changed a patch, the hash can be different. In that
   condition, do not continue before you know the cause.

3. Put the microSD card in the workstation card reader. In an Administrator
   PowerShell, find its disk number and its size in bytes:

   ```powershell
   Get-Disk | Format-Table Number, FriendlyName, BusType, Size
   pwsh -File tools\frame\disk_info.ps1 <card-disk>
   ```

   **WARNING:** Make sure that the disk is the card. Do the check again if
   you restart the workstation or connect the reader again.

4. Change the card values in `fel_card.ps1` (§1.3). Then run, in an
   Administrator PowerShell:

   ```powershell
   pwsh -File tools\frame\fel_card.ps1 check  <card-disk> <card-bytes>
   pwsh -File tools\frame\fel_card.ps1 backup <card-disk> <card-bytes>
   pwsh -File tools\frame\fel_card.ps1 write  <card-disk> <card-bytes>
   ```

   - `backup` saves the first 4 MiB of the card to `backups\sdcard-n\`.
   - `write` puts the 8192-byte stub at byte 8192 and reads it back.
   - Undo: `fel_card.ps1 restore <card-disk> <card-bytes>`.

5. Disconnect the frame from USB and remove its power. Put the FEL card in
   the frame. Connect the USB cable to the frame.
   - Expected: a new USB device `1f3a:efe8`.

6. Install the WinUSB driver on `1f3a:efe8` only. Use Zadig 2.9 (hash in
   `bom.toml`). Select the device `1f3a:efe8`, then WinUSB. Do not change
   the driver of a different device.

7. Make sure that FEL works:

   ```powershell
   diagnostics\sunxi-fel\sunxi-fel.exe version
   ```

   Expected: `AWUSBFEX soc=00001667(A33)`. If the SoC is different, stop.

## 6. Phase 3: Full eMMC backup (no write to the frame)

1. Load the read-only U-Boot into RAM. The frame must be in FEL (Phase 2,
   step 5):

   ```powershell
   diagnostics\sunxi-fel\sunxi-fel.exe -v uboot diagnostics\u-boot-out\u-boot-sunxi-with-spl.bin write 0x43100000 diagnostics\u-boot-out\ums-readonly.scr
   ```

   Expected: two new disks with the model `Linux UMS disk N USB Device`.
   Disk 0 is the microSD card in the frame. Disk 1 is the eMMC. Both are
   read-only.

2. In an Administrator PowerShell, find the eMMC disk number:

   ```powershell
   Get-CimInstance Win32_DiskDrive | Where-Object Model -like 'Linux UMS*' | Format-Table Index, Model, Size
   pwsh -File tools\frame\disk_info.ps1 <emmc-disk>
   ```

   Expected: `writable: no (error 19 ...)`. Write down the byte count. If
   the disk is writable, stop.

3. Add the byte count to `identity.json` as `emmc_bytes`, and the
   sector count as `emmc_sectors`.

4. Change `backups\pf1007l-01` in `emmc_backup.ps1` to `backups\<unit>`
   (§1.3). Then make the backup. Send the output to a file, because a text
   selection in the console stops the process:

   ```powershell
   pwsh -File tools\frame\emmc_backup.ps1 backup <emmc-disk> <emmc-bytes> *> diagnostics\emmc-backup.log
   ```

   The script reads each 1 GiB segment two times, and compares the two reads
   and the readback from the image file. The run takes some hours. If the
   frame disconnects, put it in FEL again, load U-Boot again (step 1), and
   run the same command. The script continues from the last good segment.

5. Check the backup:

   ```powershell
   python -I tools\frame\verify_backup.py <unit>
   python -I tools\frame\restore_check.py <unit>
   ```

   Expected: exit code 0 from each tool. The results go to
   `frames\<unit>\backups.json`. If a check fails, do not continue.

6. Keep `backups\<unit>\emmc-full.img.gz` and `emmc-full.sha256` on a second
   disk. This backup is the only path back to the stock firmware.

## 7. Phase 4: Sector scripts (no write to the frame)

The procedure changes one line in `/system/build.prop`:
`persist.sys.usb.config=mass_storage` becomes `persist.sys.usb.config=adb`,
with spaces at the end so that the line length stays the same. This is one
512-byte sector.

1. Find the sector in the backup. Run in WSL:

   ```powershell
   wsl -d RAD_PhotoFrame_Build -- python3 -I /mnt/g/git/RAD_PhotoFrame_AI/tools/frame/find_setting_sector.py <unit>
   ```

   Expected for the January firmware: sector `399221`, byte `247`, and the
   stock hash `f78d2d4e...a9c4`. The result goes to
   `frames\<unit>\setting_sector.json`. If the hash is different, stop. Your
   firmware is not the firmware of this runbook.

2. Make the stock sector and the edited sector:

   ```powershell
   python -I tools\frame\make_sector_scripts.py prepare <unit>
   ```

   Expected: the edited sector hash is `3e0b232c...afe4`. The files go to
   `backups\<unit>\sector-<n>\`.

3. Test the U-Boot scripts on a copy of the backup in a sandbox U-Boot:

   ```powershell
   wsl -d RAD_PhotoFrame_Build -- bash /mnt/g/git/RAD_PhotoFrame_AI/tools/frame/test_sector_scripts.sh <unit>
   ```

   Expected: all 22 checks are satisfactory. The test makes sure that the
   script writes only when the sector is stock. It also makes sure that
   `restore` puts the stock sector back, and that only the one line of
   `build.prop` changes.

## 8. Phase 5: Root ADB through USB (one eMMC write)

1. Put the frame in FEL with the FEL card (Phase 2, step 5). Make sure that
   Device Manager shows no other `1f3a` device.

2. Read the sector. This step loads U-Boot into RAM and does not write:

   ```powershell
   pwsh -File tools\frame\sector_fel.ps1 check -Unit <unit>
   ```

   Expected: `STOCK`. If you get `OTHER`, stop.

3. Write the sector. This is the only eMMC write of the procedure:

   ```powershell
   pwsh -File tools\frame\sector_fel.ps1 apply -Unit <unit> -ApproveWrite
   ```

   Expected: `WRITTEN_VERIFIED`. The script reads the result from the USB
   serial of the U-Boot disk, and records it in `changes.jsonl`.
   - If you get no result in 90 s, do not run `apply` again. Power-cycle the
     frame into FEL and run `check`.
   - Undo: `sector_fel.ps1 restore -Unit <unit> -ApproveWrite`.

4. Remove the power. Remove the FEL card from the frame. Connect the power
   and the USB cable. Wait for Android to start.

5. Make sure that root ADB works:

   ```powershell
   adb devices
   adb -s <serial> shell id
   ```

   Expected: USB device `1f3a:1001`, and `uid=0(root)`.

   **NOTE:** `adb devices` can also show a local TCP port as
   `emulator-5562`. Always give `-s <serial>`.

6. Add the Android identity to `identity.json`, then set
   `android.adb_serial` to `<serial>`:

   ```powershell
   python -I tools\frame\frame_adb.py record <unit>
   python -I tools\frame\frame_adb.py identity <unit>
   ```

7. Do three power cycles. After each cycle, run `adb -s <serial> shell id`.
   Expected: `uid=0(root)` three times. This is test TC-01.

## 9. Phase 6: WebView 106 (write to `/system`)

The stock WebView 44 cannot show the dashboards. This phase puts WebView
106.0.5249.126 in `/system/app/webview` and keeps the stock files.

1. Download the WebView APK from the URL in `[frame.webview]` of `bom.toml`
   to `diagnostics\webview\webview.apk`. Extract the three native libraries
   from `lib/armeabi-v7a/` of the APK to `diagnostics\webview\lib\arm\`.
   Compare all four hashes with `bom.toml`.

2. Read the current state:

   ```powershell
   python -I tools\frame\webview_swap.py check <unit>
   ```

   Expected: `STOCK`, and more than 300,000 KiB free in `/system`.

3. Do the swap:

   ```powershell
   python -I tools\frame\webview_swap.py apply <unit> --approve-write
   ```

   Expected: state `SWAPPED`, `versionName=106.0.5249.126`, and no library
   errors. The frame restarts during the step.
   - Undo: `webview_swap.py restore <unit> --approve-write`.

## 10. Phase 7: Host service (no write to the frame)

1. Make `config\radframe.toml` (git ignores it). The minimum file is:

   ```toml
   [frame]
   adb_serial = "<serial>"

   [host]
   bind = "127.0.0.1"

   [weather]
   place = "<town>"
   latitude = <latitude>
   longitude = <longitude>
   ```

   Until Phase 11, keep `bind = "127.0.0.1"`. The frame gets the pages
   through the USB cable with `adb reverse`.

2. Start the host in a console:

   ```powershell
   python -m radframe serve
   ```

3. Make sure that the host answers:

   ```powershell
   curl.exe http://127.0.0.1:8765/healthz
   ```

4. Get the path of the frame token file:

   ```powershell
   python -m radframe token
   ```

   The host makes the token on the first start, in
   `%LOCALAPPDATA%\RAD_PhotoFrame\frame.token`. Do not copy the token into
   the repository.

**NOTE:** The host keeps `adb reverse tcp:8765 tcp:8765` on the frame, and
makes it again after each frame restart.

## 11. Phase 8: Kiosk and the escape test (app install)

1. Build and install the kiosk:

   ```powershell
   pwsh -File tools\frame\kiosk_install.ps1 -Unit <unit> -HostUrl http://127.0.0.1:8765/frame -TokenFile $env:LOCALAPPDATA\RAD_PhotoFrame\frame.token -ApproveWrite
   ```

   The script builds `kiosk\build\rad-kiosk.apk` with `kiosk\build.ps1`
   (with the origin pin check), checks the frame identity, installs the APK,
   turns on the navigation service, and sets the host URL and the token.
   - Expected: `focused kiosk True` and `nav service enabled True`.
   - Undo: `kiosk_install.ps1 -Unit <unit> -Remove -ApproveWrite`.

2. Optional: run the WebView test page and the origin pin test (TC-06 and
   TC-36):

   ```powershell
   python -I tools\frame\kiosk_testpage.py
   ```

   Stop the host service first, because the test page uses port 8765.
   Expected: Chrome 106.0.5249.126, 10 of 10 feature checks, and five of five
   off-origin tries refused.

3. Do the escape test with your finger (TC-03). Do it three times:
   1. Hold one finger on the top-left corner of the screen for 3 s.
      Expected: the kiosk menu opens.
   2. Open Android Settings from the menu.
   3. Push the Dashboard button. Expected: the kiosk comes back.

   **CAUTION:** Do not continue to Phase 9 if the escape does not work. In
   Phase 9 you disable the vendor app, and the escape becomes the only path
   to Android Settings on the screen.

   If Android Settings shows no Back and Dashboard buttons, start the kiosk
   through ADB:

   ```powershell
   adb -s <serial> shell am start -n rad.photoframe.kiosk/.MainActivity
   ```

   At each start, the kiosk turns the accessibility switch on again.

## 12. Phase 9: Kiosk as Home and vendor apps off (package settings)

1. Make the kiosk the Home app:

   ```powershell
   adb -s <serial> shell am start -S -n rad.photoframe.kiosk/.ConfigActivity --ez home true
   adb -s <serial> shell input keyevent KEYCODE_HOME
   ```

   On the frame, select "RAD Frame" in the Home chooser, then "Always".
   - Undo: `am start -S -n rad.photoframe.kiosk/.ConfigActivity --ez home false`.

2. Restart the frame (`adb -s <serial> reboot`). Expected: the kiosk opens
   after the restart.

3. Disable the vendor apps:

   ```powershell
   adb -s <serial> shell pm disable com.efercro.os.aimor
   adb -s <serial> shell pm disable com.yhk.qeota
   adb -s <serial> shell pm disable com.DeviceTest
   ```

   - `com.efercro.os.aimor` is the AiMOR app and its file service on TCP 8086.
   - `com.yhk.qeota` is the vendor update app.
   - `com.DeviceTest` is the factory test app.
   - Undo: `adb -s <serial> shell pm enable <package>` for each package.
   - Add one line for each package to `changes.jsonl`, with the undo.

4. Restart the frame. Make sure of the result:

   ```powershell
   adb -s <serial> shell pm list packages -d
   adb -s <serial> shell netstat -an
   ```

   Expected: the three packages show as disabled. No socket is in the
   `LISTEN` state, other than on `127.0.0.1`.

## 13. Phase 10: Boot fixes and frame firewall (write to `/system` and `/data`)

The boot fixes come from the upstream `scripts/pf1007l-boot/` at `0c0defb`,
plus two project scripts in `tools/frame/device/`. They do these tasks at each
boot:

- Keep one MAC address, so that a router rule for the frame stays correct.
- Start Wi-Fi after the boot, and set the clock from NTP.
- Start `rad-firewall.sh`. This firewall drops each new inbound connection
  on Wi-Fi, and checks its rules each 60 s.

1. Read the current state:

   ```powershell
   python -I tools\frame\boot_fixes.py check <unit>
   ```

2. Install the fixes. The tool saves a backup of each file that it changes to
   `backups\<unit>\boot-fixes\<time>\`:

   ```powershell
   python -I tools\frame\boot_fixes.py apply <unit>
   ```

   - Undo: `boot_fixes.py uninstall <unit>`.

3. Restart the frame. Then:

   ```powershell
   python -I tools\frame\boot_fixes.py verify <unit>
   ```

   Expected: `MAC pinned True`, the firewall rules are on the frame, and TCP
   listen is on loopback only.

**NOTE:** If the frame knows a Wi-Fi network, it can connect after the
restart. To keep Wi-Fi off until Phase 11:

```powershell
adb -s <serial> shell "touch /data/local/frame-nowifi; svc wifi disable"
```

## 14. Phase 11: Frame network

Do these steps in sequence. Do not connect the frame to Wi-Fi before step 2.

1. Make a network for the frame only (a VLAN or an SSID) on the router.
   Give the frame a DHCP reservation for its pinned MAC address.

2. Make the router egress rules. The frame can connect only to:
   - The host on TCP 8765.
   - DNS and NTP, if they are necessary on your network.

   The frame must not connect to the internet, other LAN hosts or other host
   ports.

3. Give the workstation a DHCP reservation too. The kiosk keeps the host
   address as a fixed IP address. If the host address changes, the frame
   shows "Host offline".

4. Make the Windows firewall rule in an Administrator PowerShell:

   ```powershell
   pwsh -File tools\host\firewall_rule.ps1 -FrameSubnet <frame-address-or-subnet>
   ```

   The rule lets only the frame network connect to `pythonw.exe` on TCP
   8765. Undo: `firewall_rule.ps1 -Remove`.

5. Turn on Wi-Fi on the frame and connect it to the frame network:

   ```powershell
   adb -s <serial> shell "rm /data/local/frame-nowifi; svc wifi enable"
   ```

   Use Android Settings (through the kiosk escape) to select the network.

6. Test the egress rules from the frame (TC-07). Use `nc` on the frame:

   ```powershell
   adb -s <serial> shell "nc -z -w 3 <host-ip> 8765; echo rc=`$?"
   adb -s <serial> shell "nc -z -w 3 <host-ip> 445; echo rc=`$?"
   adb -s <serial> shell "nc -z -w 3 1.1.1.1 443; echo rc=`$?"
   ```

   Expected: `rc=0` for port 8765 only. Each other test must give a
   different code. Do not
   use `ping` as the test. The toybox `nc` has no UDP mode and does not
   resolve names.

7. Set `bind = "0.0.0.0"` in `config\radframe.toml`, and start the host
   again.

8. Make sure that a request without the token gets HTTP 403:

   ```powershell
   adb -s <serial> shell "echo -e 'GET /frame HTTP/1.0\r\n\r\n' | nc -w 3 <host-ip> 8765 | head -1"
   ```

9. Point the kiosk at the host on the network:

   ```powershell
   adb -s <serial> shell am start -n rad.photoframe.kiosk/.ConfigActivity --es host_url http://<host-ip>:8765/frame
   ```

   - Undo: the same command with `http://127.0.0.1:8765/frame`. The USB
     connection stays available.
   - Record the change and the undo in `changes.jsonl`.

10. Restart the frame. Expected: the dashboards show, and `/healthz` shows a
    frame heartbeat of less than 20 s.

## 15. Phase 12: Host start at logon

1. Stop the host in the console.
2. Install the logon start:

   ```powershell
   pwsh -File tools\host\install_startup.ps1
   ```

   This puts the shortcut "RAD Frame host" in the user Startup folder. The
   shortcut starts `pythonw.exe -m radframe run`. The supervisor starts the
   host again if it stops. Logs go to `%LOCALAPPDATA%\RAD_PhotoFrame\logs\`.
   - Undo: `install_startup.ps1 -Remove`.

3. Sign out and sign in again. Make sure that `/healthz` answers.

4. Do a run of 24 hours. Then examine the frame screen and the host logs.

## 16. Daily operation

| Task | Command or action |
| --- | --- |
| See the host state | `curl.exe http://127.0.0.1:8765/healthz` |
| Get a screen capture of one dashboard | `pwsh -File tools\frame\capture.ps1 <dashboard> -Unit <unit>` |
| Open Android Settings | Corner hold of 3 s, or `adb -s <serial> shell am start -a android.settings.SETTINGS` |
| Install a new kiosk version | `kiosk_install.ps1` as in Phase 8 |
| Change the host URL | `ConfigActivity --es host_url ...` as in Phase 11, step 9 |

Screen captures go to `diagnostics\kiosk\`. Delete each capture that shows
private data after you use it.

## 17. Troubleshooting

| Symptom | Possible cause | Action |
| --- | --- | --- |
| Frame shows "Host offline" | The host IP address changed after a power outage | Compare `ipconfig` with the `host_url` in `/data/data/rad.photoframe.kiosk/shared_prefs/kiosk.xml`. Test with `nc` from the frame. Change `host_url` (Phase 11, step 9). Make a DHCP reservation for the host. |
| Frame shows "Host offline" | The host service stopped | Look at `%LOCALAPPDATA%\RAD_PhotoFrame\logs\supervisor.log`. Start the host again. |
| `adb devices` shows no frame | Cable, hub or port | Use the USB-A to USB-C data cable on a direct port. |
| `adb devices` shows `emulator-5562` | A local TCP port | Give `-s <serial>` to each `adb` command. |
| No Back and Dashboard buttons in Android Settings | Accessibility switch is off | Start the kiosk with `am start` (Phase 8, step 3). |
| A long press starts a text selection | Kiosk older than 0.1.1 | Install the current kiosk. |
| Clock is incorrect after a restart | NTP not available | Make sure that the frame can connect to the NTP server in `/data/local/frame-boot.conf`. |
| `sector_fel.ps1` gives no result | FEL load or USB problem | Do not run `apply` again. Power-cycle into FEL and run `check`. |
| `emmc_backup.ps1` stops | Frame disconnected | Put the frame in FEL, load U-Boot, and run the same command. |
| WSL command gives incorrect paths | Started from Git Bash | Start `wsl` from PowerShell. |
| Vendor app comes back after a power cut | Package state reset | Do Phase 9, step 3 again. The router rules stop its traffic. |

## 18. Recovery

### 18.1 Undo table

Do the undo steps in the opposite sequence of the phases.

| Phase | Undo |
| --- | --- |
| 12 | `pwsh -File tools\host\install_startup.ps1 -Remove` |
| 11 | `ConfigActivity --es host_url http://127.0.0.1:8765/frame`, and `firewall_rule.ps1 -Remove` |
| 10 | `python -I tools\frame\boot_fixes.py uninstall <unit>` |
| 9 | `pm enable` for each vendor package, and `ConfigActivity --ez home false` |
| 8 | `pwsh -File tools\frame\kiosk_install.ps1 -Unit <unit> -Remove -ApproveWrite` |
| 6 | `python -I tools\frame\webview_swap.py restore <unit> --approve-write` |
| 5 | With the FEL card in the frame: `pwsh -File tools\frame\sector_fel.ps1 restore -Unit <unit> -ApproveWrite`. The USB mode becomes `mass_storage` again, and USB ADB stops. |
| 2 | `pwsh -File tools\frame\fel_card.ps1 restore <card-disk> <card-bytes>` |

### 18.2 To Android Settings

- Use the corner hold of 3 s on the kiosk.
- Or use root ADB: `adb -s <serial> shell am start -a android.settings.SETTINGS`.

### 18.3 To the stock firmware

- For a changed partition: write the partition image from the verified
  backup through root ADB, then read it back and compare the hash. Record the
  partition offsets from the backup MBR before the write.
- For a full eMMC restore: use the upstream procedure in
  `background/photo-frame-dashboard` at `0c0defb`. This is a large write.
  Get a different approval for it.

## 19. Records

| File | Contents | In git |
| --- | --- | --- |
| `frames/<unit>/identity.json` | USB, firmware, eMMC and Android identity | No |
| `frames/<unit>/changes.jsonl` | Each write, its result and its undo command | No |
| `frames/<unit>/backups.json` | Backup check results | No |
| `frames/<unit>/setting_sector.json` | Sector of the USB property | No |
| `backups/<unit>/` | eMMC backup, sector files, boot-fix backups | No |
| `diagnostics/` | Build output, logs, screen captures | No |
| `tools/frame/bom.toml` | SHA-256 of each download and build | Yes |
