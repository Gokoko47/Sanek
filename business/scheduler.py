"""One sleeping thread for all chat quiet windows; no thread per message or chat."""
from __future__ import annotations
import heapq
import itertools
import logging
import threading
import time


class QuietScheduler:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.condition = threading.Condition()
        self.entries = {}
        self.heap = []
        self.sequence = itertools.count()
        self.closed = False
        self.thread = threading.Thread(target=self._run, name='business-quiet-window', daemon=True)
        self.thread.start()

    def schedule(self, key, delay, callback):
        with self.condition:
            if self.closed:
                return
            seq = next(self.sequence)
            deadline = self.clock() + max(0, delay)
            self.entries[key] = (deadline, seq, callback)
            heapq.heappush(self.heap, (deadline, seq, key))
            if len(self.heap) > len(self.entries)*2+64:
                self.heap = [(d, s, k) for k, (d, s, _) in self.entries.items()]
                heapq.heapify(self.heap)
            self.condition.notify()

    def cancel(self, key):
        with self.condition:
            self.entries.pop(key, None)
            self.condition.notify()

    def cancel_all(self):
        with self.condition:
            self.entries.clear()
            self.heap.clear()
            self.condition.notify()

    def _run(self):
        while True:
            with self.condition:
                if self.closed:
                    return
                while self.heap:
                    deadline, seq, key = self.heap[0]
                    current = self.entries.get(key)
                    if current is None or current[1] != seq:
                        heapq.heappop(self.heap)
                        continue
                    wait = deadline-self.clock()
                    if wait > 0:
                        self.condition.wait(wait)
                        break
                    heapq.heappop(self.heap)
                    self.entries.pop(key, None)
                    callback = current[2]
                    break
                else:
                    self.condition.wait()
                    continue
                if wait > 0:
                    continue
            try:
                callback()
            except Exception:
                logging.getLogger('pakostnik.business').error('Deferred reply callback failed')

    def close(self):
        with self.condition:
            self.closed = True
            self.entries.clear()
            self.heap.clear()
            self.condition.notify_all()
        if self.thread is not threading.current_thread():
            self.thread.join(timeout=2)
