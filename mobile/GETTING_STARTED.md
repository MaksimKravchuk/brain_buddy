# Getting Brain Buddy onto your iPhone — from zero

This guide assumes nothing: no developer tools installed, no Apple developer
account (you never need one for this), no terminal experience.

## How this works, in three sentences

**Expo Go** is a free, ordinary app from the App Store that acts as a shell:
it downloads Brain Buddy's code from your computer over Wi-Fi and runs it
inside itself. Your computer is only a local server — nothing is uploaded
anywhere, and nothing is installed on the phone beyond Expo Go itself. An
Apple developer account is only ever needed for a standalone home-screen
app via TestFlight, which is a separate future step.

## One-time setup on your computer (Mac or Windows, ~10 minutes)

### 1. Install Node.js

- Go to <https://nodejs.org> and download the **LTS** version.
- Run the installer, accepting the defaults.
- Check it worked: open **Terminal** (Mac: Cmd+Space, type "Terminal") or
  **PowerShell** (Windows: Start menu, type "PowerShell") and run:

  ```
  node -v
  ```

  You should see `v20` or higher.

### 2. Get the code

Either of these works:

- **With git** (if `git -v` prints a version):

  ```
  git clone https://github.com/MaksimKravchuk/brain_buddy.git
  cd brain_buddy
  git checkout claude/ios-app-development-7a77wm
  ```

  (The `git checkout` line is only needed until the mobile-app pull request
  is merged to `main`.)

- **Without git**: open the repository on github.com, switch the branch
  dropdown (top-left, says `main`) to `claude/ios-app-development-7a77wm`,
  click the green **Code** button → **Download ZIP**, and unzip it
  somewhere easy to find.

### 3. Install the app's dependencies

In your terminal, go into the `mobile` folder inside the repo and install:

```
cd brain_buddy/mobile
npm install
```

This downloads packages for a few minutes. You only do it once (and again
only if the app's dependencies change).

## Every time you want to use the app

1. In the terminal, from the `brain_buddy/mobile` folder:

   ```
   npx expo start
   ```

   After a moment a **QR code** appears in the terminal.

2. On your iPhone (first time only): install **Expo Go** from the App
   Store — search "Expo Go", it's free, made by "650 Industries".

3. Make sure the iPhone is on the **same Wi-Fi network** as the computer.

4. Open the iPhone **Camera** app and point it at the QR code in the
   terminal. Tap the yellow **"Open in Expo Go"** banner.

5. Brain Buddy loads inside Expo Go. Sign in with your normal Brain Buddy
   account — the app talks to your production server by default. The very
   first request can take ~10 seconds while the server wakes from sleep.

To stop, press `Ctrl+C` in the terminal. Expo Go remembers the project
under "Recently opened", but it can only load while `npx expo start` is
running on the computer.

## If the phone won't connect

- **Spinner forever / "could not connect"** — your network is probably
  blocking device-to-device traffic (common on guest, hotel, or office
  Wi-Fi). Use tunnel mode instead, which routes through the internet:

  ```
  npm run start:tunnel
  ```

  The first run asks to install a small tunnel helper — answer yes. Then
  scan the new QR code. Slightly slower, works from anywhere.

- **Windows firewall pop-up** — allow Node.js on **private** networks.

- **The QR won't scan** — in Expo Go, tap "Enter URL manually" and type the
  `exp://…` address printed under the QR code in the terminal.

- **"Voice brain dump" mic is missing** — that feature is gated per
  account; your account needs the `voice_brain_dump` feature flag enabled
  on the server.

## The honest limitation

With this setup the app only works while your computer is serving it. Two
future options make it permanent, in increasing order of effort:

1. **EAS Update** — publish the app's code to Expo's servers (free Expo
   account, still no Apple account). The app then lives in Expo Go on your
   phone permanently, no computer involved.
2. **TestFlight / App Store** — a real standalone "Brain Buddy" icon.
   Requires the Apple Developer Program ($99/year).

Either can be set up later without changing the app.
