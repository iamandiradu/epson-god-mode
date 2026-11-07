# Code signing

Unsigned builds work. Signing only removes the "unknown publisher" warnings.

## Windows

`build_exe.bat` signs `dist\EpsonGodMode.exe` and `dist\egm.exe` automatically when `signing.env.bat`
exists (copy `signing.env.example.bat`). Without it the build stays unsigned.

| Option | Cost | For an individual in Romania? | Notes |
|---|---|---|---|
| **Certum "Open Source Code Signing" (SimplySign cloud)** | from ~€49 | Yes, issued to you as "Open Source Developer" | Certificate appears in the Windows store while SimplySign Desktop is logged in → method A (thumbprint). Signing needs a code from the phone app, so it suits local builds, not unattended CI. |
| **SignPath Foundation** | free for open-source projects | Yes, if the project is public on GitHub | Publisher shown is "SignPath Foundation". Requires an OSI licence (AGPL is), a released, maintained project, and builds from source in CI (`.github/workflows/build.yml` has the step). They review each project. |
| **Azure Artifact Signing** (ex Trusted Signing) | ~$9.99/month | Only through an organisation (EU companies are eligible; individuals: USA/Canada only) | Method C in `sign_windows.ps1`. |
| OV certificate from a CA | ~$150–300/year | Yes | Hardware token or cloud HSM required. |

SmartScreen reputation still builds up over time with any of these; the first downloads may show a
warning even when signed.

## macOS

`build_mac.command` (double-click on a Mac) builds `dist/Epson God Mode.app` and a `.dmg`.

* **Without an Apple Developer account**: the app is ad-hoc signed. It runs on the Mac that built it.
  On other Macs, macOS 15+ blocks it at first: open System Settings → Privacy & Security → *Open Anyway*,
  or run `xattr -dr com.apple.quarantine "/Applications/Epson God Mode.app"`.
* **With the Apple Developer Program** (US$99/year): create a *Developer ID Application* certificate,
  copy `signing.env.example.sh` to `signing.env.sh`, set the identity and a notarytool profile.
  The build then signs with the hardened runtime, notarizes and staples, and the app opens on any Mac
  without warnings.

The GitHub Actions workflow does the same on GitHub's Macs (arm64 and Intel) when the secrets listed
at the top of `.github/workflows/build.yml` are set.
