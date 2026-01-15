#!/usr/bin/env python
# -*- encoding: utf-8 -*-
'''
@File    :   download.py
@Time    :   2020/11/08
@Author  :   Yaronzz
@Version :   1.0
@Contact :   yaronhuang@foxmail.com
@Desc    :
'''

from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict

import errno
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional, Tuple

import aigpy
import requests
from mutagen import MutagenError, File as MutagenFile
from mutagen.flac import FLAC

from .coverfix import ensure_flac_cover_art
from .decryption import decrypt_file, decrypt_security_token
from .model import Album, Playlist, StreamUrl, Track, Video
from .paths import getAlbumPath, getTrackPath, getVideoPath
from .printf import Printf
from .settings import SETTINGS
from .tidal import TIDAL_API


try:  # pragma: no cover - optional dependency
    import av  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    av = None  # type: ignore

_FFMPEG_AVAILABLE: Optional[bool] = None
_PYAV_AVAILABLE: Optional[bool] = None
_ALBUM_COVER_CACHE: Dict[str, bytes] = {}


def _quality_rank(value: str) -> int:
    ranking = {
        "LOW": 0,
        "HIGH": 1,
        "LOSSLESS": 2,
        "HI_RES": 3,
        "HI_RES_LOSSLESS": 4,
    }
    return ranking.get((value or "").upper(), -1)


def _local_stream_quality(path: str) -> str:
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


def __isSkip__(finalpath: str, url: str, stream: Optional[StreamUrl] = None) -> bool:
    if not SETTINGS.checkExist:
        return False
    curSize = aigpy.file.getSize(finalpath)
    if curSize <= 0:
        return False
    if not SETTINGS.audioConvertFormat:
        netSize = aigpy.net.getSize(url)
        if curSize < netSize:
            return False
    if stream is None:
        return True
    local_quality = _local_stream_quality(finalpath)
    if not local_quality:
        return True
    local_rank = _quality_rank(local_quality)
    stream_rank = _quality_rank(str(getattr(stream, "soundQuality", "")))
    if local_rank < 0 or stream_rank < 0:
        return True
    return local_rank >= stream_rank


def _replace_file(src: str, dest: str) -> None:
    """Atomically replace *dest* with *src*.

    Falls back to a copy-and-remove strategy when the source and destination
    reside on different filesystems, mimicking ``os.replace`` semantics.
    """

    try:
        os.replace(src, dest)
    except OSError as exc:  # pragma: no cover - filesystem dependent
        if exc.errno != errno.EXDEV:
            raise

        if os.path.exists(dest):
            if os.path.isdir(dest):
                raise
            os.remove(dest)

        shutil.move(src, dest)


def __encrypted__(stream: StreamUrl, srcPath: str, descPath: str) -> str:
    if aigpy.string.isNull(stream.encryptionKey):
        _replace_file(srcPath, descPath)
        return descPath

    key, nonce = decrypt_security_token(stream.encryptionKey)
    decrypt_file(srcPath, descPath, key, nonce)
    os.remove(srcPath)
    return descPath


def _ffmpeg_ready() -> bool:
    global _FFMPEG_AVAILABLE
    if _FFMPEG_AVAILABLE is None:
        _FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None
    return bool(_FFMPEG_AVAILABLE)


def _pyav_ready() -> bool:
    global _PYAV_AVAILABLE
    if _PYAV_AVAILABLE is None:
        _PYAV_AVAILABLE = av is not None
    return bool(_PYAV_AVAILABLE)


def _flac_remux_available() -> bool:
    return _pyav_ready() or _ffmpeg_ready()


def _guess_stream_extension(stream: StreamUrl) -> str:
    candidates = []
    if stream.url:
        candidates.append(stream.url)
    if stream.urls:
        candidates.extend(stream.urls)

    for candidate in candidates:
        if not candidate:
            continue
        lowered = candidate.split("?")[0].lower()
        for ext in (".flac", ".mp4", ".m4a", ".m4b", ".mp3", ".ogg", ".aac"):
            if lowered.endswith(ext):
                return ext

    codec = (stream.codec or "").lower()
    if "flac" in codec:
        return ".flac"
    if "mp4" in codec or "m4a" in codec or "aac" in codec:
        return ".m4a"
    return ".m4a"


def _should_remux_flac(download_ext: str, final_ext: str, stream: StreamUrl) -> bool:
    if final_ext != ".flac":
        return False
    if download_ext == ".flac":
        return False
    return "flac" in (stream.codec or "").lower()


def _remux_with_pyav(src_path: str, dest_path: str) -> Tuple[bool, str]:
    if not _pyav_ready():
        return False, "PyAV backend unavailable"

    assert av is not None  # for type-checkers
    try:
        with av.open(src_path) as container:
            audio_stream = next((s for s in container.streams if s.type == "audio"), None)
            if audio_stream is None:
                return False, "PyAV could not locate an audio stream"
            with av.open(dest_path, mode="w", format="flac") as output:
                out_stream = output.add_stream(template=audio_stream)
                for packet in container.demux(audio_stream):
                    if packet.dts is None:
                        continue
                    packet.stream = out_stream
                    output.mux(packet)
    except Exception as exc:  # pragma: no cover - PyAV raises custom errors
        return False, f"PyAV error: {exc}"

    return os.path.exists(dest_path) and os.path.getsize(dest_path) > 0, "PyAV"


def _remux_with_ffmpeg(src_path: str, dest_path: str) -> Tuple[bool, str]:
    if not _ffmpeg_ready():
        return False, "ffmpeg backend unavailable"

    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-i",
        src_path,
        "-map",
        "0:a:0",
        "-c:a",
        "copy",
        dest_path,
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except subprocess.CalledProcessError as exc:
        return False, f"ffmpeg exited with code {exc.returncode}"

    return os.path.exists(dest_path) and os.path.getsize(dest_path) > 0, "ffmpeg"


def _remux_flac_stream(src_path: str, dest_path: str) -> Tuple[str, Optional[str]]:
    if os.path.exists(dest_path):
        os.remove(dest_path)

    last_reason: Optional[str] = None
    for backend in (_remux_with_pyav, _remux_with_ffmpeg):
        ok, reason = backend(src_path, dest_path)
        if ok:
            logging.debug("Remuxed FLAC stream into native container using %s", reason)
            return dest_path, reason
        last_reason = reason
        if os.path.exists(dest_path):
            os.remove(dest_path)

    if last_reason:
        logging.debug("Unable to remux FLAC stream using available backends: %s", last_reason)
    return src_path, last_reason


def _convert_audio(src_path: str, dest_path: str, fmt: str) -> Tuple[bool, str]:
    fmt = (fmt or "").lower()
    if not fmt:
        return True, ""
    cmd = ["ffmpeg", "-y", "-i", src_path]
    if fmt in ("alac", "m4a", "aac"):
        cmd += ["-c:a", "alac"]
    elif fmt == "flac":
        cmd += ["-c:a", "flac"]
    elif fmt == "wav":
        cmd += ["-c:a", "pcm_s16le"]
    elif fmt == "mp3":
        cmd += ["-c:a", "libmp3lame", "-q:a", "2"]
    else:
        return False, f"Unsupported convert format: {fmt}"
    cmd.append(dest_path)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        return False, "ffmpeg not found in PATH"
    if result.returncode != 0:
        err = result.stderr.strip() or result.stdout.strip() or "ffmpeg conversion failed"
        return False, err
    return True, ""


def __parseContributors__(roleType: str, contributors: Optional[dict]) -> Optional[list[str]]:
    if contributors is None:
        return None
    try:
        ret: list[str] = []
        for item in contributors['items']:
            if item['role'] == roleType:
                ret.append(item['name'])
        return ret
    except (KeyError, TypeError):
        return None


def _extract_media_tags(track: Track, album: Optional[Album]) -> list[str]:
    tags: list[str] = []
    for source in (
        getattr(track, "mediaMetadata", None),
        getattr(album, "mediaMetadata", None) if album else None,
    ):
        if source and getattr(source, "tags", None):
            tags = [tag for tag in source.tags if tag]
            if tags:
                break
    return tags


def _collect_contributor_roles(contributors: Optional[dict]) -> dict[str, list[str]]:
    role_map: dict[str, list[str]] = defaultdict(list)
    if not contributors:
        return role_map

    items = contributors.get("items")
    if not isinstance(items, list):
        return role_map

    for entry in items:
        if not isinstance(entry, dict):
            continue
        role = entry.get("role")
        name = entry.get("name")
        if not role or not name:
            continue
        key = f"CREDITS_{str(role).upper().replace(' ', '_')}"
        if name not in role_map[key]:
            role_map[key].append(str(name))
    return role_map


def _format_gain(value: Optional[Any]) -> Optional[str]:
    if value is None:
        return None
    try:
        return f"{float(value):.2f} dB"
    except (TypeError, ValueError):
        return str(value)


def _format_peak(value: Optional[Any]) -> Optional[str]:
    if value is None:
        return None
    try:
        return f"{float(value):.6f}"
    except (TypeError, ValueError):
        return str(value)


def _update_flac_metadata(
    filepath: str,
    track: Track,
    album: Optional[Album],
    contributors: Optional[dict],
    stream: Optional[StreamUrl],
) -> None:
    try:
        audio = FLAC(filepath)
    except (FileNotFoundError, MutagenError) as exc:
        logging.debug("Failed to open FLAC file for metadata update: %s", exc)
        return

    def set_tag(key: str, value: Any) -> None:
        if value is None:
            return
        if isinstance(value, bool):
            text = "1" if value else "0"
            audio[key] = [text]
            return
        if isinstance(value, (list, tuple, set)):
            values = []
            for item in value:
                if item is None:
                    continue
                if isinstance(item, bool):
                    item = "1" if item else "0"
                item_text = str(item).strip()
                if item_text:
                    values.append(item_text)
            if values:
                audio[key] = values
            return
        text = str(value).strip()
        if text:
            audio[key] = [text]

    set_tag("TIDAL_TRACK_ID", track.id)
    set_tag("TIDAL_TRACK_VERSION", track.version)
    set_tag("TIDAL_TRACK_POPULARITY", track.popularity)
    set_tag("TIDAL_STREAM_START_DATE", track.streamStartDate)
    set_tag("TIDAL_EXPLICIT", track.explicit)
    set_tag("TIDAL_AUDIO_QUALITY", getattr(track, "audioQuality", None))
    set_tag("TIDAL_AUDIO_MODES", getattr(track, "audioModes", None) or [])
    set_tag("TIDAL_MEDIA_METADATA_TAGS", _extract_media_tags(track, album))
    set_tag("REPLAYGAIN_TRACK_GAIN", _format_gain(getattr(track, "replayGain", None)))
    set_tag("REPLAYGAIN_TRACK_PEAK", _format_peak(getattr(track, "peak", None)))

    if album is not None:
        set_tag("TIDAL_ALBUM_ID", album.id)
        set_tag("TIDAL_ALBUM_VERSION", album.version)
        set_tag("BARCODE", getattr(album, "upc", None))
        set_tag("TIDAL_ALBUM_POPULARITY", getattr(album, "popularity", None))
        set_tag("DATE", album.releaseDate)
        set_tag("TIDAL_ALBUM_STREAM_START_DATE", getattr(album, "streamStartDate", None))
        set_tag("TIDAL_ALBUM_AUDIO_QUALITY", getattr(album, "audioQuality", None))
        set_tag("TIDAL_ALBUM_AUDIO_MODES", getattr(album, "audioModes", None) or [])

    if stream is not None:
        set_tag("CODEC", stream.codec)
        set_tag("TIDAL_STREAM_SOUND_QUALITY", stream.soundQuality)
        set_tag("BITS_PER_SAMPLE", stream.bitDepth)
        set_tag("SAMPLERATE", stream.sampleRate)

    if track.trackNumberOnPlaylist:
        set_tag("TIDAL_PLAYLIST_TRACK_NUMBER", track.trackNumberOnPlaylist)

    copyright_text = track.copyRight or (getattr(album, "copyright", None) if album else None)
    set_tag("COPYRIGHT", copyright_text)

    contributor_roles = _collect_contributor_roles(contributors)
    for role_key, names in contributor_roles.items():
        set_tag(role_key, names)
    if contributor_roles:
        all_names = [name for names in contributor_roles.values() for name in names]
        set_tag("TIDAL_CREDITS", all_names)

    set_tag("URL", f"https://listen.tidal.com/track/{track.id}")
    if album is not None and album.id is not None:
        set_tag("URL_OFFICIAL_RELEASE_SITE", f"https://listen.tidal.com/album/{album.id}")

    try:
        audio.save()
    except MutagenError as exc:
        logging.debug("Unable to save extended metadata for %s: %s", filepath, exc)


def _download_cover_bytes(url: str, album: Optional[Album]) -> Optional[bytes]:
    album_id = getattr(album, "id", "unknown")
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
    except Exception:
        logging.debug(
            "Failed to download cover art for album %s from %s",
            album_id,
            url,
            exc_info=True,
        )
        return None

    if not response.content:
        logging.debug(
            "Cover art download for album %s returned empty content from %s",
            album_id,
            url,
        )
        return None

    return response.content


def _make_cover_fetcher(album: Optional[Album]) -> Optional[Callable[[Path], Optional[Path]]]:
    if album is None:
        return None
    cover_id = getattr(album, "cover", None)
    if aigpy.string.isNull(cover_id):
        return None

    url = TIDAL_API.getCoverUrl(cover_id, "1280", "1280")
    cache_key = str(cover_id)
    cover_bytes = _ALBUM_COVER_CACHE.get(cache_key)

    def _fetch(tmp_path: Path) -> Optional[Path]:
        nonlocal cover_bytes
        destination = tmp_path / "fallback_cover.jpg"

        if cover_bytes is None:
            cover_bytes = _download_cover_bytes(url, album)
            if cover_bytes is None:
                return None
            _ALBUM_COVER_CACHE[cache_key] = cover_bytes

        try:
            destination.write_bytes(cover_bytes)
        except OSError:
            logging.debug(
                "Failed to materialise cached cover art for album %s",
                getattr(album, "id", "unknown"),
                exc_info=True,
            )
            return None

        return destination

    return _fetch


def __setMetaData__(
    track: Track,
    album: Album,
    filepath: str,
    contributors: Optional[dict],
    lyrics: str,
    stream: Optional[StreamUrl],
) -> None:
    is_flac_file = filepath.lower().endswith(".flac")
    obj = aigpy.tag.TagTool(filepath)
    obj.album = track.album.title
    obj.title = track.title
    if not aigpy.string.isNull(track.version):
        obj.title += ' (' + track.version + ')'

    obj.artist = list(map(lambda artist: artist.name, track.artists))
    obj.copyright = track.copyRight
    obj.tracknumber = track.trackNumber
    obj.discnumber = track.volumeNumber
    obj.composer = __parseContributors__('Composer', contributors)
    obj.isrc = track.isrc

    obj.albumartist = list(map(lambda artist: artist.name, album.artists))
    obj.date = album.releaseDate
    obj.totaldisc = album.numberOfVolumes
    obj.lyrics = lyrics
    if obj.totaldisc <= 1:
        obj.totaltrack = album.numberOfTracks
    coverpath = TIDAL_API.getCoverUrl(album.cover, "1280", "1280")
    save_ret = obj.save(coverpath)
    if save_ret is not True and save_ret is not None:
        logging.debug("TagTool failed to save tags for %s: %s", filepath, save_ret)

    if is_flac_file:
        cover_ok, cover_message = ensure_flac_cover_art(
            filepath, report=True, fetch_cover=_make_cover_fetcher(album)
        )
        if cover_message:
            if cover_ok:
                Printf.info(f"Cover art status: {cover_message}")
            else:
                Printf.info(f"Cover art status (needs attention): {cover_message}")
        if not cover_ok:
            logging.debug(
                "Cover normalisation did not succeed for %s: %s", filepath, cover_message
            )

        _update_flac_metadata(filepath, track, album, contributors, stream)


def downloadCover(album: Optional[Album]) -> None:
    if album is None:
        return

    cover_id = getattr(album, "cover", None)
    if aigpy.string.isNull(cover_id):
        return

    cache_key = str(cover_id)
    cover_bytes = _ALBUM_COVER_CACHE.get(cache_key)

    if cover_bytes is None:
        url = TIDAL_API.getCoverUrl(cover_id, "1280", "1280")
        cover_bytes = _download_cover_bytes(url, album)
        if cover_bytes is None:
            return
        _ALBUM_COVER_CACHE[cache_key] = cover_bytes

    temp_path: Optional[str] = None
    try:
        album_path = Path(getAlbumPath(album))
        cover_path = album_path / "cover.jpg"
        if cover_path.exists():
            try:
                cover_path.unlink()
            except OSError:
                logging.debug(
                    "Failed to remove stale cover art file for album %s",
                    getattr(album, "id", "unknown"),
                    exc_info=True,
                )

        temp_dir = Path(tempfile.gettempdir()) / "tidal-dl"
        album_id = getattr(album, "id", None)
        if album_id:
            temp_dir = temp_dir / str(album_id)
        temp_dir.mkdir(parents=True, exist_ok=True)
        cover_destination = temp_dir / "cover.jpg"

        with tempfile.NamedTemporaryFile(
            prefix="tidaldl-cover-",
            suffix=".jpg",
            delete=False,
            dir=str(temp_dir),
        ) as tmp:
            tmp.write(cover_bytes)
            temp_path = tmp.name

        assert temp_path is not None  # for type-checkers
        _replace_file(temp_path, str(cover_destination))
        temp_path = None
    except Exception:
        logging.debug(
            "Failed to write cover art file for album %s", getattr(album, "id", "unknown"),
            exc_info=True,
        )
    finally:
        if temp_path is not None:
            try:
                os.remove(temp_path)
            except OSError:
                logging.debug(
                    "Failed to clean up temporary cover art file %s", temp_path, exc_info=True
                )


def downloadAlbumInfo(album: Optional[Album], tracks: Iterable[Track]) -> None:
    if album is None:
        return

    path = getAlbumPath(album)
    aigpy.path.mkdirs(path)

    path += '/AlbumInfo.txt'
    infos = ""
    infos += "[ID]          %s\n" % (str(album.id))
    infos += "[Title]       %s\n" % (str(album.title))
    infos += "[Artists]     %s\n" % (TIDAL_API.getArtistsName(album.artists))
    infos += "[ReleaseDate] %s\n" % (str(album.releaseDate))
    infos += "[SongNum]     %s\n" % (str(album.numberOfTracks))
    infos += "[Duration]    %s\n" % (str(album.duration))
    infos += '\n'

    for index in range(0, album.numberOfVolumes):
        volumeNumber = index + 1
        infos += f"===========CD {volumeNumber}=============\n"
        for item in tracks:
            if item.volumeNumber != volumeNumber:
                continue
            infos += '{:<8}'.format("[%d]" % item.trackNumber)
            infos += "%s\n" % item.title
    aigpy.file.write(path, infos, "w+")


def downloadVideo(video: Video, album: Album = None, playlist: Playlist = None) -> Tuple[bool, Optional[str]]:
    try:
        stream = TIDAL_API.getVideoStreamUrl(video.id, SETTINGS.videoQuality)
        path = getVideoPath(video, album, playlist)

        Printf.video(video, stream)
        logging.info("[DL Video] name=" + aigpy.path.getFileName(path) + "\nurl=" + stream.m3u8Url)

        response = requests.get(stream.m3u8Url)
        response.raise_for_status()
        m3u8content = response.content if response is not None else None
        if not m3u8content:
            message = "GetM3u8 failed."
            Printf.err(f"DL Video[{video.title}] {message}")
            return False, message

        urls = aigpy.m3u8.parseTsUrls(m3u8content)
        if not urls:
            message = "GetTsUrls failed."
            Printf.err(f"DL Video[{video.title}] {message}")
            return False, message

        check, msg = aigpy.m3u8.downloadByTsUrls(urls, path)
        if check:
            Printf.success(video.title)
            return True, None

        Printf.err(f"DL Video[{video.title}] failed.{msg}")
        return False, msg
    except Exception as e:
        Printf.err(f"DL Video[{video.title}] failed.{str(e)}")
        return False, str(e)


def downloadTrack(
    track: Track,
    album: Optional[Album] = None,
    playlist: Optional[Playlist] = None,
    userProgress: Any = None,
    partSize: int = 1048576,
    base_override: Optional[str] = None,
) -> Tuple[bool, str, Optional[StreamUrl]]:
    try:
        stream = TIDAL_API.getStreamUrl(track.id, SETTINGS.audioQuality)
        path = getTrackPath(track, stream, album, playlist, base_override=base_override)
        base_path, expected_extension = os.path.splitext(path)
        expected_extension = expected_extension.lower()
        download_extension = _guess_stream_extension(stream)
        remux_required = _should_remux_flac(download_extension, expected_extension, stream)

        if remux_required and not _flac_remux_available():
            logging.info(
                "FLAC stream for '%s' requires remuxing but no backend is available; keeping %s container",
                track.title,
                download_extension,
            )
            expected_extension = download_extension
            path = base_path + expected_extension
            remux_required = False

        if SETTINGS.showTrackInfo and not SETTINGS.multiThread:
            Printf.track(track, stream)

        if userProgress is not None:
            userProgress.updateStream(stream)

        # check exist
        if __isSkip__(path, stream.url, stream):
            Printf.success(aigpy.path.getFileName(path) + " (skip:already exists!)")
            return True, '', stream

        parent_dir = os.path.dirname(path)
        if parent_dir:
            aigpy.path.mkdirs(parent_dir)

        logging.info("[DL Track] name=" + aigpy.path.getFileName(path) + "\nurl=" + stream.url)

        with tempfile.TemporaryDirectory(prefix="tidaldl-track-") as tmpdir:
            download_part = os.path.join(
                tmpdir, f"download{download_extension}.part" if download_extension else "download.part"
            )
            tool = aigpy.download.DownloadTool(download_part, stream.urls)
            tool.setUserProgress(userProgress)
            tool.setPartSize(partSize)
            check, err = tool.start(SETTINGS.showProgress and not SETTINGS.multiThread)
            if not check:
                Printf.err(f"DL Track '{track.title}' failed: {str(err)}")
                return False, str(err), stream

            decrypted_target = os.path.join(
                tmpdir, f"decrypted{download_extension}" if download_extension else "decrypted"
            )
            decrypted_path = __encrypted__(stream, download_part, decrypted_target)

            processed_path = decrypted_path
            if remux_required:
                remux_target = os.path.join(tmpdir, "remux.flac")
                processed_path, backend_used = _remux_flac_stream(decrypted_path, remux_target)
                if processed_path != decrypted_path and os.path.exists(decrypted_path):
                    os.remove(decrypted_path)
                if processed_path == decrypted_path:
                    logging.warning(
                        "Unable to remux FLAC stream for '%s'; leaving original container. Backend message: %s",
                        track.title,
                        backend_used,
                    )
                    path = base_path + download_extension
                    expected_extension = download_extension

            final_tmp_path = os.path.join(tmpdir, f"final{expected_extension}") if expected_extension else processed_path
            if processed_path != final_tmp_path:
                _replace_file(processed_path, final_tmp_path)
                processed_path = final_tmp_path

            convert_format = (SETTINGS.audioConvertFormat or "").strip().lower()
            if convert_format:
                target_ext = os.path.splitext(path)[1].lower()
                converted_path = os.path.join(tmpdir, f"converted{target_ext}")
                ok, err = _convert_audio(processed_path, converted_path, convert_format)
                if not ok:
                    Printf.err(f"Audio convert failed for '{track.title}': {err}")
                    return False, err, stream
                processed_path = converted_path

            _replace_file(processed_path, path)

        # contributors
        try:
            contributors = TIDAL_API.getTrackContributors(track.id)
        except Exception:
            contributors = None

        # lyrics
        try:
            lyrics = TIDAL_API.getLyrics(track.id).subtitles
            if SETTINGS.lyricFile:
                lrcPath = path.rsplit(".", 1)[0] + '.lrc'
                aigpy.file.write(lrcPath, lyrics, 'w')
        except Exception:
            lyrics = ''

        __setMetaData__(track, album, path, contributors, lyrics, stream)
        Printf.success(track.title)

        return True, '', stream
    except Exception as e:
        Printf.err(f"DL Track '{track.title}' failed: {str(e)}")
        return False, str(e), None


def downloadTracks(
    tracks: Iterable[Track],
    album: Optional[Album] = None,
    playlist: Optional[Playlist] = None,
    start_index: int = 1,
    collect_errors: bool = False,
) -> None:
    def __getAlbum__(item: Track):
        album = TIDAL_API.getAlbum(item.album.id)
        if SETTINGS.saveCovers and not SETTINGS.usePlaylistFolder:
            downloadCover(album)
        return album

    errors = []
    start_index = max(1, int(start_index))

    if not SETTINGS.multiThread:
        for index, item in enumerate(tracks):
            if (index + 1) < start_index:
                continue
            itemAlbum = album
            if itemAlbum is None:
                try:
                    itemAlbum = __getAlbum__(item)
                    item.trackNumberOnPlaylist = index + 1
                except Exception as exc:
                    if collect_errors:
                        errors.append((index + 1, item.title, str(exc)))
                    Printf.err(f"Skip track '{item.title}' due to album error: {exc}")
                    continue
            ok, err, _ = downloadTrack(item, itemAlbum, playlist)
            if collect_errors and not ok:
                errors.append((index + 1, item.title, err))
    else:
        thread_pool = ThreadPoolExecutor(max_workers=5)
        futures = []
        for index, item in enumerate(tracks):
            if (index + 1) < start_index:
                continue
            itemAlbum = album
            if itemAlbum is None:
                try:
                    itemAlbum = __getAlbum__(item)
                    item.trackNumberOnPlaylist = index + 1
                except Exception as exc:
                    if collect_errors:
                        errors.append((index + 1, item.title, str(exc)))
                    Printf.err(f"Skip track '{item.title}' due to album error: {exc}")
                    continue
            futures.append((index + 1, item, thread_pool.submit(downloadTrack, item, itemAlbum, playlist)))
        if collect_errors:
            for idx, item, future in futures:
                ok, err, _ = future.result()
                if not ok:
                    errors.append((idx, item.title, err))
        thread_pool.shutdown(wait=True)

    if collect_errors and errors:
        Printf.info("Download errors summary:")
        for idx, title, err in errors:
            Printf.err(f"[{idx}] {title}: {err}")
    return errors


def downloadVideos(
    videos: Iterable[Video],
    album: Optional[Album],
    playlist: Optional[Playlist] = None,
) -> None:
    for item in videos:
        downloadVideo(item, album, playlist)
