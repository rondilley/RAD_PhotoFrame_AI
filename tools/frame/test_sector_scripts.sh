#!/usr/bin/env bash
# Test the S1.2 sector scripts in a sandbox U-Boot (same commit as the frame build)
# against a copy of the first part of the eMMC backup. Nothing here touches a device.
# Run in the RAD_PhotoFrame_Build WSL distribution:
#   wsl -d RAD_PhotoFrame_Build -- bash /mnt/g/git/RAD_PhotoFrame_AI/tools/frame/test_sector_scripts.sh pf1007l-01
set -euo pipefail

UNIT=${1:?usage: test_sector_scripts.sh <unit>}
PROJ="$(cd "$(dirname "$0")/../.." && pwd)"
WORK="$HOME/rad"
SRC="$WORK/u-boot-sandbox"
BUILD="$WORK/u-boot-sandbox-build"
COMMIT=e50b1e8715011def8aff1588081a2649a2c6cd47 # v2025.10
GEN=(python3 -I "$PROJ/tools/frame/make_sector_scripts.py")
SDIR=$(ls -d "$PROJ/backups/$UNIT"/sector-* | head -1)
SECTOR=$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["sector"])' "$SDIR/manifest.json")
DISK="$WORK/test-disk.img"
FAILS=0

# 1. Sandbox U-Boot
if [ ! -x "$BUILD/u-boot" ]; then
  [ -d "$SRC/.git" ] || git clone -q --no-checkout "$WORK/u-boot" "$SRC"
  git -C "$SRC" checkout -q "$COMMIT"
  git -C "$SRC" reset -q --hard "$COMMIT"
  mkdir -p "$BUILD"
  make -s -C "$SRC" O="$BUILD" sandbox_defconfig > /dev/null
  "$SRC/scripts/config" --file "$BUILD/.config" -e CMD_HASH -e HASH_VERIFY -e SHA256 -e CMD_READ -e CMD_WRITE -e CMD_ITEST -e CMD_MEMORY -d EFI_CAPSULE_AUTHENTICATE
  make -s -C "$SRC" O="$BUILD" olddefconfig > /dev/null
  make -C "$SRC" O="$BUILD" NO_SDL=1 -j"$(nproc)" > "$WORK/u-boot-sandbox.log" 2>&1 || { tail -30 "$WORK/u-boot-sandbox.log"; exit 1; }
fi
for c in CMD_HASH HASH_VERIFY CMD_READ CMD_WRITE SANDBOX; do
  grep -q "^CONFIG_$c=y" "$BUILD/.config" || { echo "STOP: sandbox CONFIG_$c is not set"; exit 1; }
done

# 2. Test disk: the backup up to the end of the system partition
SYS_START=237568; SYS_SECTORS=2097152
END=$((SYS_START + SYS_SECTORS))
fresh_disk() {
  dd if="$PROJ/backups/$UNIT/emmc-full.img" of="$DISK" bs=1M count=$((END * 512 / 1048576)) status=none
}
fresh_disk
BASE_SHA=$(sha256sum "$DISK" | cut -d' ' -f1)
sector_sha() { dd if="$DISK" bs=512 skip="$SECTOR" count=1 status=none | sha256sum | cut -d' ' -f1; }
STOCK=$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["stock_sha256"])' "$SDIR/manifest.json")
EDITED=$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["edited_sha256"])' "$SDIR/manifest.json")

# 3. One run: make a test script, load the payloads, run it, read the serial
#    run <mode> <expected serial code> [stock payload file] [edited payload file]
run() {
  local mode=$1 want=$2 pstock=${3:-$SDIR/stock.bin} pedited=${4:-$SDIR/edited.bin}
  local dir plan marker prefix out got
  dir="$PROJ/$("${GEN[@]}" script "$UNIT" "$mode" --test)"
  plan="$dir/plan.json"
  marker=$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["marker"])' "$plan")
  prefix=$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["serial_prefix"])' "$plan")
  out=$("$BUILD/u-boot" -c "setenv serial# 0461872A00800000; host bind 0 $DISK; load hostfs - 0x01000000 $pstock; load hostfs - 0x01001000 $pedited; load hostfs - 0x02000000 $dir/sector.scr; source 0x02000000" 2>&1 || true)
  echo "$out" > "$dir/sandbox.log"
  got=$(echo "$out" | tr -d '\r' | sed -n 's/^result: //p' | tail -1)
  if [ "$got" = "$prefix-$want-$marker" ]; then
    echo "  pass  $mode -> $got"
  else
    echo "  FAIL  $mode: want $prefix-$want-$marker, got '$got' (log $dir/sandbox.log)"; FAILS=$((FAILS + 1))
  fi
}
expect_sector() {
  local want=$1 name=$2 now
  now=$(sector_sha)
  if [ "$now" = "$want" ]; then echo "  pass  sector is $name"; else echo "  FAIL  sector is $now, not $name"; FAILS=$((FAILS + 1)); fi
}
expect_disk() {
  local now
  now=$(sha256sum "$DISK" | cut -d' ' -f1)
  if [ "$now" = "$1" ]; then echo "  pass  $2"; else echo "  FAIL  $2"; FAILS=$((FAILS + 1)); fi
}

echo "stock disk:"
run check STOCK
run restore ALREADY_NO_WRITE
expect_disk "$BASE_SHA" "no change to the disk"
run apply WRITTEN_VERIFIED
expect_sector "$EDITED" edited

# Only the one sector changed: put the stock sector back in a copy and compare.
cp "$DISK" "$WORK/test-disk-edited.img"
dd if="$PROJ/backups/$UNIT/emmc-full.img" of="$WORK/test-disk-edited.img" bs=512 skip="$SECTOR" seek="$SECTOR" count=1 conv=notrunc status=none
[ "$(sha256sum "$WORK/test-disk-edited.img" | cut -d' ' -f1)" = "$BASE_SHA" ] \
  && echo "  pass  the edit changed only sector $SECTOR" \
  || { echo "  FAIL  bytes outside sector $SECTOR changed"; FAILS=$((FAILS + 1)); }
rm -f "$WORK/test-disk-edited.img"

# The edited file system: e2fsck -n must give the same result as on the stock
# partition (Android's image tool leaves a bitmap padding note on both), and
# build.prop must be the stock file with only the one line changed.
dd if="$DISK" of="$WORK/test-system.img" bs=512 skip=$SYS_START count=$SYS_SECTORS status=none
e2fsck -n -f "$WORK/test-system.img" > "$WORK/test-e2fsck.log" 2>&1 && E_EDIT=0 || E_EDIT=$?
e2fsck -n -f "$WORK/$UNIT-system.img" > "$WORK/test-e2fsck-stock.log" 2>&1 && E_STOCK=0 || E_STOCK=$?
if [ "$E_EDIT" = "$E_STOCK" ] && cmp -s <(sed 1d "$WORK/test-e2fsck.log") <(sed 1d "$WORK/test-e2fsck-stock.log"); then
  echo "  pass  e2fsck -n: edited partition gives the same result as stock (exit $E_EDIT)"
else
  echo "  FAIL  e2fsck -n differs from stock (see $WORK/test-e2fsck*.log)"; FAILS=$((FAILS + 1))
fi
debugfs -c -R "cat /build.prop" "$WORK/test-system.img" 2>/dev/null > "$WORK/test-build.prop"
sed 's/^persist\.sys\.usb\.config=mass_storage$/persist.sys.usb.config=adb         /' "$WORK/$UNIT-build.prop" > "$WORK/test-build.prop.want"
if cmp -s "$WORK/test-build.prop" "$WORK/test-build.prop.want" && grep -qx 'persist.sys.usb.config=adb *' "$WORK/test-build.prop"; then
  echo "  pass  build.prop is the stock file with only persist.sys.usb.config=adb changed"
else
  echo "  FAIL  build.prop content"; FAILS=$((FAILS + 1))
fi
rm -f "$WORK/test-system.img"

echo "edited disk:"
run apply ALREADY_NO_WRITE
run check EDITED
run restore WRITTEN_VERIFIED
expect_sector "$STOCK" stock
expect_disk "$BASE_SHA" "restore gives the original disk"

echo "refusals:"
dd if=/dev/urandom of="$DISK" bs=512 seek="$SECTOR" count=1 conv=notrunc status=none
OTHER_SHA=$(sha256sum "$DISK" | cut -d' ' -f1)
run check OTHER
run apply REFUSED_OTHER
run restore REFUSED_OTHER
expect_disk "$OTHER_SHA" "no write to an unknown sector"
fresh_disk
printf 'X' | dd of="$DISK" bs=1 seek=440 conv=notrunc status=none
MBR_SHA=$(sha256sum "$DISK" | cut -d' ' -f1)
run apply REFUSED_DISK
expect_disk "$MBR_SHA" "no write to a disk with a different MBR"
fresh_disk
run apply REFUSED_PAYLOAD "$SDIR/edited.bin" "$SDIR/edited.bin"
run apply REFUSED_PAYLOAD "$SDIR/stock.bin" "$SDIR/stock.bin"
expect_disk "$BASE_SHA" "no write with a wrong payload"

rm -f "$DISK"
echo
if [ "$FAILS" = 0 ]; then
  rm -rf "$PROJ"/diagnostics/sector-run/test-*
  echo "PASS: all sector script tests"
else
  echo "FAIL: $FAILS test(s); logs in diagnostics/sector-run/test-*"; exit 1
fi
