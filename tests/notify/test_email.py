from orbit.notify.email import FakeEmailSender


def test_fake_sender_records_sent_messages() -> None:
    sender = FakeEmailSender()

    sender.send(to="customer@example.com", subject="Hi", body="Body text")

    assert len(sender.sent) == 1
    sent = sender.sent[0]
    assert sent.to == "customer@example.com"
    assert sent.subject == "Hi"
    assert sent.body == "Body text"


def test_fake_sender_records_multiple_messages_in_order() -> None:
    sender = FakeEmailSender()

    sender.send(to="a@example.com", subject="First", body="...")
    sender.send(to="b@example.com", subject="Second", body="...")

    assert [sent.subject for sent in sender.sent] == ["First", "Second"]
