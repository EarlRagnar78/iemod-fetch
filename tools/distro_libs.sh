#!/bin/sh
# The system libraries the wizard's Linux bundle needs on one distribution,
# measured inside it (GUI-AUDIT item "the bundles start on the target
# distros", ADR-0056). Run as root inside a fresh container of the distro:
#
#   distro_libs.sh BUNDLE_DIR [CLI_DIR]
#
# BUNDLE_DIR holds iemod-fetch-gui/ (the unzipped wizard zip); CLI_DIR holds
# iemod-fetch/ (the unzipped command-line zip). Nothing is guessed from a
# list: each library the bundle's Qt links to and the system lacks is read
# with ldd, the package that ships it is asked of the distro's own package
# index, installed, and the wizard is then started offscreen. Lines:
#
#   MISSING <set> <soname>      before anything is installed
#   PACKAGE <set> <soname> <package>
#   STILL   <set> <soname>      after the packages (should be none)
#   CHECK   <before|after> <ok|failed>
#   CLI     <ok|failed>
#
# Sets: offscreen (what `--check` and a headless start need), xcb (an X11 or
# XWayland desktop), wayland (a native Wayland session; Qt falls back to xcb).
set -u
BUNDLE=$1/iemod-fetch-gui
CLI=${2:-}
QT=$BUNDLE/_internal/PySide6/Qt
. /etc/os-release
FAMILY=${ID_LIKE:-$ID}
case " $ID $FAMILY " in
  *" debian "*|*" ubuntu "*) PM=apt ;;
  *" fedora "*|*" rhel "*) PM=dnf ;;
  *" arch "*) PM=pacman ;;
  *) echo "UNKNOWN $ID"; exit 2 ;;
esac
echo "DISTRO $PRETTY_NAME ($PM)"

prepare() {
  case $PM in
    apt) export DEBIAN_FRONTEND=noninteractive
         apt-get update -q >/dev/null && apt-get install -y -q apt-file >/dev/null \
           && apt-file update >/dev/null ;;
    dnf) dnf -q makecache >/dev/null
         command -v ldd >/dev/null || dnf -q install -y /usr/bin/ldd >/dev/null ;;
    pacman) { pacman-key --init && pacman-key --populate archlinux; } >/dev/null 2>&1
            # -Syu, not -Sy: installing after a bare -Sy is a partial upgrade
            pacman -Syu --noconfirm >/dev/null && pacman -Fy --noconfirm >/dev/null ;;
  esac
}

# the package that ships $1 (a soname), as the distro's index says
package_of() {
  case $PM in
    apt) apt-file find -x "/(usr/)?lib/x86_64-linux-gnu/$1\$" 2>/dev/null \
           | cut -d: -f1 | sort -u | head -1 ;;
    dnf) dnf -q repoquery --arch x86_64,noarch --qf '%{name}\n' \
           --whatprovides "/usr/lib64/$1" 2>/dev/null | sort -u | head -1 ;;
    pacman) pacman -Fq "usr/lib/$1" 2>/dev/null | head -1 | sed 's|.*/||' ;;
  esac
}

install() {
  [ $# -gt 0 ] || return 0
  case $PM in
    apt) apt-get install -y -q --no-install-recommends "$@" >/dev/null ;;
    dnf) dnf -q install -y "$@" >/dev/null ;;
    pacman) pacman -S --noconfirm --needed "$@" >/dev/null ;;
  esac
}

files_of() {
  case $1 in
    offscreen) echo "$BUNDLE/iemod-fetch-gui $QT/plugins/platforms/libqoffscreen.so" \
                    "$QT/lib/libQt6Core.so.6 $QT/lib/libQt6Gui.so.6" \
                    "$QT/lib/libQt6Widgets.so.6 $QT/lib/libQt6DBus.so.6" ;;
    xcb) echo "$QT/plugins/platforms/libqxcb.so $QT/lib/libQt6XcbQpa.so.6" ;;
    wayland) echo "$QT/plugins/platforms/libqwayland.so" ;;
  esac
}

missing() {     # the sonames the set's files link to and the system lacks
  for f in $(files_of "$1"); do
    [ -e "$f" ] && ldd "$f" 2>/dev/null | awk '/not found/ {print $1}'
  done | sort -u
}

check() {
  mkdir -p /tmp/project
  if QT_QPA_PLATFORM=offscreen "$BUNDLE/iemod-fetch-gui" --check --project /tmp/project \
       >/tmp/check.log 2>&1; then echo "CHECK $1 ok"; else
    echo "CHECK $1 failed"; sed 's/^/  | /' /tmp/check.log | tail -15; fi
}

if [ -n "$CLI" ]; then
  if "$CLI/iemod-fetch/iemod-fetch" --version && "$CLI/iemod-fetch/iemod-fetch" --help >/dev/null
  then echo "CLI ok"; else echo "CLI failed"; fi
fi
check before
prepare || { echo "PREPARE failed"; exit 1; }
for set in offscreen xcb wayland; do
  wanted=""
  for so in $(missing $set); do
    echo "MISSING $set $so"
    pkg=$(package_of "$so")
    echo "PACKAGE $set $so ${pkg:-?}"
    [ -n "$pkg" ] && wanted="$wanted $pkg"
  done
  # shellcheck disable=SC2086
  install $(echo $wanted | tr ' ' '\n' | sort -u) || echo "INSTALL $set failed:$wanted"
  for so in $(missing $set); do echo "STILL $set $so"; done
  if [ "$set" = offscreen ]; then check after; fi
done
exit 0      # the verdict is in the lines; 1 and 2 are PREPARE and UNKNOWN
