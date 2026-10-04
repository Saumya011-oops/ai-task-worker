"""Chaos-mode state (CHAOS=1). One instance per process; reset via /__reset."""
import os


class Chaos:
    def __init__(self) -> None:
        self.enabled = os.getenv("CHAOS", "0") == "1"
        self.reset()

    def reset(self) -> None:
        self.post_failed = False   # first POST /erp/bills already answered with 500?
        self.page_views = 0        # authenticated ERP HTML page views
        self.expired_once = False  # session expiry already fired?

    def should_fail_post(self) -> bool:
        """True exactly once: the first bill POST."""
        if self.enabled and not self.post_failed:
            self.post_failed = True
            return True
        return False

    def should_expire_session(self) -> bool:
        """Count a page view; True on the 4th view, once only."""
        if not self.enabled or self.expired_once:
            return False
        self.page_views += 1
        if self.page_views > 3:
            self.expired_once = True
            return True
        return False

    @property
    def save_label(self) -> str:
        return "Create bill" if self.enabled else "Save bill"
