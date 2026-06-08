[app]

title = Vibrate Me
package.name = vibrateme
package.domain = org.naeem
version = 0.1

source.dir = .
source.include_exts = py,png,jpg,kv,atlas

icon.filename = icon.png

requirements = python3,kivy,plyer,numpy,scipy,matplotlib

orientation = portrait

android.permissions = BODY_SENSORS,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE

android.api = 35
android.build_tools_version = 35.0.0
android.minapi = 24
android.accept_sdk_license = True

fullscreen = 0
