"""
Clue UI — macOS Persistent Floating Overlay Panel Utility
Screen-Share Invisibility (NSWindowSharingNone) + 0x151 Multi-Space Stickiness + SkyLight kCGSTagSticky
"""

import sys
from typing import Optional

# ── Collection Behavior Constants (AppKit/NSWindow.h) ────────────────────────
CAN_JOIN_ALL_SPACES    = 1 << 0   # 0x01  — visible on every desktop/Space
MOVE_TO_ACTIVE_SPACE   = 1 << 1   # 0x02  — move to whichever Space is active
STATIONARY             = 1 << 4   # 0x10  — stay in place during Space-switch
IGNORES_CYCLE          = 1 << 6   # 0x40  — skip Cmd+` window cycling
FULL_SCREEN_AUXILIARY  = 1 << 8   # 0x100 — overlay fullscreen apps (NSPanel)

# 0x151 = 337: Persistent overlay multi-Space stickiness
OVERLAY_COLLECTION_BEHAVIOR = (
    CAN_JOIN_ALL_SPACES | STATIONARY | IGNORES_CYCLE | FULL_SCREEN_AUXILIARY
)

# Window Levels
NS_NORMAL_WINDOW_LEVEL       = 0
NS_FLOATING_WINDOW_LEVEL     = 3
NS_STATUS_WINDOW_LEVEL       = 25
NS_SCREEN_SAVER_WINDOW_LEVEL = 1000  # Stealth maximum z-order

_activation_policy_set = False


def ensure_accessory_policy() -> None:
    """
    Set application activation policy to NSApplicationActivationPolicyAccessory.
    Critical on macOS 15+ (Sequoia) & 26+ so windows appear over fullscreen Spaces
    and follow the user across all virtual desktops.
    """
    global _activation_policy_set
    if _activation_policy_set or sys.platform != "darwin":
        return

    try:
        from AppKit import NSApp
        if NSApp:
            # 1 = NSApplicationActivationPolicyAccessory
            NSApp.setActivationPolicy_(1)
            _activation_policy_set = True
    except Exception as e:
        print(f"  ⚠️ overlay_panel: Could not set activation policy: {e}")


def get_nswindow_from_widget(qt_widget):
    """Retrieve the backing native NSWindow from a PyQt6 widget."""
    if sys.platform != "darwin":
        return None

    cached = getattr(qt_widget, "_cached_ns_window", None)
    if cached:
        return cached

    try:
        import objc
        from ctypes import c_void_p
        from AppKit import NSApp

        view_ptr = int(qt_widget.winId())
        ns_view = objc.objc_object(c_void_p=view_ptr)
        ns_window = ns_view.window() if hasattr(ns_view, "window") else None

        if not ns_window and NSApp:
            target_title = qt_widget.windowTitle()
            for win in NSApp.windows():
                if target_title and target_title in (win.title() or ""):
                    ns_window = win
                    break
                frame = win.frame()
                if (abs(frame.size.width - qt_widget.width()) < 10 and
                        abs(frame.size.height - qt_widget.height()) < 10):
                    ns_window = win
                    break

        if ns_window:
            qt_widget._cached_ns_window = ns_window
        return ns_window
    except Exception as e:
        print(f"  ⚠️ Could not retrieve NSWindow: {e}")
        return None


def configure_overlay_panel(
    qt_widget,
    level: int = 1000,
    can_become_key: bool = True,
    screen_share_invisible: bool = True,
    window_title_hint: Optional[str] = None,
) -> bool:
    """
    Configure a QWidget's backing NSWindow as a sticky floating panel that
    follows the user across ALL virtual desktops/Spaces and stays invisible to screen share.
    """
    if sys.platform != "darwin":
        return False

    ensure_accessory_policy()

    if window_title_hint:
        qt_widget.setWindowTitle(window_title_hint)

    ns_window = get_nswindow_from_widget(qt_widget)
    if not ns_window:
        return False

    try:
        import objc

        # 1. NSPanel properties
        is_panel = ns_window.isKindOfClass_(objc.lookUpClass("NSPanel")) if objc else False
        if is_panel:
            if hasattr(ns_window, "setFloatingPanel_"):
                ns_window.setFloatingPanel_(True)
            if hasattr(ns_window, "setWorksWhenModal_"):
                ns_window.setWorksWhenModal_(True)
            if hasattr(ns_window, "setBecomesKeyOnlyIfNeeded_"):
                ns_window.setBecomesKeyOnlyIfNeeded_(not can_become_key)

        # 2. Collection Behavior 0x151 (CAN_JOIN_ALL_SPACES | STATIONARY | IGNORES_CYCLE | FULL_SCREEN_AUXILIARY)
        # This makes the window follow across EVERY virtual desktop/Space!
        if hasattr(ns_window, "setCollectionBehavior_"):
            ns_window.setCollectionBehavior_(OVERLAY_COLLECTION_BEHAVIOR)

        # 3. Window Level (Floating above everything)
        if hasattr(ns_window, "setLevel_"):
            ns_window.setLevel_(level)

        # 4. Don't hide when app loses focus or switches spaces
        if hasattr(ns_window, "setHidesOnDeactivate_"):
            ns_window.setHidesOnDeactivate_(False)

        if hasattr(ns_window, "setCanHide_"):
            ns_window.setCanHide_(False)

        if hasattr(ns_window, "setAnimationBehavior_"):
            ns_window.setAnimationBehavior_(0)

        # 5. Prevent focus stealing if desired
        if ns_window.respondsToSelector_(b"_setPreventsActivation:"):
            ns_window._setPreventsActivation_(not can_become_key)

        # 6. Bring front without activating
        if hasattr(ns_window, "orderFrontRegardless"):
            ns_window.orderFrontRegardless()

        # 7. Screen-Share Invisibility (NSWindowSharingNone = 0)
        if screen_share_invisible and hasattr(ns_window, "setSharingType_"):
            ns_window.setSharingType_(0)
            ns_window.orderFrontRegardless()

        # 8. SkyLight Private Framework: Physical OS-level Sticky Tag (0x800)
        try:
            from ctypes import cdll, c_int, c_int64, byref
            skylight = cdll.LoadLibrary("/System/Library/PrivateFrameworks/SkyLight.framework/SkyLight")
            skylight._CGSDefaultConnection.restype = c_int
            cgs_conn = skylight._CGSDefaultConnection()
            wid = ns_window.windowNumber()

            kCGSTagSticky = c_int64(0x800)  # kCGSTagSticky = appear on all desktops/Spaces
            skylight.SLSSetWindowTags(c_int(cgs_conn), c_int(wid), byref(kCGSTagSticky), c_int(64))
            skylight.SLSSetWindowLevel(c_int(cgs_conn), c_int(wid), c_int(level))

            qt_widget._skylight = skylight
            qt_widget._cgs_conn = cgs_conn
            qt_widget._window_id = wid
            ns_window.orderFrontRegardless()
        except Exception:
            pass

        return True

    except Exception as e:
        print(f"  ⚠️ overlay_panel configuration error: {e}")
        return False


def reassert_overlay(qt_widget) -> None:
    """
    Reassert window level, stickiness, and orderFront on macOS Space changes.
    Called periodically or on desktop switch.
    """
    if sys.platform != "darwin":
        return

    ns_window = get_nswindow_from_widget(qt_widget)
    if not ns_window:
        return

    try:
        # Reassert collection behavior and level
        ns_window.setCollectionBehavior_(OVERLAY_COLLECTION_BEHAVIOR)
        ns_window.setLevel_(1000)
        ns_window.orderFrontRegardless()

        # Reassert SkyLight sticky tag
        skylight = getattr(qt_widget, "_skylight", None)
        cgs_conn = getattr(qt_widget, "_cgs_conn", None)
        wid = getattr(qt_widget, "_window_id", None)
        if skylight and cgs_conn and wid:
            from ctypes import c_int, c_int64, byref
            kCGSTagSticky = c_int64(0x800)
            skylight.SLSSetWindowTags(c_int(cgs_conn), c_int(wid), byref(kCGSTagSticky), c_int(64))
            skylight.SLSSetWindowLevel(c_int(cgs_conn), c_int(wid), c_int(1000))
    except Exception:
        pass


def clamp_to_visible_screen(qt_widget) -> None:
    """Ensure the floating widget is positioned within visible display bounds."""
    try:
        from PyQt6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geo = screen.availableGeometry()
        x = max(geo.left(), min(qt_widget.x(), geo.right() - qt_widget.width()))
        y = max(geo.top(), min(qt_widget.y(), geo.bottom() - qt_widget.height()))
        qt_widget.move(x, y)
    except Exception:
        pass
