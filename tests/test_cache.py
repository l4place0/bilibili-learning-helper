import json
import time

from core.cache import CacheStore, derived_key, media_key


def test_stable_media_key_ignores_signed_url():
    first = media_key("bilibili", "BV123", quality="720p")
    second = media_key("bilibili", "BV123", quality="720p")
    assert first == second
    assert len(first) == 64


def test_cache_put_get_and_materialize(tmp_path):
    store = CacheStore(tmp_path / "cache")
    source = tmp_path / "audio.wav"
    source.write_bytes(b"audio")
    key = derived_key("parent", "audio", codec="pcm")

    stored = store.put_path(key, "audio", source)
    found = store.get(key)
    target = tmp_path / "work" / "audio.wav"

    assert stored.key == key
    assert found is not None
    assert store.materialize_file(found, target).read_bytes() == b"audio"
    assert store.status()["by_kind"] == {"audio": 1}


def test_cache_json_and_prune_expired(tmp_path):
    store = CacheStore(tmp_path / "cache")
    key = derived_key("parent", "transcript", model="small")
    store.put_json(key, "transcript", {"text": "hello"}, ttl_seconds=-1)

    assert store.read_json(key) is None
    result = store.prune()
    assert result["deleted"] == 0


def test_cache_list_serializes_entries(tmp_path):
    store = CacheStore(tmp_path / "cache")
    key = derived_key("parent", "metadata")
    store.put_json(key, "metadata", {"title": "test"})

    payload = json.dumps(store.list()[0].to_dict())
    assert key in payload
    assert store.list()[0].last_access <= time.time()
