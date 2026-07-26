"""Tests for frame candidate extraction."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

def test_assign_scenes_to_segments_basic():
    """Scene frames are assigned to correct segments with dedup."""
    from core.vision.frames import _assign_scenes_to_segments

    # 60s video, 3 segments of 20s each
    # Baseline at 10s, 30s, 50s
    scenes = [(5.0, 0.8), (15.0, 0.6), (25.0, 0.9), (35.0, 0.5), (45.0, 0.7)]
    baselines = [10.0, 30.0, 50.0]
    result = _assign_scenes_to_segments(scenes, 60.0, 3, max_per_seg=2, min_gap=5.0, baseline_timestamps=baselines)
    # All scenes are exactly 5.0s from baseline (not < 5.0), so all kept
    assert result == [5.0, 15.0, 25.0, 35.0, 45.0]


def test_assign_scenes_dedup_within_segment():
    """Two scene frames within min_gap in same segment → keep first encountered."""
    from core.vision.frames import _assign_scenes_to_segments

    # 100s video, 1 segment
    scenes = [(20.0, 0.5), (22.0, 0.9)]  # 2s apart, < min_gap=5
    baselines = [50.0]
    result = _assign_scenes_to_segments(scenes, 100.0, 1, max_per_seg=2, min_gap=5.0, baseline_timestamps=baselines)
    # Scenes sorted by score desc: (22.0, 0.9) first, then (20.0, 0.5) discarded (< 5s from 22.0)
    assert result == [22.0]


def test_assign_scenes_discards_close_to_baseline():
    """Scene frame < min_gap from baseline is discarded."""
    from core.vision.frames import _assign_scenes_to_segments

    # 60s video, 1 segment, baseline at 30s
    scenes = [(28.0, 0.9)]  # 2s from baseline
    baselines = [30.0]
    result = _assign_scenes_to_segments(scenes, 60.0, 1, max_per_seg=2, min_gap=5.0, baseline_timestamps=baselines)
    # 28.0 is only 2s from baseline 30.0 → discarded
    assert result == []


def test_assign_scenes_empty_scenes():
    """No scenes → empty result."""
    from core.vision.frames import _assign_scenes_to_segments

    result = _assign_scenes_to_segments([], 60.0, 3, max_per_seg=2, min_gap=5.0, baseline_timestamps=[10.0, 30.0, 50.0])
    assert result == []


def test_assign_scenes_zero_duration():
    """Zero duration → empty result."""
    from core.vision.frames import _assign_scenes_to_segments

    result = _assign_scenes_to_segments([(5.0, 0.8)], 0.0, 3, max_per_seg=2, min_gap=5.0, baseline_timestamps=[])
    assert result == []


def test_detect_scene_changes_parses_ffmpeg_metadata(tmp_path):
    from core.vision.frames import _detect_scene_changes

    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    stdout = (
        "frame:0 pts:100 pts_time:4.25\n"
        "lavfi.scene_score=0.651257\n"
        "frame:1 pts:200 pts_time:9.5\n"
        "lavfi.scene_score=0.820679\n"
    )
    with patch("core.vision.frames.subprocess.run") as run:
        run.return_value = MagicMock(stdout=stdout, stderr="")
        scenes = _detect_scene_changes(video, 0.3)

    assert scenes == [(4.25, 0.651257), (9.5, 0.820679)]
    assert "metadata=print:file=-" in run.call_args.args[0][4]


def test_extract_frames_hybrid_fallback_on_no_duration():
    """Hybrid mode falls back to fps when duration is unknown."""
    from core.vision.frames import _extract_frames_hybrid

    with tempfile.TemporaryDirectory() as tmp:
        video = Path(tmp) / "test.mp4"
        video.write_bytes(b"fake video")
        out_dir = Path(tmp) / "frames"
        out_dir.mkdir()

        with patch("core.vision.frames._get_video_duration", return_value=0), \
             patch("core.vision.frames._extract_frames_fps", return_value=[Path("frame.webp")]) as mock_fps:
            result = _extract_frames_hybrid(video, out_dir)
            mock_fps.assert_called_once()
            assert len(result) == 1


def test_extract_frames_hybrid_with_scenes():
    """Hybrid mode combines baseline and scene frames."""
    from core.vision.frames import _extract_frames_hybrid

    with tempfile.TemporaryDirectory() as tmp:
        video = Path(tmp) / "test.mp4"
        video.write_bytes(b"fake video")
        out_dir = Path(tmp) / "frames"
        out_dir.mkdir()

        # 120s video, 3 segments for simplicity
        fake_scenes = [(10.0, 0.9), (50.0, 0.8), (90.0, 0.7)]

        with patch("core.vision.frames._get_video_duration", return_value=120.0), \
             patch("core.vision.frames._detect_scene_changes", return_value=fake_scenes), \
             patch("core.vision.frames._encode_frame", side_effect=lambda v, ts, out, w, f, q: out.touch() or True):
            result = _extract_frames_hybrid(video, out_dir, segments=3, max_scene_per_seg=2, min_gap=5.0)
            # 3 baselines + scene frames (all > 5s from baselines)
            assert len(result) >= 3  # at least the 3 baselines
            # All files are .webp
            assert all(f.suffix == ".webp" for f in result)


def test_extract_frames_webp_format():
    """Extracted frames use webp extension by default."""
    from core.vision.frames import _extract_frames_hybrid

    with tempfile.TemporaryDirectory() as tmp:
        video = Path(tmp) / "test.mp4"
        video.write_bytes(b"fake video")
        out_dir = Path(tmp) / "frames"
        out_dir.mkdir()

        with patch("core.vision.frames._get_video_duration", return_value=60.0), \
             patch("core.vision.frames._detect_scene_changes", return_value=[]), \
             patch("core.vision.frames._encode_frame", side_effect=lambda v, ts, out, w, f, q: out.touch() or True):
            result = _extract_frames_hybrid(video, out_dir, segments=5, fmt="webp")
            assert all(f.suffix == ".webp" for f in result)
            assert all(f.name.startswith("frame_") for f in result)


def test_extract_frames_hybrid_honors_explicit_limit():
    """Explicit max_frames stays in hybrid mode and is passed as a cap."""
    from core.vision.frames import extract_frames

    with tempfile.TemporaryDirectory() as tmp:
        video = Path(tmp) / "test.mp4"
        video.write_bytes(b"fake video")

        with patch(
            "core.vision.frames._extract_frames_hybrid", return_value=[]
        ) as mock_hybrid:
            extract_frames(video, max_frames=10, mode="hybrid")
            assert mock_hybrid.call_args.kwargs["max_frames"] == 10


def test_hybrid_fills_requested_count_when_no_scenes(tmp_path):
    from core.vision.frames import _extract_frames_hybrid

    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    output = tmp_path / "frames"
    output.mkdir()
    with (
        patch("core.vision.frames._get_video_duration", return_value=100.0),
        patch("core.vision.frames._detect_scene_changes", return_value=[]),
        patch(
            "core.vision.frames._encode_frame",
            side_effect=lambda _v, _t, path, _w, _f, _q: path.touch() or True,
        ),
    ):
        frames = _extract_frames_hybrid(
            video, output, segments=60, max_frames=10
        )

    assert len(frames) == 10


def test_hybrid_expands_scene_burst_without_crossing_next_cut(tmp_path):
    from core.vision.frames import _extract_frames_hybrid

    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    output = tmp_path / "frames"
    output.mkdir()
    timestamps = []

    def encode(_video, timestamp, path, _width, _format, _quality):
        timestamps.append(timestamp)
        path.touch()
        return True

    with (
        patch("core.vision.frames._get_video_duration", return_value=100.0),
        patch(
            "core.vision.frames._detect_scene_changes",
            return_value=[(10.0, 0.9), (11.2, 0.8)],
        ),
        patch("core.vision.frames._encode_frame", side_effect=encode),
    ):
        _extract_frames_hybrid(
            video,
            output,
            segments=1,
            max_frames=4,
            min_gap=1,
            scene_offsets=(0.0, 0.5, 1.0, 2.0),
        )

    assert 10.0 in timestamps
    assert 10.5 in timestamps
    assert 11.0 in timestamps


def test_encode_frame_webp_cmd():
    """_encode_frame builds correct ffmpeg command for webp."""
    from core.vision.frames import _encode_frame

    with tempfile.TemporaryDirectory() as tmp:
        video = Path(tmp) / "test.mp4"
        video.write_bytes(b"fake")
        out_path = Path(tmp) / "frame.webp"

        with (
            patch("core.vision.frames.subprocess.run") as mock_run,
            patch("core.vision.frames._supports_encoder", return_value=True),
        ):
            mock_run.return_value = MagicMock(returncode=0)
            # Make out_path exist
            out_path.touch()

            result = _encode_frame(video, 10.0, out_path, 1280, "webp", 85)
            assert result is True
            cmd = mock_run.call_args[0][0]
            assert "-c:v" in cmd
            assert "libwebp" in cmd
            assert "-quality" in cmd
            assert "85" in cmd
            assert "scale=1280:-2" in cmd


def test_encode_timestamps_runs_with_bounded_concurrency():
    import threading
    import time

    from core.config import settings
    from core.vision.frames import _encode_timestamps

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        video = root / "test.mp4"
        video.write_bytes(b"fake")
        thread_ids = set()
        lock = threading.Lock()

        def fake_encode(_video, _ts, output, _width, _fmt, _quality):
            with lock:
                thread_ids.add(threading.get_ident())
            time.sleep(0.02)
            output.touch()
            return True

        with (
            patch.object(settings, "frame_workers", 3),
            patch("core.vision.frames._encode_frame", side_effect=fake_encode),
        ):
            frames = _encode_timestamps(
                video,
                root,
                [1.0, 2.0, 3.0, 4.0],
                1280,
                "webp",
                85,
            )

        assert [frame.name for frame in frames] == [
            "frame_0001.webp",
            "frame_0002.webp",
            "frame_0003.webp",
            "frame_0004.webp",
        ]
        assert len(thread_ids) > 1


def test_extract_frames_at_normalizes_timestamps(tmp_path):
    from core.vision.frames import extract_frames_at

    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    output = tmp_path / "frames"
    with (
        patch("core.vision.frames.BasePlatform.check_ffmpeg"),
        patch(
            "core.vision.frames._encode_timestamps",
            return_value=[],
        ) as mock_encode,
        patch("core.vision.frames._supports_encoder", return_value=True),
    ):
        extract_frames_at(video, output, [10, -2, 10, 3])

    assert mock_encode.call_args.args[2] == [0.0, 3.0, 10.0]


def test_scene_mode_converts_jpeg_frames_with_cwebp(tmp_path):
    from core.config import settings
    from core.vision.frames import extract_frames

    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    jpeg = tmp_path / "frame_0001.jpg"
    with (
        patch.object(settings, "frame_format", "webp"),
        patch("core.vision.frames.BasePlatform.check_ffmpeg"),
        patch("core.vision.frames._supports_encoder", return_value=False),
        patch("core.vision.frames._supports_cwebp", return_value=True),
        patch(
            "core.vision.frames._extract_frames_scene",
            return_value=[jpeg],
        ),
        patch(
            "core.vision.frames._convert_images_to_webp",
            return_value=[jpeg.with_suffix(".webp")],
        ) as mock_convert,
    ):
        frames = extract_frames(video, output_dir=tmp_path, mode="scene")

    mock_convert.assert_called_once_with([jpeg], settings.frame_quality)
    assert frames == [jpeg.with_suffix(".webp")]
