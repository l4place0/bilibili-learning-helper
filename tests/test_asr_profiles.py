from pathlib import Path

from core.asr.profiles import ASR_PROFILES, resolve_asr_profile


def test_profiles_map_to_stable_model_filenames(tmp_path):
    expected = {
        "fast": "ggml-base-q5_1.bin",
        "balanced": "ggml-small-q5_1.bin",
        "accurate": "ggml-medium-q5_0.bin",
    }

    assert set(ASR_PROFILES) == set(expected)
    for name, filename in expected.items():
        profile, path = resolve_asr_profile(name, tmp_path)
        assert profile.name == name
        assert path == Path(tmp_path).resolve() / filename
