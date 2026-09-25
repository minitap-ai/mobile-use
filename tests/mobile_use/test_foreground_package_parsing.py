from minitap.mobile_use.controllers.platform_specific_commands_controller import (
    parse_android_foreground_package,
)

CHROME_ACTIVITY = (
    "  mFocusedApp=ActivityRecord{403f607 u0 com.android.chrome/"
    "org.chromium.chrome.browser.ChromeTabbedActivity t31}"
)


def test_activity_window_reports_its_package():
    output = (
        "  mCurrentFocus=Window{2d598a3 u0 com.android.chrome/"
        "org.chromium.chrome.browser.ChromeTabbedActivity}\n" + CHROME_ACTIVITY
    )

    assert parse_android_foreground_package(output) == "com.android.chrome"


def test_a_popup_menu_belongs_to_the_focused_app():
    # Captured from an Android 15 emulator with Chrome's overflow menu open.
    output = "  mCurrentFocus=Window{ba11684 u0 PopupWindow:13bc602}\n" + CHROME_ACTIVITY

    assert parse_android_foreground_package(output) == "com.android.chrome"


def test_other_windows_without_a_package_stay_unknown():
    output = "  mCurrentFocus=Window{7f1 u0 NotificationShade}\n" + CHROME_ACTIVITY

    assert parse_android_foreground_package(output) is None


def test_null_focus_stays_none_while_an_app_is_loading():
    output = "  mCurrentFocus=null\n" + CHROME_ACTIVITY

    assert parse_android_foreground_package(output) is None


def test_another_apps_window_is_reported_as_that_app():
    output = (
        "  mCurrentFocus=Window{9a u0 com.google.android.gm/"
        "com.google.android.gm.ComposeActivityGmailExternal}\n" + CHROME_ACTIVITY
    )

    assert parse_android_foreground_package(output) == "com.google.android.gm"


def test_a_popup_without_a_focused_app_is_unknown():
    assert (
        parse_android_foreground_package("  mCurrentFocus=Window{ba1 u0 PopupWindow:13bc602}")
        is None
    )


def test_missing_focus_line_is_unknown():
    assert parse_android_foreground_package("") is None
