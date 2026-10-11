# Niko Was Here

A deliberately tiny Android app for restored TrekStor tablets. It displays basic
device information and includes a small reader for one selected post from Niko's
blog RSS feed.

## Design

- Classic Android Holo interface
- Java only; no AndroidX or third-party libraries
- Minimum Android version: API 15 (Android 4.0.3)
- Shows the device manufacturer, model, Android version, and build ID
- Fetches a selected article from `https://nikolan.net/blog/index.xml`
- Renders the article using a dark, Holo-style layout with JavaScript disabled
- Opens links in an external browser
- Uses only the `INTERNET` permission; no analytics or data collection
- Uses the project-owned launcher icon in `res/drawable-nodpi/ic_launcher.png`

## Editing

Edit the main screen's named text constants at the top of:

```text
app/src/main/java/de/readerportal/nikowashere/MainActivity.java
```

The reader selects the "fixing-ipads" article on `nikolan.net`.
To change the selected article, edit `ARTICLE_URL` near the top of:

```text
app/src/main/java/de/readerportal/nikowashere/BlogActivity.java
```

The selected URL must match an item in the RSS feed. The reader downloads the
item's full `content:encoded` HTML. It includes loading, failure, and retry
screens and has been tested successfully over HTTPS on Android 4.4.2.

## Build

From PowerShell:

```powershell
.\build.ps1
```

The script builds a debug-signed APK and copies it to:

```text
..\server\assets\apps\niko-was-here.apk
```

The TrekStor server will include it in the next generated `custom.zip`.

To replace an installed copy on a connected tablet:

```powershell
adb install -r .\app\build\outputs\apk\debug\app-debug.apk
```
