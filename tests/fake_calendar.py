"""
Giả lập Google Calendar API v3, đủ bề mặt cho những gì agent dùng.

Có bộ này bạn kiểm chứng được toàn bộ logic sync, chống vòng lặp và các
cầu dao an toàn mà không cần tài khoản Google, không cần mạng, và quan
trọng nhất: không cần rủi ro nghịch vào lịch thật.
"""

import copy
import itertools
from datetime import datetime, timezone


class FakeHttpError(Exception):
    def __init__(self, status, msg=""):
        super().__init__(f"{status} {msg}")
        self.resp = type("R", (), {"status": status})()


class _Req:
    def __init__(self, fn):
        self._fn = fn

    def execute(self):
        return self._fn()


class FakeCalendar:
    def __init__(self):
        self.store = {}                 # id -> event dict
        self.version = 0                # tăng mỗi lần có thay đổi
        self.changed_at = {}            # id -> version
        self.valid_from = 0             # token cũ hơn mốc này -> 410
        self._ids = itertools.count(1)
        self.calls = {"list": 0, "insert": 0, "patch": 0, "delete": 0}

    # ---------------------------------------------------------- tiện ích test
    def seed(self, summary, start_iso, end_iso, private=None, ev_id=None):
        ev_id = ev_id or f"ev{next(self._ids)}"
        self.version += 1
        ev = {
            "id": ev_id,
            "summary": summary,
            "status": "confirmed",
            "start": {"dateTime": start_iso},
            "end": {"dateTime": end_iso},
            "updated": datetime.now(timezone.utc).isoformat(),
        }
        if private:
            ev["extendedProperties"] = {"private": private}
        self.store[ev_id] = ev
        self.changed_at[ev_id] = self.version
        return ev

    def expire_tokens(self):
        """Mô phỏng syncToken hết hạn -> lần list tới trả 410."""
        self.valid_from = self.version + 1

    # ------------------------------------------------------------------- API
    def events(self):
        return self

    def list(self, **params):
        return _Req(lambda: self._list(params))

    def _list(self, params):
        self.calls["list"] += 1
        token = params.get("syncToken")

        if token is not None:
            since = int(token.split(":")[1])
            if since < self.valid_from:
                raise FakeHttpError(410, "Sync token is no longer valid")
            items = [copy.deepcopy(e) for eid, e in self.store.items()
                     if self.changed_at.get(eid, 0) > since]
        else:
            items = [copy.deepcopy(e) for e in self.store.values()]

        if not params.get("showDeleted"):
            items = [e for e in items if e.get("status") != "cancelled"]

        return {"items": items, "nextSyncToken": f"tok:{self.version}"}

    def insert(self, calendarId, body):
        def _do():
            self.calls["insert"] += 1
            self.version += 1
            ev_id = f"ev{next(self._ids)}"
            ev = copy.deepcopy(body)
            ev.update({"id": ev_id, "status": "confirmed",
                       "updated": datetime.now(timezone.utc).isoformat()})
            self.store[ev_id] = ev
            self.changed_at[ev_id] = self.version
            return copy.deepcopy(ev)
        return _Req(_do)

    def patch(self, calendarId, eventId, body):
        def _do():
            self.calls["patch"] += 1
            if eventId not in self.store:
                raise FakeHttpError(404, "Not Found")
            self.version += 1
            self.store[eventId].update(copy.deepcopy(body))
            self.store[eventId]["updated"] = datetime.now(timezone.utc).isoformat()
            self.changed_at[eventId] = self.version
            return copy.deepcopy(self.store[eventId])
        return _Req(_do)

    def delete(self, calendarId, eventId):
        def _do():
            self.calls["delete"] += 1
            if eventId not in self.store:
                raise FakeHttpError(404, "Not Found")
            self.version += 1
            self.store[eventId]["status"] = "cancelled"
            self.changed_at[eventId] = self.version
            return ""
        return _Req(_do)
