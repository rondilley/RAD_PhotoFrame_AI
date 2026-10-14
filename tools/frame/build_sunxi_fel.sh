#!/usr/bin/env bash
# Build a static native Windows sunxi-fel.exe with mingw-w64 (S1.1 item 2).
# Run in the RAD_PhotoFrame_Build WSL distribution:
#   wsl -d RAD_PhotoFrame_Build -- bash /mnt/g/git/RAD_PhotoFrame_AI/tools/frame/build_sunxi_fel.sh
# Sources and pins are in tools/frame/bom.toml. Builds in ~/rad, output goes to
# the ignored diagnostics/sunxi-fel/. Nothing here touches a device.
set -euo pipefail

PROJ="$(cd "$(dirname "$0")/../.." && pwd)"
WORK="$HOME/rad"
DL="$WORK/dl"
PFX="$WORK/mingw-prefix"
OUT="$PROJ/diagnostics/sunxi-fel"
HOST=x86_64-w64-mingw32
SUNXI_COMMIT=d7bbd172a5da601a08f94479de308c6fb714a19a
STUB_SHA=2ccec08a026840571f3804671ba72afae840db27112a43f2b1f122075bc808bc

fetch() { # url sha256
  local f="$DL/$(basename "$1")"
  [ -s "$f" ] || curl -sSfL --retry 5 -o "$f" "$1"
  echo "$2  $f" | sha256sum -c --quiet - || { echo "STOP: hash mismatch for $f"; exit 1; }
}

mkdir -p "$DL" "$PFX" "$OUT"
fetch https://github.com/libusb/libusb/releases/download/v1.0.29/libusb-1.0.29.tar.bz2 \
  5977fc950f8d1395ccea9bd48c06b3f808fd3c2c961b44b0c2e6e29fc3a70a85
fetch https://github.com/madler/zlib/releases/download/v1.3.1/zlib-1.3.1.tar.gz \
  9a93b2b7dfdac77ceba5a558a580e74667dd6fede4585b91eefb60f03b72df23
fetch https://mirrors.edge.kernel.org/pub/software/utils/dtc/dtc-1.7.2.tar.xz \
  92d8ca769805ae1f176204230438fe52808f4e1c7944053c9eec0e649b237539

cd "$WORK"
rm -rf libusb-1.0.29 zlib-1.3.1 dtc-1.7.2
tar xf "$DL/libusb-1.0.29.tar.bz2"
tar xf "$DL/zlib-1.3.1.tar.gz"
tar xf "$DL/dtc-1.7.2.tar.xz"

# libusb, static
(cd libusb-1.0.29 && ./configure -q --host=$HOST --prefix="$PFX" --disable-shared --enable-static \
  && make -s -j"$(nproc)" && make -s install) > "$WORK/libusb.log" 2>&1 \
  || { tail -30 "$WORK/libusb.log"; exit 1; }

# zlib, static
(cd zlib-1.3.1 && make -s -f win32/Makefile.gcc PREFIX=$HOST- libz.a \
  && install -D -m644 libz.a "$PFX/lib/libz.a" \
  && install -m644 zlib.h zconf.h "$PFX/include/") > "$WORK/zlib.log" 2>&1 \
  || { tail -30 "$WORK/zlib.log"; exit 1; }

# libfdt, static
(cd dtc-1.7.2/libfdt && for c in *.c; do $HOST-gcc -O2 -I. -c "$c"; done \
  && $HOST-ar rcs libfdt.a ./*.o \
  && install -m644 libfdt.a "$PFX/lib/" \
  && install -m644 fdt.h libfdt.h libfdt_env.h "$PFX/include/") > "$WORK/libfdt.log" 2>&1 \
  || { tail -30 "$WORK/libfdt.log"; exit 1; }

# sunxi-tools at the pinned commit
if [ ! -d "$WORK/sunxi-tools/.git" ]; then
  git init -q "$WORK/sunxi-tools"
  git -C "$WORK/sunxi-tools" remote add origin https://github.com/linux-sunxi/sunxi-tools.git
  git -C "$WORK/sunxi-tools" fetch -q --depth 1 origin "$SUNXI_COMMIT"
  git -C "$WORK/sunxi-tools" checkout -q FETCH_HEAD
fi
[ "$(git -C "$WORK/sunxi-tools" rev-parse HEAD)" = "$SUNXI_COMMIT" ] || { echo "STOP: sunxi-tools is not at $SUNXI_COMMIT"; exit 1; }
git -C "$WORK/sunxi-tools" diff --quiet || { echo "STOP: sunxi-tools has local changes"; exit 1; }

cd "$WORK/sunxi-tools"
rm -f sunxi-fel sunxi-fel.exe
make -s OS=Windows_NT CC=$HOST-gcc \
  LIBUSB_CFLAGS="-I$PFX/include/libusb-1.0" LIBUSB_LIBS="$PFX/lib/libusb-1.0.a" \
  ZLIB_CFLAGS="-I$PFX/include" ZLIB_LIBS="$PFX/lib/libz.a" \
  LIBFDT_CFLAGS="-I$PFX/include" LIBFDT_LIBS="$PFX/lib/libfdt.a" \
  LIBS="-lws2_32 -lpthread" LDFLAGS="-static" sunxi-fel > "$WORK/sunxi-fel.log" 2>&1 \
  || { tail -40 "$WORK/sunxi-fel.log"; exit 1; }
[ -f sunxi-fel.exe ] || mv sunxi-fel sunxi-fel.exe

echo "$STUB_SHA  bin/fel-sdboot.sunxi" | sha256sum -c --quiet - || { echo "STOP: stub hash mismatch"; exit 1; }
install -m644 sunxi-fel.exe bin/fel-sdboot.sunxi "$OUT/"
echo "DLL imports:"; $HOST-objdump -p "$OUT/sunxi-fel.exe" | grep 'DLL Name' | sort -u
sha256sum "$OUT/sunxi-fel.exe" "$OUT/fel-sdboot.sunxi"
