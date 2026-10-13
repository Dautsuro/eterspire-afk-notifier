import json

from eterspire_notifier import config


def test_round_trip_and_bad_values(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    s = config.load()
    assert s.phone.ntfy_topic.startswith("eterspire-")
    s.spot_empty.phone = True
    s.spot_empty.phone_delay = 45
    config.save(s)
    assert config.load().spot_empty.phone_delay == 45

    data = json.loads(config.config_path().read_text())
    data["volume"] = "loud"  # wrong type: ignored
    data["spot_empty"]["phone"] = 1  # not a bool: ignored, back to the default
    data["unknown"] = 1
    config.config_path().write_text(json.dumps(data))
    loaded = config.load()
    assert loaded.volume == 80
    assert loaded.spot_empty.phone is False
    assert loaded.spot_empty.phone_delay == 45


def test_corrupt_file_gives_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    config.config_path().write_text("{not json")
    assert config.load().volume == 80


def test_single_service_from_1_0_0_is_migrated(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    config.config_path().write_text(json.dumps({"phone": {"service": "discord", "discord_webhook": "https://x"}}))
    phone = config.load().phone
    assert (phone.use_ntfy, phone.use_discord, phone.use_telegram) == (False, True, False)
    assert phone.discord_webhook == "https://x"
