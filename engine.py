import logging
import threading

from config_store import DATA_DIR
from managers.telegram_manager import TelegramManager
from managers.worker import Worker


class MonitorEngine:
    """Starts one Worker thread per enabled search and stops them all together."""

    def __init__(self, cfg, emit):
        self.logger = logging.getLogger(__name__)
        self._cfg = cfg
        self._emit = emit
        self._stop = threading.Event()
        self._threads = []

    def start(self):
        tg = self._cfg['telegram']
        telegram = None
        if tg.get('enabled') and tg.get('token') and tg.get('channel'):
            telegram = TelegramManager(tg['token'], tg['channel'])
        else:
            self.logger.info("Telegram alerts are off - new listings will only show in the app")

        searches = [s for s in self._cfg['searches'] if s.get('enabled') and s.get('search_query')]
        for s in searches:
            w = Worker(s, telegram=telegram,
                       interval_seconds=float(self._cfg.get('interval_minutes', 5)) * 60,
                       data_dir=DATA_DIR,
                       stop_event=self._stop, emit=self._emit)
            t = threading.Thread(target=w.run, name=f"worker-{w.id}", daemon=True)
            t.start()
            self._threads.append(t)
        self.logger.info(f"Monitor started with {len(searches)} search(es)")
        return len(searches)

    def stop(self):
        self._stop.set()
        self.logger.info("Stopping monitor…")

    @property
    def running(self):
        return any(t.is_alive() for t in self._threads)
