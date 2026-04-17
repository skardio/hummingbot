import threading
from typing import TYPE_CHECKING

from hummingbot.core.utils.async_utils import safe_ensure_future
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase

if TYPE_CHECKING:
    from hummingbot.client.hummingbot_application import HummingbotApplication  # noqa: F401


class GracefulStopCommand:
    def graceful_stop(self: "HummingbotApplication"):
        if threading.current_thread() != threading.main_thread():
            self.ev_loop.call_soon_threadsafe(self.graceful_stop)
            return
        safe_ensure_future(self.graceful_stop_loop(), loop=self.ev_loop)

    async def graceful_stop_loop(self: "HummingbotApplication"):
        strategy = self.trading_core.strategy
        if not strategy or not isinstance(strategy, ScriptStrategyBase):
            self.notify("No active strategy running.")
            return

        controllers = getattr(strategy, "controllers", {})
        if not controllers:
            self.notify("No controllers found — use 'stop' instead.")
            return

        flagged = 0
        for name, controller in controllers.items():
            if hasattr(controller, "_graceful_stop_requested"):
                if controller._graceful_stop_requested:
                    self.notify(f"Graceful stop already active for '{name}'.")
                else:
                    controller._graceful_stop_requested = True
                    flagged += 1
                    self.notify(
                        f"⏳ Graceful stop activated for '{name}' — "
                        f"no new trades will open. Active executors will finish naturally."
                    )
            else:
                self.notify(f"Controller '{name}' does not support graceful stop.")

        if flagged:
            self.notify(
                "Run 'status' to monitor progress. "
                "Once all executors finish, run 'stop' to shut down."
            )
