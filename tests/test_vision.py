"""Tests for multimodal pipeline — video path based summarization."""
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# --- Multimodal LLM tests ---

def test_base_llm_multimodal_fallback():
    """BaseLLM.summarize_multimodal falls back to text-only."""
    from core.llm.base import BaseLLM

    class DummyLLM(BaseLLM):
        def _chat(self, prompt, max_tokens=4096):
            return f"text-only: {prompt[:20]}"

    llm = DummyLLM()
    with tempfile.TemporaryDirectory() as tmp:
        video = Path(tmp) / "test.mp4"
        video.write_bytes(b"fake video")
        result = llm.summarize_multimodal("hello", video, lang="zh", detail="normal")
    assert "text-only" in result


def test_base_llm_classify():
    """BaseLLM.classify parses JSON response."""
    from core.llm.base import BaseLLM

    class DummyLLM(BaseLLM):
        def _chat(self, prompt, max_tokens=4096):
            return '{"summary": "test video", "type": "tutorial"}'

    llm = DummyLLM()
    result = llm.classify("some transcript")
    assert result["type"] == "tutorial"
    assert result["summary"] == "test video"


def test_base_llm_classify_invalid_json():
    """BaseLLM.classify falls back to general on bad JSON."""
    from core.llm.base import BaseLLM

    class DummyLLM(BaseLLM):
        def _chat(self, prompt, max_tokens=4096):
            return "not json at all"

    llm = DummyLLM()
    result = llm.classify("some transcript")
    assert result["type"] == "general"


def test_base_llm_classify_markdown_json():
    """BaseLLM.classify handles markdown-wrapped JSON."""
    from core.llm.base import BaseLLM

    class DummyLLM(BaseLLM):
        def _chat(self, prompt, max_tokens=4096):
            return '```json\n{"summary": "test", "type": "demo"}\n```'

    llm = DummyLLM()
    result = llm.classify("some transcript")
    assert result["type"] == "demo"


def test_claude_multimodal_extracts_frames():
    """Claude multimodal extracts frames internally and sends as images."""
    from core.llm.claude import ClaudeLLM

    with tempfile.TemporaryDirectory() as tmp:
        video = Path(tmp) / "test.mp4"
        video.write_bytes(b"fake video")

        with patch("core.llm.claude.settings") as mock_settings:
            mock_settings.anthropic_api_key = "test-key"
            mock_settings.anthropic_base_url = ""
            mock_settings.claude_model = "test-model"
            mock_settings.max_frames = 5
            mock_settings.frame_interval = 30

            llm = ClaudeLLM()

            with patch.object(llm, "_chat_multimodal", return_value="multimodal summary") as mock_chat, \
                 patch("core.llm.claude.extract_frames") as mock_extract:
                frame = Path(tmp) / "frame.jpg"
                frame.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
                mock_extract.return_value = [frame]

                result = llm.summarize_multimodal("transcript text", video, lang="zh", content_type="general")

                assert result == "multimodal summary"
                mock_extract.assert_called_once()
                call_args = mock_chat.call_args
                content = call_args[0][0]
                assert len(content) == 2
                assert content[0]["type"] == "image"
                assert content[1]["type"] == "text"


def test_openai_multimodal_frame_first():
    """OpenAI multimodal tries frame extraction first."""
    from core.llm.openai_proto import OpenAILLM

    with tempfile.TemporaryDirectory() as tmp:
        video = Path(tmp) / "test.mp4"
        video.write_bytes(b"fake video")

        with patch("core.llm.openai_proto.settings") as mock_settings:
            mock_settings.openai_api_key = "test-key"
            mock_settings.openai_base_url = "http://test"
            mock_settings.openai_model = "test-model"
            mock_settings.openai_vision_model = ""
            mock_settings.max_frames = 5
            mock_settings.frame_interval = 30

            llm = OpenAILLM()

            with patch.object(llm, "_chat_multimodal", return_value="frame summary") as mock_chat, \
                 patch("core.llm.openai_proto.extract_frames") as mock_extract:
                frame = Path(tmp) / "frame.jpg"
                frame.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
                mock_extract.return_value = [frame]

                result = llm.summarize_multimodal("transcript text", video, lang="zh", content_type="general")

                assert result == "frame summary"
                mock_extract.assert_called_once()
                call_args = mock_chat.call_args
                content = call_args[0][0]
                assert content[0]["type"] == "image_url"


def test_openai_multimodal_fallback_to_native_video():
    """OpenAI falls back to native video when frame extraction fails."""
    from core.llm.openai_proto import OpenAILLM

    with tempfile.TemporaryDirectory() as tmp:
        video = Path(tmp) / "test.mp4"
        video.write_bytes(b"fake video data")

        with patch("core.llm.openai_proto.settings") as mock_settings:
            mock_settings.openai_api_key = "test-key"
            mock_settings.openai_base_url = "http://test"
            mock_settings.openai_model = "test-model"
            mock_settings.openai_vision_model = "mimo-v2-omni"
            mock_settings.max_frames = 5
            mock_settings.frame_interval = 30

            llm = OpenAILLM()

            with patch.object(llm, "_chat_multimodal", return_value="native video summary") as mock_chat, \
                 patch("core.llm.openai_proto.extract_frames", return_value=[]):

                result = llm.summarize_multimodal("transcript text", video, lang="zh", content_type="general")

                assert result == "native video summary"
                call_args = mock_chat.call_args
                content = call_args[0][0]
                assert content[0]["type"] == "video_url"


def test_openai_multimodal_fallback_to_text():
    """OpenAI falls back to text-only when both frame and native video fail."""
    from core.llm.openai_proto import OpenAILLM

    with tempfile.TemporaryDirectory() as tmp:
        video = Path(tmp) / "test.mp4"
        video.write_bytes(b"fake video data")

        with patch("core.llm.openai_proto.settings") as mock_settings:
            mock_settings.openai_api_key = "test-key"
            mock_settings.openai_base_url = "http://test"
            mock_settings.openai_model = "test-model"
            mock_settings.openai_vision_model = "mimo-v2-omni"
            mock_settings.max_frames = 5
            mock_settings.frame_interval = 30

            llm = OpenAILLM()

            call_count = 0

            def side_effect(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise RuntimeError("API error")
                return "text fallback"

            with patch.object(llm, "_chat", side_effect=side_effect), \
                 patch.object(llm, "_chat_multimodal", side_effect=side_effect), \
                 patch("core.llm.openai_proto.extract_frames") as mock_extract:
                frame = Path(tmp) / "frame.jpg"
                frame.write_bytes(b"fake")
                mock_extract.return_value = [frame]

                result = llm.summarize_multimodal("transcript", video, lang="zh", content_type="general")

                assert result == "text fallback"


def test_content_type_routing():
    """content_type is passed through to prompt selection."""
    from core.llm.prompts import get_summary_prompt

    tutorial_prompt = get_summary_prompt("tutorial", "zh")
    general_prompt = get_summary_prompt("general", "zh")

    assert "步骤" in tutorial_prompt or "操作" in tutorial_prompt
    assert tutorial_prompt != general_prompt
    assert "{transcript}" in tutorial_prompt
    assert "{transcript}" in general_prompt


def test_content_types_coverage():
    """All content types have prompts."""
    from core.llm.prompts import CONTENT_TYPES, get_summary_prompt

    for ct in CONTENT_TYPES:
        prompt = get_summary_prompt(ct, "zh")
        assert "{transcript}" in prompt
        prompt_en = get_summary_prompt(ct, "en")
        assert "{transcript}" in prompt_en


# --- Frame extraction tests ---

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


def test_extract_frames_backward_compat():
    """Explicit max_frames > 0 reverts to timestamp mode."""
    from core.vision.frames import extract_frames

    with tempfile.TemporaryDirectory() as tmp:
        video = Path(tmp) / "test.mp4"
        video.write_bytes(b"fake video")

        with patch("core.vision.frames._extract_frames_timestamp", return_value=[]) as mock_ts:
            extract_frames(video, max_frames=10, mode="hybrid")
            mock_ts.assert_called_once()


def test_encode_frame_webp_cmd():
    """_encode_frame builds correct ffmpeg command for webp."""
    from core.vision.frames import _encode_frame

    with tempfile.TemporaryDirectory() as tmp:
        video = Path(tmp) / "test.mp4"
        video.write_bytes(b"fake")
        out_path = Path(tmp) / "frame.webp"

        with patch("core.vision.frames.subprocess.run") as mock_run:
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
