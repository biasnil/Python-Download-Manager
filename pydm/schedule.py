"""ScheduleManager: the timed download queue and 'when finished' power actions."""

from __future__ import annotations

from PyQt6.QtCore import QObject, QTimer
from datetime import datetime

from .config import Settings
from .models import ACTIVE_STATES, DownloadTask, TaskState
from .power import PowerCountdownDialog, PowerManager



class ScheduleManager(QObject):
    """Starts the scheduled queue at the configured time/days, stops it at the
    stop time (unfinished items go back to the schedule) and runs the chosen
    power action when everything is done."""

    def __init__(self, window, cfg: Settings):
        super().__init__(window)
        self.w, self.cfg = window, cfg
        self.running: set[str] = set()        # tasks started by the schedule
        self.reschedule: set[str] = set()     # paused by "stop at" → back to Scheduled
        self.when_done_once = "nothing"       # Tools → When All Downloads Finish
        self._fired: dict[str, str] = {}
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(15_000)

    @staticmethod
    def time_reached(hhmm: str, now: datetime) -> bool:
        try:
            t = datetime.strptime(hhmm, "%H:%M")
        except ValueError:
            return False
        target = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
        return 0 <= (now - target).total_seconds() < 120

    def tick(self) -> None:
        c = self.cfg
        now = datetime.now()
        today = now.date().isoformat()
        if not c.sched_enabled or now.weekday() not in c.sched_days:
            return
        if self.time_reached(c.sched_start, now) and self._fired.get("start") != today:
            self._fired["start"] = today
            self.start()
        if (c.sched_stop and self.time_reached(c.sched_stop, now)
                and self._fired.get("stop") != today):
            self._fired["stop"] = today
            if self.running:
                self.stop()

    def start(self) -> None:
        w = self.w
        tasks = [t for t in w.tasks.values() if t.state == TaskState.SCHEDULED]
        if not tasks:
            w.statusBar().showMessage("The schedule is empty — use “Download Later” "
                                      "or right-click → Add to Schedule", 6000)
            return
        for t in tasks:
            t.state = TaskState.QUEUED          # immediately, so "all done" can't misfire
            self.running.add(t.id)
            w.enqueue_task(t)
            w._on_task_updated(t)
        w.tray.notify("Scheduled queue started", f"{len(tasks)} download(s)")
        w._refresh_actions()

    def stop(self) -> None:
        w = self.w
        for tid in list(self.running):
            t = w.tasks.get(tid)
            if t and (t.state in ACTIVE_STATES or t.state == TaskState.QUEUED):
                self.reschedule.add(tid)
                w.pause_task(t)
        self.running.clear()
        w.tray.notify("Scheduled queue stopped", "Unfinished downloads went back to the schedule")
        w._refresh_actions()

    def take_rescheduled(self, task: DownloadTask) -> bool:
        """A task paused by 'stop at' becomes Scheduled again. Returns True if so."""
        if task.id in self.reschedule and task.state == TaskState.PAUSED:
            self.reschedule.discard(task.id)
            task.state = TaskState.SCHEDULED
            return True
        return False

    def forget(self, task_id: str) -> None:
        self.running.discard(task_id)
        self.reschedule.discard(task_id)

    def check_all_done(self) -> None:
        w = self.w
        busy = ACTIVE_STATES | {TaskState.QUEUED}
        if self.running:
            ts = [w.tasks.get(i) for i in self.running]
            if not any(t and t.state in busy for t in ts):
                self.running.clear()
                w.tray.notify("Scheduled queue finished", "All scheduled downloads are done")
                self.run_power_action(self.cfg.sched_when_done)
                return
        if self.when_done_once != "nothing" and not any(
                t.state in busy for t in w.tasks.values()):
            action = self.when_done_once
            self.when_done_once = "nothing"
            w.when_done_actions["nothing"].setChecked(True)
            self.run_power_action(action)

    def run_power_action(self, action: str) -> None:
        if action == "nothing":
            return

        def confirm(a):
            if a == "exit":
                self.w.quit_app()
                return
            if a in ("shutdown", "hibernate"):
                self.w._save_everything()
            PowerManager.perform(a)
        PowerCountdownDialog(action, confirm, 60, self.w).show()
