from jarvis.core.permissions import needs_confirmation


def test_low_risk_does_not_need_confirmation():
    assert needs_confirmation("low") is False


def test_high_risk_needs_confirmation():
    assert needs_confirmation("high") is True


def test_critical_risk_needs_confirmation():
    assert needs_confirmation("critical") is True
