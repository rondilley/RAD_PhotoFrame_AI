#!/usr/bin/env bash
# Build the RAM-only read-only PF1007L U-Boot for FEL (S1.1 item 3).
# Run in the RAD_PhotoFrame_Build WSL distribution:
#   wsl -d RAD_PhotoFrame_Build -- bash /mnt/g/git/RAD_PhotoFrame_AI/tools/frame/build_uboot.sh
# U-Boot v2025.10 + upstream pf1007l-uboot.patch + start-stop patch + 12 MHz patch,
# plus CMD_HASH/HASH_VERIFY for the guarded sector write.
# Builds in ~/rad, output goes to the ignored diagnostics/u-boot-out/.
# Nothing here touches a device.
set -euo pipefail

PROJ="$(cd "$(dirname "$0")/../.." && pwd)"
UP="$PROJ/background/photo-frame-dashboard"
WORK="$HOME/rad"
SRC="$WORK/u-boot"
BUILD="$WORK/u-boot-build"
OUT="$PROJ/diagnostics/u-boot-out"
COMMIT=e50b1e8715011def8aff1588081a2649a2c6cd47 # v2025.10
PATCHES=(
  "$UP/scripts/a33-uboot/pf1007l-uboot.patch"
  "$UP/docs/patches/pf1007l-v2025.10-start-stop.patch"
  "$UP/docs/patches/pf1007l-v2025.10-linux-12mhz.patch"
)

[ "$(git -C "$UP" rev-parse --short=7 HEAD 2>/dev/null || echo none)" = 0c0defb ] \
  || echo "NOTE: upstream repository is not a git checkout at 0c0defb; patch hashes below are the record"

if [ ! -d "$SRC/.git" ]; then
  git init -q "$SRC"
  git -C "$SRC" remote add origin https://github.com/u-boot/u-boot.git
  git -C "$SRC" fetch -q --depth 1 origin "$COMMIT"
  git -C "$SRC" checkout -q FETCH_HEAD
fi
[ "$(git -C "$SRC" rev-parse HEAD)" = "$COMMIT" ] || { echo "STOP: $SRC is not at $COMMIT"; exit 1; }

# Start from the clean pinned tree each time, then apply the patches with no fuzz.
git -C "$SRC" reset -q --hard "$COMMIT"
git -C "$SRC" clean -q -fdx
for p in "${PATCHES[@]}"; do
  (cd "$SRC" && patch --dry-run --fuzz=0 -p1 < "$p" > /dev/null && patch -s --fuzz=0 -p1 < "$p") \
    || { echo "STOP: $p does not apply"; exit 1; }
done
cat >> "$SRC/configs/pf1007l_backup_defconfig" <<'EOF'
CONFIG_CMD_HASH=y
CONFIG_HASH_VERIFY=y
CONFIG_SHA256=y
EOF

rm -rf "$BUILD" && mkdir -p "$BUILD" "$OUT"
export CROSS_COMPILE=arm-linux-gnueabihf-
make -s -C "$SRC" O="$BUILD" pf1007l_backup_defconfig > /dev/null
make -C "$SRC" O="$BUILD" -j"$(nproc)" > "$OUT/build.log" 2>&1 || { tail -40 "$OUT/build.log"; exit 1; }

for c in CMD_HASH HASH_VERIFY SHA256 CMD_USB_MASS_STORAGE USB_MUSB_GADGET SUNXI_NO_PMIC; do
  grep -q "^CONFIG_$c=y" "$BUILD/.config" || { echo "STOP: CONFIG_$c is not set"; exit 1; }
done
grep -E "^CONFIG_(DRAM_CLK|DRAM_ZQ|MMC_SUNXI_SLOT_EXTRA|SYS_CLK_FREQ|BOOTDELAY)=" "$BUILD/.config"

# Device tree check: 4-bit bus and 12 MHz on the eMMC node.
DTB="$BUILD/arch/arm/dts/sun8i-a33-pf1007l-backup.dtb"
fdtget "$DTB" /soc/mmc@1c11000 bus-width | grep -qx 4 || { echo "STOP: eMMC bus-width is not 4"; exit 1; }
fdtget "$DTB" /soc/mmc@1c11000 max-frequency | grep -qx 12000000 || { echo "STOP: eMMC max-frequency is not 12000000"; exit 1; }
echo "eMMC node: bus-width 4, max-frequency 12000000"

# SPL layout check: the SPL must end below 0x5e00 (early stack and global data).
END=$(arm-linux-gnueabihf-nm "$BUILD/spl/u-boot-spl" | awk '$3=="__image_copy_end"{print $1}')
EGON=$(python3 -I -c 'import struct,sys; print(hex(struct.unpack_from("<I", open(sys.argv[1],"rb").read(), 0x10)[0]))' "$BUILD/u-boot-sunxi-with-spl.bin")
echo "SPL __image_copy_end 0x$END, eGON length $EGON"
[ $((16#$END)) -lt $((0x5e00)) ] || { echo "STOP: SPL code ends too close to the stack/global-data area"; exit 1; }
[ $((EGON)) -le $((0x5e00)) ] || { echo "STOP: eGON length is above 0x5e00"; exit 1; }

cp "$BUILD/u-boot-sunxi-with-spl.bin" "$BUILD/.config" "$OUT/"
cp "$UP/scripts/a33-uboot/ums-readonly.cmd" "$OUT/"
mkimage -C none -A arm -T script -d "$OUT/ums-readonly.cmd" "$OUT/ums-readonly.scr" > /dev/null
(cd "$SRC" && git diff --stat && git status --short | grep '^??' || true) > "$OUT/source-changes.txt"
sha256sum "${PATCHES[@]}" "$OUT/u-boot-sunxi-with-spl.bin" "$OUT/ums-readonly.scr"
