import threading

from eterspire_notifier import alerts
from eterspire_notifier.config import PhoneSettings


def test_sends_to_every_ticked_service(monkeypatch):
    posted = []
    monkeypatch.setattr(alerts, "_post", lambda url, data, headers: posted.append(url))
    phone = PhoneSettings(
        use_ntfy=True,
        use_discord=True,
        use_telegram=True,
        ntfy_topic="eterspire-test",
        discord_webhook="https://discord.com/api/webhooks/1/abc",
        telegram_token="123:abc",
        telegram_chat_id="42",
    )
    results = {}
    done = threading.Event()

    def on_done(service, error):
        results[service] = error
        if len(results) == 3:
            done.set()

    assert alerts.send_phone_async(phone, "Title", "Message", on_done=on_done) == ["ntfy", "discord", "telegram"]
    assert done.wait(5)
    assert results == {"ntfy": None, "discord": None, "telegram": None}
    assert sorted(posted) == [
        "https://api.telegram.org/bot123:abc/sendMessage",
        "https://discord.com/api/webhooks/1/abc",
        "https://ntfy.sh/eterspire-test",
    ]


def test_unticked_services_are_skipped_and_errors_reported(monkeypatch):
    monkeypatch.setattr(alerts, "_post", lambda *a: None)
    phone = PhoneSettings(use_ntfy=False, use_discord=True)  # no webhook pasted
    assert alerts.enabled_services(phone) == ["discord"]
    results = {}
    done = threading.Event()
    alerts.send_phone_async(phone, "T", "M", on_done=lambda s, e: (results.update({s: e}), done.set()))
    assert done.wait(5)
    assert "webhook" in results["discord"]


def test_nothing_ticked_sends_nothing():
    assert alerts.send_phone_async(PhoneSettings(use_ntfy=False), "T", "M") == []
