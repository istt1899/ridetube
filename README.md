# RideTube

> **Fork 0.3.9:** Cyrillic-title and playback-error fixes, plus car-internet diagnosis and a more resilient YouTube sign-in; not yet tested on a car. The application ID is unchanged, so this can upgrade an existing RideTube installation. See [release notes](RELEASE-NOTES-RU.md) and the [technical specification](TECHNICAL-SPEC-RU.md). This fork is based on `25af2acee82d2a1c8140c25870a76f501f878af9`; upstream project and author credits remain below.

> **Fork install:** in MGU Store, refresh the existing `istt1899/ridetube` Releases source with **Settings → Check now**, then update RideTube. The Store installs the matching 0.3.9 service and its declared dependencies. The original installation instructions below refer to the upstream project.

> **Local USB build:** `python kit/tools/build.py jap_ridetube`, `python tools/repack_service.py --base <verified upstream 0.3.8 service tgz>`, then `python tools/release.py`. The repacker changes the service JavaScript and manifest; it checks and reuses the original yt-dlp and decoder binaries byte for byte. The resulting `dist/release/` catalog can be copied to `mgu-repo/ridetube/` on a USB stick with artifact URLs made relative to that folder. Check the Store's Internet status before signing in.

> **Experimental and unofficial.** RideTube is an unofficial client for YouTube. It is not affiliated with,
> endorsed by or sponsored by Google or YouTube. Use it at your own risk. You are responsible for following
> YouTube's Terms of Service and the laws of your country, and for using it safely: by default the picture
> shows only while the car is parked.

RideTube plays videos on the BMW iDrive 7 head unit (MGU), installed from the MGU Store. Everything runs on
the car, over the car's own internet connection:

- **Home**, **Subscriptions** and **Watch later**, once you sign in on the car with the TV device sign-in (a
  code to enter on your phone; RideTube never sees your password).
- Search, channel pages, chapters, the video quality and fill or fit for the picture.
- Skip segments from [SponsorBlock](https://sponsor.ajay.app) (sponsors, self-promotion, intros and similar).
- The sound plays through the car's own media player.
- While driving, the picture is replaced by a podcast view (title, progress, controls) and the sound plays on.
  The picture comes back when the car is parked again.
- Nothing is stored for later. The video playing is downloaded to the head unit in full while it plays, then
  deleted: expect the video's whole size on your data plan, even if you stop early. The download stops if the
  head unit's storage gets low.
- Signed in, what you watch goes to your YouTube history, as on a TV.

## Requirements

- A BMW with iDrive 7 (MGU, `ID7`) and the [MGU Store](https://github.com/robertnisipeanu/mgu-store) installed.
- The car online through the Store's uplink (`mgu-uplink`).
- Installed for you as requirements, so keep their sources in the Store: from the Store's own source, the
  renderer `mgu-render` 0.6.11 or newer, `mgu-deploy` 0.7.0 and `mgu-python` 1.0.2; from the Store's default
  `cauliflowermossgrape/idrive7-apps` source, the controller gate `mgu-inputgate` 1.0.0.

## Install

In the MGU Store, add the source

```
JustAnotherPU/ridetube:releases
```

Add `JustAnotherPU/mgu-apps:releases` too (it is a default source once accepted): it has `jap-node22`, the
Node.js 22 that RideTube's service runs on. Then install RideTube. The Store installs its service
(`jap-ridetube-d`, the player, the yt-dlp fetcher and the video decoder) and, from mgu-apps, `jap-node22` with it.

## Settings

- **Video while driving**: off by default. Leave it off unless the car is coded for video in motion and only
  passengers can see the screen. You use it at your own risk. It takes effect only once switched on while the
  car is parked: pressed while driving, the picture stays off until the next stop.
- **Fill the screen**: off by default (black bars); on, the picture is cropped to fill the screen.
- **Video quality**: auto (720p on Wi-Fi, 480p on phone data), 720p, 480p or 360p.
- **Show members-only videos**: off by default. A channel can also be hidden from its page.
- **SponsorBlock**, per category: skip, show a Skip button, or off.
- **Parked: pause when the 12 V battery is under** 60, 65 (default) or 70 %, or never.
- **Sign in** / **Sign out** in the app's menu.

The parked check reads the car's speed. A reading older than 5 seconds counts as driving.

## Tested on

| | |
|---|---|
| Car | BMW X5 xDrive45e (G05), iDrive 7 (MGU, ID7 HMI), firmware P18_23w44.2-1-3 |
| Internet | the Store's uplink over home Wi-Fi and an iPhone hotspot |

One car only so far. Reports from other cars are welcome in the issues.

## Known limits

- yt-dlp breaks now and then when YouTube changes. A fixed RideTube release then needs a new yt-dlp (see
  `native/jap-ridetube-d/README.md`, "Updating yt-dlp").
- H.264 only (up to 720p, 30 fps preferred), decoded on the head unit's GPU. A video with no H.264 stream
  does not play.
- Signing in uses the TV device sign-in that YouTube's TV apps use. The client id is read from YouTube's TV
  page when you sign in; RideTube ships none.
- The switch from the first seconds of sound to the full file may be heard as a short break.
- Any app installed on the head unit can drive RideTube's service through its control socket (it is open to the
  group every app shares). Install only apps you trust; see `native/jap-ridetube-d/README.md`, "Security notes".

## Uninstall

1. In RideTube, **Sign out** (or later, remove "YouTube on TV" at https://myaccount.google.com/permissions):
   uninstalling deletes the sign-in from the car, but Google keeps the grant until it is revoked.
2. In the MGU Store, uninstall **RideTube**, then its service `jap-ridetube-d`. A bad update can be undone in the
   Store while the previous version is kept.

## Layout

| Path | |
|---|---|
| `apps/jap_ridetube` | the app (Node 8, the iDrive's own app runtime) |
| `kit/` | the idrive7-apps app kit, trimmed to the modules RideTube uses |
| `native/jap-ridetube-d` | the service on the car: player, fetcher, account, search, thumbnails |
| `native/ytdec` | the H.264 decoder that draws into the renderer's video layer |
| `tools/release.py` | lays out the Store catalog (`catalog.json` and its assets) |

## Build and test on a computer

```sh
node kit/tools/test_runtime.js && node kit/tools/test_life.js && node kit/tools/test_parked.js \
  && node kit/tools/test_qr.js
(cd native/jap-ridetube-d && node test/test_network.js && node test/test_account_version.js)
(cd native/jap-ridetube-d && node test/test_ytd.js && node test/test_thumb.js && python3.12 -I test/test_ytfetch.py)
(cd native/ytdec && make test && make target)     # make target needs Docker
```

A release needs an `oap-sdk` folder extracted from a BMW app you own (`node kit/tools/extract_sdk.js
<javascript/app.js of a BMW app>`; never commit it), then:

```sh
python3 kit/tools/build.py jap_ridetube && node kit/tools/test_ridetube.js
export MGU_STORE=<a clone of the MGU Store>
(cd native/jap-ridetube-d && ./build.sh)      # jap-node22 is built in github.com/JustAnotherPU/mgu-apps
python3 tools/release.py      # dist/release/: upload every file to a GitHub release tagged "catalog"
```

The tests need Node 18 or newer, Python 3.12 and ffmpeg.

## License

GPL-3.0-or-later, Copyright (c) 2026 JustAnotherPU ([LICENSE](LICENSE)). Parts come from others under their
own licences (the app kit: MIT; parts of `native/ytdec`: GPL-3.0-or-later; yt-dlp: Unlicense, fetched at
build time; SponsorBlock data: CC BY-NC-SA 4.0): see [THIRD_PARTY_LICENSES](THIRD_PARTY_LICENSES).

## Fork installation repair

The `istt1899/ridetube` Releases catalog includes a pinned `jap-node22` provider from the official `JustAnotherPU/mgu-apps` release. The Store can install the required Node.js runtime from the same source. Refresh the source with Check now, then retry RideTube installation. The runtime does not replace the system Node used by BMW apps. The provider archive checksum was verified before publication.

If the GitHub Releases source does not refresh, use the direct HTTPS catalog: `https://raw.githubusercontent.com/istt1899/ridetube/main/catalog.json`. It lists the same app, service and runtime with the same checked artifact hashes.
