<br>
This is a personal fork focused on playlist automation and reliability for large libraries. It includes liked-songs playlist creation/update, resumable playlist downloads, and safer output handling. Some upstream features may be untested here.


<br>
    <a href="https://github.com/yaronzz/Tidal-Media-Downloader-PRO">[GUI-REPOSITORY (Upstream)]</a>
<br>

![Tidal-Media-Downloader](https://socialify.git.ci/TMLoew/Tidal-Media-Downloader/image?description=1&font=Rokkitt&forks=1&issues=1&language=1&name=1&owner=1&pattern=Circuit%20Board&stargazers=1&theme=Dark)


<div align="center">
  <h1>Tidal-Media-Downloader</h1>
  <a href="https://github.com/TMLoew/Tidal-Media-Downloader/blob/master/LICENSE">
    <img src="https://img.shields.io/github/license/TMLoew/Tidal-Media-Downloader.svg?style=flat-square" alt="">
  </a>
  <a href="https://github.com/TMLoew/Tidal-Media-Downloader/releases">
    <img src="https://img.shields.io/github/v/release/TMLoew/Tidal-Media-Downloader.svg?style=flat-square" alt="">
  </a>
  <a href="https://www.python.org/">
    <img src="https://img.shields.io/github/issues/TMLoew/Tidal-Media-Downloader.svg?style=flat-square" alt="">
  </a>
  <a href="https://github.com/TMLoew/Tidal-Media-Downloader/releases">
    <img src="https://img.shields.io/github/downloads/TMLoew/Tidal-Media-Downloader/total?label=tidal-gui%20download" alt="">
  </a>
  <a href="https://pypi.org/project/tidal-dl/">
    <img src="https://img.shields.io/pypi/dm/tidal-dl?label=tidal-dl%20download" alt="">
  </a>
  <a href="https://github.com/TMLoew/Tidal-Media-Downloader/actions/workflows/build.yml">
    <img src="https://github.com/TMLoew/Tidal-Media-Downloader/actions/workflows/build.yml/badge.svg" alt="">
  </a>
</div>
<p align="center">
  «Tidal-Media-Downloader» is an application that lets you download videos and tracks from Tidal. It supports two version: tidal-dl and tidal-gui. (This fork only contains tidal-dl; GUI notes and docs are upstream.)
    <br>
        <a href="https://github.com/TMLoew/Tidal-Media-Downloader/releases">Download</a> |
        <a href="https://doc.yaronzz.com/post/tidal_dl_installation/">Documentation (Upstream)</a> |
        <a href="https://doc.yaronzz.com/post/tidal_dl_installation_chn/">中文文档 (Upstream)</a> |
    <br>
</p>

## 📺 Installation 

```shell
pip3 install "git+https://github.com/TMLoew/Tidal-Media-Downloader.git"
```

If you want to install local changes from this repo:

```shell
pip3 install -r requirements.txt --user
python3 setup.py install
```

| USE                                                   | FUNCTION                   |
| ----------------------------------------------------- | -------------------------- |
| tidal-dl                                              | Show interactive interface |
| tidal-dl -h                                           | Show help-message          |
| tidal-dl -l "https://tidal.com/browse/track/70973230" | Download link              |
| tidal-dl -g                                           | Show simple-gui            |

If you are using windows system, you can use [tidal-pro (Upstream)](https://github.com/yaronzz/Tidal-Media-Downloader-PRO)

### Nightly Builds

|Download nightly builds from continuous integration: 	| [![Build Status][Build]][Actions] 
|-------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------|

[Actions]: https://github.com/TMLoew/Tidal-Media-Downloader/actions
[Build]: https://github.com/TMLoew/Tidal-Media-Downloader/workflows/Tidal%20Media%20Downloader/badge.svg

## 🤖 Features
- Download album \ track \ video \ playlist \ artist-albums

- Add metadata to songs with automatic FLAC cover-art normalisation *(requires `ffmpeg` and `metaflac` in `PATH`)*

- Selectable video resolution and track quality, including DASH manifests for compatible playback apps

- PKCE login flow support for secure keyless authentication

- Optional listener mode for remote-triggered downloads secured by a shared secret

### Fork additions
- Create a **Liked Songs** playlist from your TIDAL favorites (dated `DD-MM-YYYY`)
- Update an existing **Liked Songs** playlist (select most recent or pick from list)
- Offline **Liked Tracks** sync (download missing, move unliked to `_Removed`)
- Enforced filename format: `Title - Artist.ext` (with collision-safe renames)
- Quality-aware re-downloads (replace lower quality with highest available)
- Per-file quality cache to avoid re-scanning unchanged files
- Flatten liked-tracks folder so all files live in one directory
- Configurable liked-tracks path (defaults to `~/Music/TIDAL/Liked Tracks`)
- Auto-refresh access token on expiry (transparent retry)
- Optional auto-conversion after download (e.g., ALAC/FLAC/WAV/MP3)
- `--startat` CLI flag to resume playlist downloads at a specific track index
- Playlist downloads skip errors and print a summary at the end

## 🔐 Using PKCE credentials

PKCE-based authentication lets you log in without storing the TIDAL device client secret locally. To use it:

1. **Pick a PKCE-capable API key.** Start `tidal-dl`, choose menu option `7` (*Change API Key*), and pick an entry that lists `supportsPkce = True` (the bundled “TV” key is `index 3`). The selected index is stored in `~/.tidal-dl.json` under `apiKeyIndex`, so you can also edit the config file manually if you prefer.
2. *(Optional)* **Override the API credentials.** Menu option `10` (*Configure custom API settings*) lets you supply your own `clientId`, client secret, and PKCE endpoints/scope. The overrides are saved alongside the rest of the user configuration.
3. **Begin the PKCE login flow.** From the main menu choose option `8` (*Login via PKCE*). The CLI prints an authorization URL—open it in your browser and approve access. While you wait for the redirect you can either copy the final URL manually or let an automation post it to the temporary endpoint the CLI exposes (it prints something like `http://127.0.0.1:8123/pkce`, or whichever port you configured for listener mode).
4. **Provide the redirect URL to `tidal-dl`.** Paste it when prompted or POST the JSON payload from the Chrome extension/bridge script to `/pkce`. The downloader exchanges the code for tokens and saves them to `~/.tidal-dl.token.json`. Future sessions reuse the stored refresh token automatically until it expires or you change API keys.

If your current API key does not support PKCE the CLI falls back to the regular device-code login. Switch keys first or edit `apiKeyIndex` to continue using PKCE.

## 💽 User Interface

<img src="https://i.loli.net/2020/08/19/gqW6zHI1SrKlomC.png" alt="image" style="zoom: 50%;" />

![image-20220708105823257](https://s2.loli.net/2022/07/08/vV6HsxugwoDyGr8.png)

![image-20200806013705425](https://i.loli.net/2020/08/06/sPLowIlCGyOdpVN.png)

## 🔊 Listener Mode

The command-line interface exposes a small HTTP listener that mirrors the companion script shared above. Enable it from the interactive settings screen (`tidal-dl` → option `6`) or by editing the config file, then launch it with:

```shell
tidal-dl --listen
```

The listener binds to `127.0.0.1` on port `8123` by default and requires POST requests to `/run` or `/run_sync` to include the `X-Auth` header set to your configured secret. You can change both the port and secret from the settings menu. When a request arrives the downloader attempts the current quality first and retries once at HiFi if the initial download fails.

See [docs/http-endpoints.md](docs/http-endpoints.md) for detailed information on the `/pkce`, `/run`, and `/run_sync` endpoints, including authentication requirements and example payloads.

If your automation already has a valid bearer token you can pass it either as an `Authorization: Bearer <token>` header or in the JSON payload as `{"bearerAuthorization": "<token>"}` and the listener will reuse it for that download, falling back to the stored login afterwards.

Log output is appended to `~/tidal-dl-listener.txt` so you can audit activity initiated via the listener.

## Settings - Possible Tags

### Album

| Tag               | Example value                        |
| ----------------- | ------------------------------------ |
| {ArtistName}      | The Beatles                          |
| {AlbumArtistName} | The Beatles                          |
| {Flag}            | M/A/E  (Master/Dolby Atmos/Explicit) |
| {AlbumID}         | 55163243                             |
| {AlbumYear}       | 1963                                 |
| {AlbumTitle}      | Please Please Me (Remastered)        |
| {AudioQuality}    | LOSSLESS                             |
| {DurationSeconds} | 1919                                 |
| {Duration}        | 31:59                                |
| {NumberOfTracks}  | 14                                   |
| {NumberOfVideos}  | 0                                    |
| {NumberOfVolumes} | 1                                    |
| {ReleaseDate}     | 1963-03-22                           |
| {RecordType}      | ALBUM                                |
| {None}            |                                      |

### Track

| Tag               | Example Value                              |
| ----------------- | ------------------------------------------ |
| {TrackNumber}     | 01                                         |
| {ArtistName}      | The Beatles                                |
| {ArtistsName}     | The Beatles                                |
| {TrackTitle}      | I Saw Her Standing There (Remastered 2009) |
| {ExplicitFlag}    | (*Explicit*)                               |
| {AlbumYear}       | 1963                                       |
| {AlbumTitle}      | Please Please Me (Remastered)              |
| {AudioQuality}    | LOSSLESS                                   |
| {DurationSeconds} | 173                                        |
| {Duration}        | 02:53                                      |
| {TrackID}         | 55163244                                   |

### Video

| Tag               | Example Value                              |
| ----------------- | ------------------------------------------ |
| {VideoNumber}     | 00                                         |
| {ArtistName}      | DMX                                        |
| {ArtistsName}     | DMX, Westside Gunn                         |
| {VideoTitle}      | Hood Blues                                 |
| {ExplicitFlag}    | (*Explicit*)                               |
| {VideoYear}       | 2021                                       |
| {TrackID}         | 188932980                                  |

## ☕ Support (Original Author)

If you really like the original project and want to support its author, you can buy them a coffee and star their repository.

<a href="https://www.buymeacoffee.com/yaronzz" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/arial-orange.png" alt="Buy Me A Coffee" style="height: 51px !important;width: 217px !important;" ></a>

## 🎂 Contributors
This project exists thanks to all the people who contribute. 

<a href="https://github.com/TMLoew/Tidal-Media-Downloader/graphs/contributors"><img src="https://contributors-img.web.app/image?repo=TMLoew/Tidal-Media-Downloader" /></a>

## 🎨 Libraries and reference

- [aigpy](https://github.com/yaronzz/AIGPY)
- [python-tidal](https://github.com/tamland/python-tidal)
- [python-tidal (EbbLabs fork)](https://github.com/EbbLabs/python-tidal)
- [redsea](https://github.com/redsudo/RedSea)
- [tidal-wiki](https://github.com/Fokka-Engineering/TIDAL/wiki)

## 📜 Disclaimer
- Private use only.
- Need a Tidal-HIFI subscription. 
- You should not use this method to distribute or pirate music.
- It may be illegal to use this in your country, so be informed.

## Developing

```shell
pip3 uninstall tidal-dl
pip3 install -r requirements.txt --user
python3 setup.py install
```

