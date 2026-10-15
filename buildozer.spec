[app]
title = mini Brain
package.name = minibrain
package.domain = org.mini
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json
version = 1.0
requirements = python3,kivy==2.3.0,pyjnius,android,certifi
orientation = portrait
android.permissions = INTERNET, FOREGROUND_SERVICE, FOREGROUND_SERVICE_DATA_SYNC, POST_NOTIFICATIONS
android.api = 31
android.minapi = 24
android.ndk = 25b
android.ndk_api = 24
android.archs = arm64-v8a
android.accept_sdk_license = True
android.allow_backup = True
android.extra_manifest_application_arguments = ./extra_manifest_application.xml

# Hand-written Java foreground service (see src/org/mini/minibrain/TabletService.java)
# that keeps this app's process - and its Python HTTP server thread - alive
# in the background, with a persistent notification.
android.add_src = src

# Pin p4a to a stable release (same fix used for the mobile app)
p4a.branch = v2024.01.21

[buildozer]
log_level = 2
warn_on_root = 1
