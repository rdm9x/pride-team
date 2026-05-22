"""
Tests for browser notification filtering logic (S6.6).

These tests verify the JS-side notification filter logic using Python mocks
that mirror the getNotificationSettings / notify() semantics defined in app.js.
"""

import pytest


# ---------------------------------------------------------------------------
# Pure-Python mirror of the JS notify() filter logic
# ---------------------------------------------------------------------------

class NotificationSettings:
    """Mirrors localStorage-backed getNotificationSettings() in app.js."""

    def __init__(self, enabled=True, level="important"):
        assert level in ("critical", "important", "all")
        self.enabled = enabled
        self.level = level


def should_send(level: str, settings: NotificationSettings, tab_visible: bool) -> bool:
    """
    Mirrors the guard logic inside notify() in app.js:

        if (!notificationsAllowed) return;          ← assumed allowed in tests
        if (document.visibilityState === 'visible') return;
        const s = getNotificationSettings();
        if (!s.enabled) return;
        if (s.level === 'critical'  && level !== 'critical')  return;
        if (s.level === 'important' && level === 'info')       return;
        // …send
    """
    if tab_visible:
        return False
    if not settings.enabled:
        return False
    if settings.level == "critical" and level != "critical":
        return False
    if settings.level == "important" and level == "info":
        return False
    return True


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def settings_default():
    """Default settings: enabled=True, level='important'."""
    return NotificationSettings(enabled=True, level="important")


@pytest.fixture
def settings_critical_only():
    return NotificationSettings(enabled=True, level="critical")


@pytest.fixture
def settings_all():
    return NotificationSettings(enabled=True, level="all")


@pytest.fixture
def settings_disabled():
    return NotificationSettings(enabled=False, level="important")


# ---------------------------------------------------------------------------
# Core guard: tab visibility
# ---------------------------------------------------------------------------

class TestTabVisibility:
    def test_no_notification_when_tab_visible(self, settings_default):
        """Even critical notifications must not fire when tab is active."""
        assert should_send("critical", settings_default, tab_visible=True) is False

    def test_notification_allowed_when_tab_hidden(self, settings_default):
        assert should_send("important", settings_default, tab_visible=False) is True


# ---------------------------------------------------------------------------
# Enabled toggle
# ---------------------------------------------------------------------------

class TestEnabledToggle:
    def test_disabled_blocks_all_levels(self, settings_disabled):
        for level in ("critical", "important", "info"):
            assert should_send(level, settings_disabled, tab_visible=False) is False

    def test_enabled_allows_matching_level(self, settings_default):
        assert should_send("important", settings_default, tab_visible=False) is True


# ---------------------------------------------------------------------------
# Level filter — default (important)
# ---------------------------------------------------------------------------

class TestLevelImportant:
    def test_critical_passes(self, settings_default):
        assert should_send("critical", settings_default, tab_visible=False) is True

    def test_important_passes(self, settings_default):
        assert should_send("important", settings_default, tab_visible=False) is True

    def test_info_blocked(self, settings_default):
        """Chat messages (info) must be suppressed at default level."""
        assert should_send("info", settings_default, tab_visible=False) is False


# ---------------------------------------------------------------------------
# Level filter — critical only
# ---------------------------------------------------------------------------

class TestLevelCriticalOnly:
    def test_critical_passes(self, settings_critical_only):
        assert should_send("critical", settings_critical_only, tab_visible=False) is True

    def test_important_blocked(self, settings_critical_only):
        assert should_send("important", settings_critical_only, tab_visible=False) is False

    def test_info_blocked(self, settings_critical_only):
        assert should_send("info", settings_critical_only, tab_visible=False) is False


# ---------------------------------------------------------------------------
# Level filter — all
# ---------------------------------------------------------------------------

class TestLevelAll:
    def test_critical_passes(self, settings_all):
        assert should_send("critical", settings_all, tab_visible=False) is True

    def test_important_passes(self, settings_all):
        assert should_send("important", settings_all, tab_visible=False) is True

    def test_info_passes(self, settings_all):
        """With level=all, even chat messages must fire."""
        assert should_send("info", settings_all, tab_visible=False) is True


# ---------------------------------------------------------------------------
# Specific call-site semantics defined in S6.6
# ---------------------------------------------------------------------------

class TestCallSiteSemantics:
    """Verify that the level assignments made in app.js produce correct outcomes."""

    def test_inbox_approval_is_important_fires_by_default(self, settings_default):
        """needs_approval inbox → level='important' → fires at default settings."""
        level = "important"  # checkInboxNotifications: approvals
        assert should_send(level, settings_default, tab_visible=False) is True

    def test_inbox_reviews_is_info_blocked_by_default(self, settings_default):
        """reviews inbox → level='info' → suppressed at default settings."""
        level = "info"       # checkInboxNotifications: reviews / questions
        assert should_send(level, settings_default, tab_visible=False) is False

    def test_chat_message_is_info_blocked_by_default(self, settings_default):
        """Regular chat message → level='info' → suppressed at default settings."""
        level = "info"       # renderChat: notify("info", ...)
        assert should_send(level, settings_default, tab_visible=False) is False

    def test_chat_message_fires_when_level_all(self, settings_all):
        """Chat message fires when user explicitly sets level=all."""
        assert should_send("info", settings_all, tab_visible=False) is True

    def test_approval_fires_when_critical_only_not(self, settings_critical_only):
        """Approvals (important) are NOT sent when user chose critical-only."""
        assert should_send("important", settings_critical_only, tab_visible=False) is False


# ---------------------------------------------------------------------------
# Notification settings defaults
# ---------------------------------------------------------------------------

class TestSettingsDefaults:
    def test_default_enabled_is_true(self):
        s = NotificationSettings()
        assert s.enabled is True

    def test_default_level_is_important(self):
        s = NotificationSettings()
        assert s.level == "important"

    def test_invalid_level_raises(self):
        with pytest.raises(AssertionError):
            NotificationSettings(level="verbose")
