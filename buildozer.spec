[app]
title = mini Brain
package.name = minibrain
package.domain = org.mini
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json
version = 1.0
requirements = python3,kivy==2.3.0,certifi
orientation = portrait
android.permissions = INTERNET
android.api = 31
android.minapi = 24
android.ndk = 25b
android.ndk_api = 24
android.archs = arm64-v8a
android.accept_sdk_license = True
android.allow_backup = True

# Pin p4a to a stable release (same fix used for the mobile app)
p4a.branch = v2024.01.21

[buildozer]
log_level = 2
warn_on_root = 1
