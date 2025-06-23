#!/usr/bin/env bash
# Void Linux UEFI Full-Disk-Encryption Installer (Interactive)
# Author: Adapted by ChatGPT
# Description: Install Void Linux with UEFI + LUKS1 + LVM via network repo.

set -euo pipefail
IFS=$'\n\t'

### Helpers ###
log() { echo -e "[\e[32mINFO\e[0m] $*"; }
err() { echo -e "[\e[31mERROR\e[0m] $*" >&2; exit 1; }
prompt() { local _var="$1" _txt="$2" _def="$3"; read -rp "$_txt [$_def]: " _inp; eval "$_var=\"${_inp:-$_def}\""; }

### 0. Update host & install tools ###
update_system() {
  log "Sync & update XBPS on host…"
  xbps-install -Sy
  xbps-install -uy xbps
  log "Install xtools & parted…"
  xbps-install -Sy xtools parted
}

### 1. Prompt hostname & root password ###
get_host_and_pass() {
  prompt hostname "Hostname for new system" "voidlinux"
  while true; do
    read -rsp "Root password: " root_pw; echo
    read -rsp "Confirm root password: " root_pw_confirm; echo
    [[ "$root_pw" == "$root_pw_confirm" ]] && break
    echo "Passwords do not match, try again." >&2
  done
}

### 2. Choose disk ###
select_disk() {
  log "Available disks:"
  lsblk -dpno NAME,SIZE,MODEL | grep -E "/dev/[sv]d|/dev/nvme"
  prompt disk "Disk to install on" "/dev/sda"
  [[ -b "$disk" ]] || err "Disk $disk not found."
}

### 3. Sizes ###
define_sizes() {
  prompt esp_size "EFI size (MiB)" "128"
  prompt root_lv  "Root LV (GiB)"  "10"
  prompt swap_lv  "Swap LV (GiB)"  "2"
}

### 4. Partition ###
partition_disk() {
  log "Partitioning $disk…"
  parted --script "$disk" mklabel gpt
  parted --script "$disk" mkpart ESP fat32 1MiB ${esp_size}MiB
  parted --script "$disk" set 1 esp on
  parted --script "$disk" mkpart primary ext4 ${esp_size}MiB 100%
  esp="${disk}1"
  rawcrypt="${disk}2"
}

### 5. LUKS container ###
setup_luks() {
  log "Encrypting $rawcrypt…"
  cryptsetup luksFormat --type luks1 "$rawcrypt"
  cryptsetup luksOpen      "$rawcrypt" cryptroot
  mappedcrypt="/dev/mapper/cryptroot"
}

### 6. LVM ###
setup_lvm() {
  log "Creating LVM on $mappedcrypt…"
  pvcreate "$mappedcrypt"
  vgcreate voidvg "$mappedcrypt"
  lvcreate -L "${root_lv}G" -n root voidvg
  lvcreate -L "${swap_lv}G" -n swap voidvg
  lvcreate -l 100%FREE      -n home voidvg
}

### 7. Filesystems ###
format_filesystems() {
  log "Formatting filesystems…"
  mkfs.fat -F32 "$esp"
  mkfs.xfs /dev/voidvg/root
  mkfs.xfs /dev/voidvg/home
  mkswap /dev/voidvg/swap && swapon /dev/voidvg/swap
}

### 8. Mount ###
mount_all() {
  log "Mounting…"
  mount /dev/voidvg/root /mnt
  mkdir -p /mnt/{boot/efi,home}
  mount "$esp"           /mnt/boot/efi
  mount /dev/voidvg/home /mnt/home
}

### 9. Copy XBPS keys ###
copy_keys() {
  log "Copy XBPS keys…"
  mkdir -p /mnt/var/db/xbps/keys
  cp -r /var/db/xbps/keys/* /mnt/var/db/xbps/keys/
}

### 10. Install base ###
install_base() {
  log "Installing base-system…"
  xbps-install -Sy -R https://repo-default.voidlinux.org/current -r /mnt \
    base-system cryptsetup lvm2 grub grub-x86_64-efi
}

### 11. fstab ###
make_fstab() {
  log "Generating fstab…"
  xgenfstab /mnt > /mnt/etc/fstab
}

### 12. Initial chroot ###
configure_chroot_initial() {
  log "Chroot initial config…"
  xchroot /mnt /bin/bash -euo pipefail <<EOF
# 1) Hostname & root pw
echo "$hostname" > /etc/hostname
echo "root:$root_pw" | chpasswd

# 2) Locale
echo "LANG=en_US.UTF-8" > /etc/locale.conf
echo "en_US.UTF-8 UTF-8" >> /etc/default/libc-locales
xbps-reconfigure -f glibc-locales

# 3) Enable GRUB cryptodisk in /etc/default/grub
if grep -q '^#GRUB_ENABLE_CRYPTODISK' /etc/default/grub; then
  sed -i 's/^#GRUB_ENABLE_CRYPTODISK.*/GRUB_ENABLE_CRYPTODISK=y/' /etc/default/grub
elif ! grep -q '^GRUB_ENABLE_CRYPTODISK' /etc/default/grub; then
  echo 'GRUB_ENABLE_CRYPTODISK=y' >> /etc/default/grub
fi

# 4) Inject LVM VG & LUKS UUID into the kernel cmdline
UUID=\$(blkid -s UUID -o value $rawcrypt)
sed -i "s|^GRUB_CMDLINE_LINUX_DEFAULT=\"\\(.*\\)\"|GRUB_CMDLINE_LINUX_DEFAULT=\"\\1 rd.lvm.vg=voidvg rd.luks.uuid=\$UUID\"|" /etc/default/grub

# 5) Create & lock down keyfile
dd bs=1 count=64 if=/dev/urandom of=/boot/volume.key
chmod 000 /boot/volume.key
EOF
}
# (follows steps 13–15 unchanged)

### 13. Add LUKS key ###
add_luks_keyfile() {
  log "Adding LUKS key to $rawcrypt…"
  cryptsetup luksAddKey "$rawcrypt" /mnt/boot/volume.key
}

### 14. Final chroot ###
configure_chroot_final() {
  log "Chroot final config…"
  uuid=$(blkid -s UUID -o value "$rawcrypt")
  xchroot /mnt /bin/bash -euo pipefail <<EOF
echo "cryptroot UUID=${uuid} /boot/volume.key luks" > /etc/crypttab
echo 'install_items+=" /boot/volume.key /etc/crypttab "' > /etc/dracut.conf.d/10-crypt.conf
grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=void
xbps-reconfigure -fa
EOF
}

### 15. Cleanup ###
cleanup() {
  log "Cleanup & reboot…"
  umount -R /mnt
  reboot
}

### Main ###
main() {
  update_system
  get_host_and_pass
  select_disk
  define_sizes
  partition_disk
  setup_luks
  setup_lvm
  format_filesystems
  mount_all
  copy_keys
  install_base
  make_fstab
  configure_chroot_initial   # enables GRUB_ENABLE_CRYPTODISK=y & edits CMDLINE :contentReference[oaicite:0]{index=0}
  add_luks_keyfile
  configure_chroot_final
  cleanup
}

main "$@"
