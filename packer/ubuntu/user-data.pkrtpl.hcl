#cloud-config
# autoinstall answers for the Ubuntu template build (ubuntu.pkr.hcl). The installer reads them from
# the "cidata" CD. The build user only exists until clean.sh deletes it.
autoinstall:
  version: 1
  locale: en_US.UTF-8
  keyboard:
    layout: us
  identity:
    hostname: tpl-ubuntu
    username: builder
    # A random password nobody knows: the build signs in with its key.
    password: "${bcrypt(uuidv4())}"
  ssh:
    install-server: true
    allow-pw: false
    authorized-keys:
      - "${ssh_public_key}"
  storage:
    layout:
      name: lvm
%{ if sizing_all ~}
      sizing-policy: all
%{ endif ~}
%{ if apt_mirror != "" ~}
  apt:
    geoip: false
    primary:
      - arches: [default]
        uri: "${apt_mirror}"
%{ endif ~}
  late-commands:
    - "echo 'builder ALL=(ALL) NOPASSWD:ALL' > /target/etc/sudoers.d/builder"
    - "chmod 440 /target/etc/sudoers.d/builder"
