#!/usr/bin/env python
# -*- encoding: utf-8 -*-
'''
@File    :   __init__.py
@Time    :   2020/11/08
@Author  :   Yaronzz
@Version :   3.0
@Contact :   yaronhuang@foxmail.com
@Desc    :
'''
import sys
import getopt
import os
import shutil
import re
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set

import aigpy
from mutagen import File as MutagenFile
from mutagen import MutagenError
from .paths import __fixPath__, getTrackPath
from functools import wraps
from datetime import datetime

if __package__ in (None, "", "__main__"):
    from pathlib import Path
    import importlib.util

    _module_path = Path(__file__).resolve().parent
    sys.path.insert(0, str(_module_path))
    sys.path.insert(0, str(_module_path.parent))
    # When the application is frozen with PyInstaller the temporary
    # extraction directory is named ``_MEIxxxxx``.  If we blindly use that
    # directory name as ``__package__`` then relative imports such as
    # ``from .metadata_refresh`` try to resolve against the temporary
    # directory instead of the actual ``tidal_dl`` package.  Explicitly set
    # the expected package name to ensure the relative imports keep working
    # both for source runs and frozen executables.
    __package__ = "tidal_dl"

    # Register the currently executing module as the ``tidal_dl`` package so
    # that subsequent relative imports do not try to locate a separate
    # top-level package when running from a frozen executable.  PyInstaller
    # executes ``__init__`` as ``__main__`` which means the package is not
    # automatically available in ``sys.modules``.  By exposing the module (and
    # the package search path) explicitly we keep the import machinery focused
    # on the extracted package contents bundled with the executable.
    module = sys.modules.setdefault(__package__, sys.modules[__name__])
    search_locations = list(getattr(module, "__path__", []))
    if __spec__ is not None and getattr(__spec__, "submodule_search_locations", None):
        search_locations.extend(str(entry) for entry in __spec__.submodule_search_locations)
    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", "")).joinpath("tidal_dl")
        search_locations.append(str(meipass))
    else:
        search_locations.append(str(_module_path))
    module.__path__ = list(dict.fromkeys(search_locations))
    if __spec__ is None:
        __spec__ = importlib.util.spec_from_loader(
            __package__, loader=None, origin=str(_module_path / "__init__.py"), is_package=True
        )

# Importing ``tidal_dl.metadata_refresh`` using an absolute name ensures that
# PyInstaller can discover the module when it analyses ``__init__`` as the
# entry-point script.  Relying purely on a relative import caused the module to
# be omitted from the frozen bundle which then crashed at runtime when the
# metadata refresh CLI flag was used.
from tidal_dl.metadata_refresh import refresh_metadata_for_directory

from .events import *
from .listener import start_listener
from .settings import *
from .paths import getProfilePath, getTokenPath
from .gui import startGui
from .printf import Printf


def _ensure_api_key_configured(interactive: bool) -> bool:
    """Ensure a usable API key (or custom override) is available.

    When running interactively we only warn so the user can configure
    custom settings first. Non-interactive invocations return False to
    signal that execution should stop until configuration is provided.
    """

    if SETTINGS.has_custom_api_settings() or apiKey.isItemValid(SETTINGS.apiKeyIndex):
        return True

    if interactive:
        Printf.info(
            "No bundled API key selected. Use option 7 to choose one or option 10 to configure custom API settings."
        )
    else:
        Printf.err(
            "No valid API key configured. Select a bundled key or configure custom API settings before proceeding."
        )
    return False


def _login_if_needed():
    if not loginByConfig():
        if apiSupportsPkce():
            loginByPkce()
        else:
            loginByWeb()




def create_playlist_from_liked_tracks():
    if not _ensure_api_key_configured(interactive=True):
        return
    _login_if_needed()

    liked_tracks = TIDAL_API.getFavoriteTracks()
    if not liked_tracks:
        Printf.err("No liked tracks found.")
        return

    today = datetime.now().strftime("%d-%m-%Y")
    title = f"Liked Songs {today}"
    description = f"Auto-generated from liked tracks on {today}"
    playlist = TIDAL_API.createPlaylist(title, description)
    if not playlist or not getattr(playlist, 'uuid', None):
        Printf.err("Failed to create playlist.")
        return

    track_ids = [str(track.id) for track in liked_tracks if getattr(track, 'id', None)]
    TIDAL_API.addTracksToPlaylist(playlist.uuid, track_ids)
    Printf.success(f"Created playlist '{title}' with {len(track_ids)} tracks.")

def _get_liked_songs_playlists():
    playlists = TIDAL_API.getPlaylistSelf()
    liked_playlists = []
    for playlist in playlists:
        title = (playlist.title or "").strip()
        if not title.startswith("Liked Songs "):
            continue
        date_str = title.replace("Liked Songs ", "", 1).strip()
        try:
            parsed = datetime.strptime(date_str, "%d-%m-%Y")
        except ValueError:
            parsed = None
        liked_playlists.append((parsed, playlist))
    liked_playlists.sort(key=lambda item: item[0] or datetime.min, reverse=True)
    return liked_playlists


def update_playlist_from_liked_tracks():
    if not _ensure_api_key_configured(interactive=True):
        return
    _login_if_needed()

    liked_tracks = TIDAL_API.getFavoriteTracks()
    if not liked_tracks:
        Printf.err("No liked tracks found.")
        return

    liked_playlists = _get_liked_songs_playlists()
    if not liked_playlists:
        Printf.err("No existing 'Liked Songs' playlists found.")
        return

    Printf.info("Select a playlist to update (press Enter for most recent):")
    for idx, (_, playlist) in enumerate(liked_playlists, start=1):
        Printf.info(f"{idx}) {playlist.title} [{playlist.uuid}]")

    choice = input("").strip()
    if choice == "":
        target = liked_playlists[0][1]
    else:
        try:
            index = int(choice) - 1
            target = liked_playlists[index][1]
        except Exception:
            Printf.err("Invalid selection.")
            return

    Printf.info(f"Updating playlist '{target.title}'...")
    TIDAL_API.clearPlaylist(target.uuid)

    track_ids = [str(track.id) for track in liked_tracks if getattr(track, 'id', None)]
    TIDAL_API.addTracksToPlaylist(target.uuid, track_ids)
    Printf.success(f"Updated playlist '{target.title}' with {len(track_ids)} tracks.")

def _get_local_liked_track_ids(base_dir: Path):
    supported_exts = {".flac", ".m4a", ".mp4", ".aac", ".alac", ".mp3", ".wav"}
    track_map: Dict[str, List[Path]] = {}

    for path in base_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in supported_exts:
            continue
        try:
            audio = MutagenFile(path)
        except MutagenError:
            continue
        if audio is None or not hasattr(audio, "tags") or audio.tags is None:
            continue
        tags = {str(k).upper(): v for k, v in audio.tags.items()}
        track_id_values = tags.get("TIDAL_TRACK_ID")
        if not track_id_values:
            continue
        track_id = str(track_id_values[0]).strip()
        if not track_id:
            continue
        track_map.setdefault(track_id, []).append(path)

    return track_map


def _ensure_title_artist_filenames(base_dir: Path):
    supported_exts = {".flac", ".m4a", ".mp4", ".aac", ".alac", ".mp3", ".wav"}

    def infer_from_filename(stem: str):
        parts = re.split(r"\s*-\s*", stem, maxsplit=1)
        if len(parts) != 2:
            return None
        artist_raw, title_raw = (p.strip() for p in parts)
        if not artist_raw or not title_raw:
            return None
        artist = __fixPath__(artist_raw)
        title = __fixPath__(title_raw)
        if not artist or not title:
            return None
        return artist, title

    def unique_path(path: Path) -> Path:
        if not path.exists():
            return path
        stem = path.stem
        suffix = path.suffix
        parent = path.parent
        idx = 2
        while True:
            candidate = parent / f"{stem} ({idx}){suffix}"
            if not candidate.exists():
                return candidate
            idx += 1

    renamed = 0
    skipped = 0
    collisions = 0
    inferred = 0
    skipped_no_pattern = 0

    for path in base_dir.rglob("*"):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.suffix.lower() not in supported_exts:
            continue
        title = ""
        artist = ""
        try:
            audio = MutagenFile(path)
            if audio is not None and getattr(audio, "tags", None):
                tags = {str(k).lower(): v for k, v in audio.tags.items()}
                title = __fixPath__((tags.get("title", [""])[0] or "").strip())
                artist = __fixPath__(((tags.get("artist", [""])[0] or "").split(",")[0].strip()))
        except MutagenError:
            audio = None

        if not title or not artist:
            inferred_parts = infer_from_filename(path.stem)
            if not inferred_parts:
                skipped += 1
                skipped_no_pattern += 1
                continue
            artist, title = inferred_parts
            inferred += 1

        new_name = f"{title} - {artist}{path.suffix}"
        dest = path.with_name(new_name)
        if dest == path:
            skipped += 1
            continue
        if dest.exists():
            dest = unique_path(dest)
            collisions += 1
        try:
            path.rename(dest)
            renamed += 1
        except Exception:
            skipped += 1

    Printf.info(f"Renamed {renamed} file(s) to 'Title - Artist' format.")
    if inferred:
        Printf.info(f"Renamed {inferred} file(s) using filename inference.")
    if collisions:
        Printf.info(f"Resolved {collisions} filename collisions.")
    if skipped:
        Printf.info(f"Skipped {skipped} file(s) without usable tags.")
    if skipped_no_pattern:
        Printf.info(f"Skipped {skipped_no_pattern} file(s) without a usable delimiter pattern.")


def _flatten_liked_tracks_folder(base_dir: Path, removed_dir: Path) -> int:
    supported_exts = {".flac", ".m4a", ".mp4", ".aac", ".alac", ".mp3", ".wav"}

    def unique_path(path: Path) -> Path:
        if not path.exists():
            return path
        stem = path.stem
        suffix = path.suffix
        parent = path.parent
        idx = 2
        while True:
            candidate = parent / f"{stem} ({idx}){suffix}"
            if not candidate.exists():
                return candidate
            idx += 1

    moved = 0
    for path in base_dir.rglob("*"):
        if not path.is_file() or path.name.startswith("."):
            continue
        if removed_dir in path.parents:
            continue
        if path.suffix.lower() not in supported_exts:
            continue
        if path.parent == base_dir:
            continue
        dest = unique_path(base_dir / path.name)
        try:
            shutil.move(str(path), str(dest))
            moved += 1
        except Exception:
            continue

    for folder in sorted([p for p in base_dir.rglob("*") if p.is_dir()], reverse=True):
        if folder == removed_dir:
            continue
        try:
            if not any(folder.iterdir()):
                folder.rmdir()
        except Exception:
            continue

    if moved:
        Printf.info(f"Moved {moved} file(s) into the liked tracks root folder.")
    return moved


def _quality_rank(value: str) -> int:
    ranking = {
        "LOW": 0,
        "HIGH": 1,
        "LOSSLESS": 2,
        "HI_RES": 3,
        "HI_RES_LOSSLESS": 4,
    }
    return ranking.get(value.upper(), -1)


def _desired_quality_rank() -> int:
    if SETTINGS.audioQuality == AudioQuality.Normal:
        return _quality_rank("LOW")
    if SETTINGS.audioQuality == AudioQuality.High:
        return _quality_rank("HIGH")
    if SETTINGS.audioQuality == AudioQuality.HiFi:
        return _quality_rank("LOSSLESS")
    if SETTINGS.audioQuality == AudioQuality.Master:
        return _quality_rank("HI_RES")
    if SETTINGS.audioQuality == AudioQuality.Max:
        return _quality_rank("HI_RES_LOSSLESS")
    return _quality_rank("LOW")


def _get_local_stream_quality(path: Path) -> str:
    try:
        audio = MutagenFile(path)
    except MutagenError:
        return ""
    if audio is None or not getattr(audio, "tags", None):
        return ""
    tags = {str(k).upper(): v for k, v in audio.tags.items()}
    stream_quality = tags.get("TIDAL_STREAM_SOUND_QUALITY")
    if stream_quality and stream_quality[0]:
        return str(stream_quality[0]).strip()
    audio_quality = tags.get("TIDAL_AUDIO_QUALITY")
    if audio_quality and audio_quality[0]:
        return str(audio_quality[0]).strip()
    return ""


def _load_quality_cache(cache_path: Path) -> dict:
    if not cache_path.exists():
        return {}
    try:
        with cache_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {}


def _save_quality_cache(cache_path: Path, cache: dict) -> None:
    tmp_path = cache_path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(cache, handle, ensure_ascii=True, indent=2)
    tmp_path.replace(cache_path)


def sync_offline_liked_tracks():
    if not _ensure_api_key_configured(interactive=True):
        return
    _login_if_needed()

    base_dir = Path(SETTINGS.likedTracksPath or os.path.expanduser("~/Music/TIDAL/Liked Tracks"))
    base_dir.mkdir(parents=True, exist_ok=True)
    removed_dir = base_dir / "_Removed"
    removed_dir.mkdir(parents=True, exist_ok=True)

    liked_tracks = TIDAL_API.getFavoriteTracks()
    liked_track_map = {
        str(track.id): track for track in liked_tracks if getattr(track, "id", None)
    }
    liked_ids: Set[str] = set(liked_track_map.keys())

    local_track_map = _get_local_liked_track_ids(base_dir)
    local_ids = set(local_track_map.keys())

    missing_ids = liked_ids - local_ids
    removed_ids = local_ids - liked_ids

    Printf.info(f"Found {len(local_ids)} local liked tracks.")
    Printf.info(f"Missing {len(missing_ids)} tracks to download.")
    Printf.info(f"{len(removed_ids)} tracks no longer liked will be moved.")

    original_download_path = SETTINGS.downloadPath
    original_use_playlist = SETTINGS.usePlaylistFolder
    original_check_exist = SETTINGS.checkExist
    SETTINGS.downloadPath = str(base_dir)
    SETTINGS.usePlaylistFolder = False

    errors = []
    for track_id in missing_ids:
        try:
            track = TIDAL_API.getTrack(track_id)
            album = TIDAL_API.getAlbum(track.album.id)
            ok, err, _ = downloadTrack(track, album, None, base_override=str(base_dir))
            if not ok:
                errors.append(
                    {
                        "track_id": track_id,
                        "title": getattr(track, "title", ""),
                        "artist": getattr(getattr(track, "artist", None), "name", ""),
                        "error": err or "Unknown download error",
                    }
                )
        except Exception as exc:
            liked_track = liked_track_map.get(str(track_id))
            errors.append(
                {
                    "track_id": track_id,
                    "title": getattr(liked_track, "title", ""),
                    "artist": getattr(getattr(liked_track, "artist", None), "name", ""),
                    "error": str(exc),
                }
            )

    for track_id in removed_ids:
        for path in local_track_map.get(track_id, []):
            if removed_dir in path.parents:
                continue
            rel = path.relative_to(base_dir)
            target = removed_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(str(path), str(target))
            except Exception as exc:
                errors.append(
                    {
                        "track_id": track_id,
                        "title": "",
                        "artist": "",
                        "error": f"Move failed: {exc}",
                    }
                )

    desired_rank = _desired_quality_rank()
    upgrade_candidates = []
    skipped_quality = 0
    unavailable_quality = 0

    cache_path = base_dir / "_quality_cache.json"
    quality_cache = _load_quality_cache(cache_path)

    for track_id, paths in local_track_map.items():
        if track_id in removed_ids:
            continue
        local_paths = [p for p in paths if removed_dir not in p.parents]
        if not local_paths:
            continue
        best_rank = -1
        for path in local_paths:
            stat = path.stat()
            cache_key = str(path)
            cache_entry = quality_cache.get(cache_key)
            if (
                cache_entry
                and cache_entry.get("mtime") == stat.st_mtime
                and cache_entry.get("size") == stat.st_size
            ):
                local_quality = cache_entry.get("quality", "")
            else:
                local_quality = _get_local_stream_quality(path)
                quality_cache[cache_key] = {
                    "mtime": stat.st_mtime,
                    "size": stat.st_size,
                    "quality": local_quality,
                }
                _save_quality_cache(cache_path, quality_cache)
            if not local_quality:
                continue
            best_rank = max(best_rank, _quality_rank(local_quality))
        if best_rank < 0:
            skipped_quality += 1
            continue
        if best_rank < desired_rank:
            upgrade_candidates.append((track_id, local_paths, best_rank))

    if upgrade_candidates:
        Printf.info(f"Upgrading {len(upgrade_candidates)} track(s) to {SETTINGS.audioQuality.name}.")
        SETTINGS.checkExist = False
        for track_id, local_paths, current_rank in upgrade_candidates:
            try:
                track = TIDAL_API.getTrack(track_id)
                album = TIDAL_API.getAlbum(track.album.id)
                stream = TIDAL_API.getStreamUrl(track.id, SETTINGS.audioQuality)
                stream_rank = _quality_rank(str(getattr(stream, "soundQuality", "")))
                if stream_rank <= current_rank:
                    unavailable_quality += 1
                    continue
                target_path = Path(getTrackPath(track, stream, album, None))
                ok, err, _ = downloadTrack(track, album, None, base_override=str(base_dir))
                if not ok:
                    errors.append(
                        {
                            "track_id": track_id,
                            "title": getattr(track, "title", ""),
                            "artist": getattr(getattr(track, "artist", None), "name", ""),
                            "error": f"Upgrade failed: {err or 'Unknown download error'}",
                        }
                    )
                    continue
                for old_path in local_paths:
                    if old_path.resolve() == target_path.resolve():
                        continue
                    try:
                        if old_path.exists():
                            old_path.unlink()
                    except Exception as exc:
                        errors.append(
                            {
                                "track_id": track_id,
                                "title": getattr(track, "title", ""),
                                "artist": getattr(getattr(track, "artist", None), "name", ""),
                                "error": f"Cleanup failed: {exc}",
                            }
                        )
            except Exception as exc:
                errors.append(
                    {
                        "track_id": track_id,
                        "title": "",
                        "artist": "",
                        "error": f"Upgrade failed: {exc}",
                    }
                )
        SETTINGS.checkExist = original_check_exist

    _flatten_liked_tracks_folder(base_dir, removed_dir)
    _ensure_title_artist_filenames(base_dir)
    _ensure_title_artist_filenames(removed_dir)
    _save_quality_cache(cache_path, quality_cache)

    SETTINGS.downloadPath = original_download_path
    SETTINGS.usePlaylistFolder = original_use_playlist
    SETTINGS.checkExist = original_check_exist

    if errors:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        log_path = base_dir / f"_sync_errors_{timestamp}.txt"
        with log_path.open("w", encoding="utf-8") as handle:
            handle.write("track_id | title | artist | error\n")
            for entry in errors:
                handle.write(
                    f"{entry.get('track_id','-')} | "
                    f"{entry.get('title','-') or '-'} | "
                    f"{entry.get('artist','-') or '-'} | "
                    f"{entry.get('error','-') or '-'}\n"
                )
        Printf.info("Sync errors summary:")
        for entry in errors:
            Printf.err(f"{entry.get('track_id')}: {entry.get('error')}")
        Printf.info(f"Wrote sync error log to: {log_path}")
    if skipped_quality:
        Printf.info(f"Skipped quality check for {skipped_quality} track(s) without stream quality tags.")
    if unavailable_quality:
        Printf.info(f"{unavailable_quality} track(s) were already at the highest available quality.")
    else:
        Printf.success("Offline liked tracks are in sync.")


def require_api_ready(*, interactive: bool, perform_login: bool = True):
    """Decorator ensuring an API key (or overrides) exists before proceeding."""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not _ensure_api_key_configured(interactive=interactive):
                return
            if perform_login:
                _login_if_needed()
            return func(*args, **kwargs)

        return wrapper

    return decorator


@require_api_ready(interactive=False)
def _perform_metadata_refresh(refresh_path: str):
    refresh_metadata_for_directory(refresh_path)


@require_api_ready(interactive=False)
def _start_download(link: str):
    Printf.info(LANG.select.SETTING_DOWNLOAD_PATH + ':' + SETTINGS.downloadPath)
    start(link)


def mainCommand():
    try:
        opts, args = getopt.getopt(
            sys.argv[1:],
            "hvgl:o:q:r:s:",
            [
                "help",
                "version",
                "gui",
                "link=",
                "output=",
                "quality",
                "resolution",
                "startat=",
                "listen",
                "refresh-metadata=",
            ],
        )
    except getopt.GetoptError as errmsg:
        Printf.err(vars(errmsg)['msg'] + ". Use 'tidal-dl -h' for usage.")
        return

    link = None
    showGui = False
    refresh_path = None

    for opt, val in opts:
        if opt in ('-h', '--help'):
            Printf.usage()
            return
        if opt in ('-v', '--version'):
            Printf.logo()
            return
        if opt in ('-g', '--gui'):
            showGui = True
            continue
        if opt == '--listen':
            start_listener()
            return
        if opt == '--refresh-metadata':
            refresh_path = val
            continue
        if opt in ('-l', '--link'):
            link = val
            continue
        if opt in ('-o', '--output'):
            SETTINGS.downloadPath = val
            SETTINGS.save()
            continue
        if opt in ('-q', '--quality'):
            SETTINGS.audioQuality = SETTINGS.getAudioQuality(val)
            SETTINGS.save()
            continue
        if opt in ('-r', '--resolution'):
            SETTINGS.videoQuality = SETTINGS.getVideoQuality(val)
            SETTINGS.save()
            continue
        if opt in ('-s', '--startat'):
            try:
                SETTINGS.downloadStartIndex = max(1, int(val))
            except ValueError:
                Printf.err("Invalid --startat value; expected an integer >= 1.")
                return
            continue

    if refresh_path is not None:
        if showGui:
            Printf.err("Metadata refresh is not available in GUI mode.")
            return
        if link is not None:
            Printf.err("Please provide either a link or --refresh-metadata, not both.")
            return
        _perform_metadata_refresh(refresh_path)
        return

    if not aigpy.path.mkdirs(SETTINGS.downloadPath):
        Printf.err(LANG.select.MSG_PATH_ERR + SETTINGS.downloadPath)
        return

    if showGui:
        startGui()
        return

    if link is not None:
        _start_download(link)

def main():
    SETTINGS.read(getProfilePath())
    TOKEN.read(getTokenPath())
    updateActiveApiKey()

    if len(sys.argv) > 1:
        mainCommand()
        return

    Printf.logo()
    Printf.settings()

    if _ensure_api_key_configured(interactive=True):
        _login_if_needed()

    Printf.checkVersion()

    while True:
        Printf.choices()
        choice = Printf.enter(LANG.select.PRINT_ENTER_CHOICE)
        if choice == "0":
            return
        elif choice == "1":
            if not _ensure_api_key_configured(interactive=True):
                continue
            if not loginByConfig():
                if apiSupportsPkce():
                    loginByPkce()
                else:
                    loginByWeb()
        elif choice == "2":
            if not _ensure_api_key_configured(interactive=True):
                continue
            if apiSupportsPkce():
                loginByPkce()
            else:
                loginByWeb()
        elif choice == "3":
            if not _ensure_api_key_configured(interactive=True):
                continue
            loginByAccessToken()
        elif choice == "4":
            changePathSettings()
        elif choice == "5":
            changeQualitySettings()
        elif choice == "6":
            changeSettings()
        elif choice == "7":
            if changeApiKey():
                if apiSupportsPkce():
                    loginByPkce()
                else:
                    loginByWeb()
        elif choice == "8":
            if not _ensure_api_key_configured(interactive=True):
                continue
            loginByPkce()
        elif choice == "9":
            start_listener()
        elif choice == "10":
            configureCustomApiSettings()
        elif choice == "11":
            create_playlist_from_liked_tracks()
        elif choice == "12":
            update_playlist_from_liked_tracks()
        elif choice == "13":
            sync_offline_liked_tracks()
        else:
            if not _ensure_api_key_configured(interactive=True):
                continue
            start(choice)


def test():
    SETTINGS.read(getProfilePath())
    TOKEN.read(getTokenPath())

    if not loginByConfig():
        if apiSupportsPkce():
            loginByPkce()
        else:
            loginByWeb()

    SETTINGS.audioQuality = AudioQuality.Master
    SETTINGS.videoFileFormat = VideoQuality.P240
    SETTINGS.checkExist = False
    SETTINGS.includeEP = True
    SETTINGS.saveCovers = True
    SETTINGS.lyricFile = True
    SETTINGS.showProgress = True
    SETTINGS.showTrackInfo = True
    SETTINGS.saveAlbumInfo = True
    SETTINGS.downloadVideos = True
    SETTINGS.downloadPath = "./download/"
    SETTINGS.usePlaylistFolder = True
    SETTINGS.albumFolderFormat = R"{ArtistName}/{Flag} {AlbumTitle} [{AlbumID}] [{AlbumYear}]"
    SETTINGS.playlistFolderFormat = R"Playlist/{PlaylistName} [{PlaylistUUID}]"
    SETTINGS.trackFileFormat = R"{TrackNumber} - {ArtistName} - {TrackTitle}{ExplicitFlag}"
    SETTINGS.videoFileFormat = R"{VideoNumber} - {ArtistName} - {VideoTitle}{ExplicitFlag}"
    SETTINGS.multiThread = False
    SETTINGS.apiKeyIndex = 4
    SETTINGS.checkExist = False

    Printf.settings()

    TIDAL_API.getPlaylistSelf()
    # test example
    # https://tidal.com/browse/track/70973230
    # track 70973230  77798028 212657
    start('242700165')
    # album 58138532  77803199  21993753   79151897  56288918
    # start('58138532')
    # playlist 98235845-13e8-43b4-94e2-d9f8e603cee7
    # start('98235845-13e8-43b4-94e2-d9f8e603cee7')
    # video 155608351 188932980 https://tidal.com/browse/track/55130637
    # start("155608351")https://tidal.com/browse/track/199683732


if __name__ == '__main__':
    # test()
    main()
