import json
import logging
import sqlite3
import threading
import time
from pathlib import Path

from src.match import normalize
from src.targets import KEYWORDS, TOPICS

log = logging.getLogger("kimparser")

WEEK_SECONDS = 7 * 24 * 60 * 60
_KEEP_DELIVERY_SECONDS = 3 * 24 * 60 * 60


class Database:
    def __init__(self, path):
        self.path = Path(path)
        if self.path.parent and not self.path.parent.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(
            str(self.path),
            check_same_thread=False,
            isolation_level=None,
            timeout=30,
        )
        self.conn.row_factory = sqlite3.Row
        with self._lock:
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.execute("PRAGMA busy_timeout=5000")
            self.conn.execute("PRAGMA journal_mode=WAL").fetchone()
            self.conn.execute("PRAGMA synchronous=FULL")
            self._create()
            self.conn.execute("UPDATE deliveries SET sent=0 WHERE sent=2")
        self._chmod()

    def prepare_user(self, user_id, now=None):
        moment = _moment(now)

        def run():
            return self._seed(int(user_id), moment)

        return self._transaction(run)

    def counts(self, user_id):
        def run():
            chats = self.conn.execute(
                "SELECT COUNT(*) AS n FROM chats WHERE user_id=?",
                (int(user_id),),
            ).fetchone()["n"]
            words = self.conn.execute(
                "SELECT COUNT(*) AS n FROM keywords WHERE user_id=?",
                (int(user_id),),
            ).fetchone()["n"]
            return chats, words

        return self._read(run)

    def list_chats(self, user_id):
        def run():
            rows = self.conn.execute(
                "SELECT * FROM chats WHERE user_id=? ORDER BY id",
                (int(user_id),),
            ).fetchall()
            return [dict(row) for row in rows]

        return self._read(run)

    def list_keywords(self, user_id):
        def run():
            rows = self.conn.execute(
                "SELECT * FROM keywords WHERE user_id=? ORDER BY id",
                (int(user_id),),
            ).fetchall()
            return [dict(row) for row in rows]

        return self._read(run)

    def all_chats(self):
        def run():
            rows = self.conn.execute("SELECT * FROM chats ORDER BY id").fetchall()
            return [dict(row) for row in rows]

        return self._read(run)

    def add_chat(
        self,
        user_id,
        link,
        title,
        status,
        username=None,
        peer_id=None,
        topic_id=None,
        topic_title=None,
        invite_hash=None,
        now=None,
    ):
        moment = _moment(now)

        def run():
            cursor = self.conn.execute(
                """INSERT INTO chats(
                    user_id, peer_id, username, title, topic_id, topic_title,
                    link, invite_hash, status, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    int(user_id),
                    peer_id,
                    username.lower() if username else None,
                    title or link,
                    topic_id,
                    topic_title or None,
                    link,
                    invite_hash,
                    status,
                    moment,
                ),
            )
            return cursor.lastrowid

        return self._transaction(run)

    def update_chat(self, chat_id, **fields):
        allowed = (
            "peer_id",
            "username",
            "title",
            "topic_id",
            "topic_title",
            "link",
            "invite_hash",
            "status",
        )
        keys = [key for key in allowed if key in fields]
        if not keys:
            return
        if "username" in fields and fields["username"]:
            fields["username"] = fields["username"].lower()
        values = [fields[key] for key in keys]
        values.append(chat_id)
        sql = "UPDATE chats SET " + ", ".join("{}=?".format(key) for key in keys) + " WHERE id=?"

        def run():
            self.conn.execute(sql, values)

        self._transaction(run)

    def same_chat(self, user_id, peer_id, topic_id):
        if peer_id is None:
            return False

        def run():
            for row in self.conn.execute(
                "SELECT topic_id FROM chats WHERE user_id=? AND peer_id=?",
                (int(user_id), peer_id),
            ):
                if row["topic_id"] == topic_id:
                    return True
            return False

        return self._read(run)

    def same_link(self, user_id, link):
        if not link:
            return False

        def run():
            row = self.conn.execute(
                "SELECT 1 AS x FROM chats WHERE user_id=? AND lower(link)=lower(?) LIMIT 1",
                (int(user_id), link),
            ).fetchone()
            return row is not None

        return self._read(run)

    def same_invite(self, user_id, invite_hash):
        if not invite_hash:
            return False

        def run():
            row = self.conn.execute(
                "SELECT 1 AS x FROM chats WHERE user_id=? AND invite_hash=? LIMIT 1",
                (int(user_id), invite_hash),
            ).fetchone()
            return row is not None

        return self._read(run)

    def delete_chat(self, user_id, chat_id):
        def run():
            row = self.conn.execute(
                "SELECT * FROM chats WHERE id=? AND user_id=?",
                (chat_id, int(user_id)),
            ).fetchone()
            if row is None:
                return None
            self.conn.execute(
                "DELETE FROM chats WHERE id=? AND user_id=?",
                (chat_id, int(user_id)),
            )
            return dict(row)

        return self._transaction(run)

    def peer_in_use(self, peer_id):
        if peer_id is None:
            return False

        def run():
            row = self.conn.execute(
                """SELECT 1 AS x FROM chats
                   WHERE peer_id=? AND status!='failed' LIMIT 1""",
                (peer_id,),
            ).fetchone()
            return row is not None

        return self._read(run)

    def peer_by_username(self, username):
        if not username:
            return None

        def run():
            row = self.conn.execute(
                """SELECT peer_id FROM chats
                   WHERE username=? AND peer_id IS NOT NULL LIMIT 1""",
                (username.lower(),),
            ).fetchone()
            return row["peer_id"] if row else None

        return self._read(run)

    def add_keyword(self, user_id, raw, now=None):
        text = " ".join((raw or "").split())
        if not text:
            return "Пришлите слово."
        if len(text) > 80:
            return "Слишком длинное слово."
        norm = normalize(text)
        if len(norm) < 2:
            return "Слишком короткое слово."
        moment = _moment(now)

        def run():
            found = self.conn.execute(
                "SELECT 1 AS x FROM keywords WHERE user_id=? AND norm=? LIMIT 1",
                (int(user_id), norm),
            ).fetchone()
            if found:
                return "Такое слово уже есть."
            self.conn.execute(
                "INSERT INTO keywords(user_id, keyword, norm, created_at) VALUES(?, ?, ?, ?)",
                (int(user_id), text, norm, moment),
            )
            return None

        return self._transaction(run)

    def delete_keyword(self, user_id, keyword_id):
        def run():
            cursor = self.conn.execute(
                "DELETE FROM keywords WHERE id=? AND user_id=?",
                (keyword_id, int(user_id)),
            )
            return cursor.rowcount > 0

        return self._transaction(run)

    def set_wizard(self, user_id, mode, ids):
        payload = json.dumps([int(item) for item in ids])

        def run():
            self.conn.execute(
                "UPDATE users SET wizard=?, wizard_payload=? WHERE user_id=?",
                (mode, payload, int(user_id)),
            )

        self._transaction(run)

    def clear_wizard(self, user_id):
        def run():
            self.conn.execute(
                "UPDATE users SET wizard=NULL, wizard_payload='[]' WHERE user_id=?",
                (int(user_id),),
            )

        self._transaction(run)

    def wizard(self, user_id):
        def run():
            row = self.conn.execute(
                "SELECT wizard, wizard_payload FROM users WHERE user_id=?",
                (int(user_id),),
            ).fetchone()
            if row is None or not row["wizard"]:
                return None, []
            try:
                ids = json.loads(row["wizard_payload"] or "[]")
            except ValueError:
                ids = []
            return row["wizard"], [int(item) for item in ids]

        return self._read(run)

    def matching_rows(self, peer_id):
        def run():
            rows = self.conn.execute(
                """SELECT c.user_id AS user_id, c.topic_id AS topic_id,
                          c.title AS title, c.topic_title AS topic_title,
                          c.link AS link, c.status AS status, k.keyword AS keyword
                   FROM chats c
                   JOIN keywords k ON k.user_id = c.user_id
                   WHERE c.peer_id=? AND c.status='active'""",
                (peer_id,),
            ).fetchall()
            return [dict(row) for row in rows]

        return self._read(run)

    def plan_delivery(self, peer_id, msg_id, targets, now=None):
        moment = _moment(now)

        def run():
            self._cleanup(moment)
            for target in targets:
                user_id, keyword, chat_name, chat_link = _target_fields(target)
                row = self.conn.execute(
                    """SELECT sent FROM deliveries
                       WHERE peer_id=? AND msg_id=? AND user_id=?""",
                    (peer_id, msg_id, user_id),
                ).fetchone()
                if row is None:
                    self.conn.execute(
                        """INSERT INTO deliveries(
                               peer_id, msg_id, user_id, keyword, chat_name, chat_link, sent, created_at
                           ) VALUES(?, ?, ?, ?, ?, ?, 0, ?)""",
                        (peer_id, msg_id, user_id, keyword, chat_name, chat_link, moment),
                    )
                elif row["sent"] == 0:
                    self.conn.execute(
                        """UPDATE deliveries SET keyword=?, chat_name=?, chat_link=?
                           WHERE peer_id=? AND msg_id=? AND user_id=?""",
                        (keyword, chat_name, chat_link, peer_id, msg_id, user_id),
                    )

        self._transaction(run)

    def claim_delivery(self, peer_id, msg_id):
        def run():
            rows = self.conn.execute(
                """SELECT user_id, keyword, chat_name, chat_link FROM deliveries
                   WHERE peer_id=? AND msg_id=? AND sent=0""",
                (peer_id, msg_id),
            ).fetchall()
            self.conn.execute(
                """UPDATE deliveries SET sent=2
                   WHERE peer_id=? AND msg_id=? AND sent=0""",
                (peer_id, msg_id),
            )
            return [
                (row["user_id"], row["keyword"], row["chat_name"] or "", row["chat_link"] or "")
                for row in rows
            ]

        return self._transaction(run)

    def finish_delivery(self, peer_id, msg_id, user_id):
        def run():
            self.conn.execute(
                """UPDATE deliveries SET sent=1
                   WHERE peer_id=? AND msg_id=? AND user_id=?""",
                (peer_id, msg_id, int(user_id)),
            )

        self._transaction(run)

    def release_delivery(self, peer_id, msg_id, user_id):
        def run():
            self.conn.execute(
                """UPDATE deliveries SET sent=0
                   WHERE peer_id=? AND msg_id=? AND user_id=? AND sent=2""",
                (peer_id, msg_id, int(user_id)),
            )

        self._transaction(run)

    def record_hit(self, user_id, keyword, now=None):
        moment = _moment(now)

        def run():
            self.conn.execute(
                "INSERT INTO hits(user_id, keyword, ts) VALUES(?, ?, ?)",
                (int(user_id), keyword, moment),
            )
            self.conn.execute("DELETE FROM hits WHERE ts<?", (moment - WEEK_SECONDS,))

        self._transaction(run)

    def top_keywords(self, user_id, now=None, limit=3):
        moment = _moment(now)
        cutoff = moment - WEEK_SECONDS

        def run():
            rows = self.conn.execute(
                """SELECT keyword, COUNT(*) AS n FROM hits
                   WHERE user_id=? AND ts>=?
                   GROUP BY keyword
                   ORDER BY n DESC, keyword ASC
                   LIMIT ?""",
                (int(user_id), cutoff, limit),
            ).fetchall()
            return [(row["keyword"], row["n"]) for row in rows]

        return self._read(run)

    def active_peer_count(self):
        def run():
            return self.conn.execute(
                """SELECT COUNT(DISTINCT peer_id) AS n FROM chats
                   WHERE status='active' AND peer_id IS NOT NULL"""
            ).fetchone()["n"]

        return self._read(run)

    def user_ids(self):
        def run():
            return [
                row["user_id"]
                for row in self.conn.execute("SELECT user_id FROM users ORDER BY user_id")
            ]

        return self._read(run)

    def import_legacy_file(self, path):
        if self._meta_value("legacy_stats") == "1":
            return
        events = _legacy_events(path)

        def run():
            if self._meta("legacy_stats") == "1":
                return
            users = [
                row["user_id"]
                for row in self.conn.execute("SELECT user_id FROM users").fetchall()
            ]
            for user_id in users:
                for ts, keyword in events:
                    self.conn.execute(
                        "INSERT INTO hits(user_id, keyword, ts) VALUES(?, ?, ?)",
                        (user_id, keyword, ts),
                    )
            self._set_meta("legacy_stats", "1")

        self._transaction(run)

    def _seed(self, user_id, moment):
        row = self.conn.execute(
            "SELECT seeded FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if row is None:
            self.conn.execute(
                "INSERT INTO users(user_id, seeded, wizard, wizard_payload) VALUES(?, 0, NULL, '[]')",
                (user_id,),
            )
            seeded = 0
        else:
            seeded = row["seeded"]
        if seeded:
            return False
        for username, topic_ids in TOPICS.items():
            for topic_id in topic_ids:
                self.conn.execute(
                    """INSERT INTO chats(
                        user_id, peer_id, username, title, topic_id, topic_title,
                        link, invite_hash, status, created_at
                    ) VALUES(?, NULL, ?, ?, ?, NULL, ?, NULL, 'pending', ?)""",
                    (
                        user_id,
                        username.lower(),
                        "@" + username,
                        topic_id,
                        "https://t.me/{}/{}".format(username.lower(), topic_id),
                        moment,
                    ),
                )
        for keyword in KEYWORDS:
            self.conn.execute(
                "INSERT INTO keywords(user_id, keyword, norm, created_at) VALUES(?, ?, ?, ?)",
                (user_id, keyword, normalize(keyword), moment),
            )
        self.conn.execute("UPDATE users SET seeded=1 WHERE user_id=?", (user_id,))
        log.info("Стартовые чаты и слова для %s", user_id)
        return True

    def _cleanup(self, moment):
        self.conn.execute(
            "DELETE FROM deliveries WHERE created_at<?",
            (moment - _KEEP_DELIVERY_SECONDS,),
        )

    def _create(self):
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                seeded INTEGER NOT NULL DEFAULT 0,
                wizard TEXT,
                wizard_payload TEXT NOT NULL DEFAULT '[]'
            );
            CREATE TABLE IF NOT EXISTS chats (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                peer_id INTEGER,
                username TEXT,
                title TEXT NOT NULL,
                topic_id INTEGER,
                topic_title TEXT,
                link TEXT NOT NULL,
                invite_hash TEXT,
                status TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );
            CREATE INDEX IF NOT EXISTS chats_peer ON chats(peer_id);
            CREATE INDEX IF NOT EXISTS chats_user ON chats(user_id);
            CREATE TABLE IF NOT EXISTS keywords (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                keyword TEXT NOT NULL,
                norm TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                UNIQUE (user_id, norm)
            );
            CREATE TABLE IF NOT EXISTS hits (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                keyword TEXT NOT NULL,
                ts INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS hits_user_ts ON hits(user_id, ts);
            CREATE TABLE IF NOT EXISTS deliveries (
                peer_id INTEGER NOT NULL,
                msg_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                keyword TEXT NOT NULL,
                chat_name TEXT NOT NULL DEFAULT '',
                chat_link TEXT NOT NULL DEFAULT '',
                sent INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                PRIMARY KEY (peer_id, msg_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        self._add_column("deliveries", "chat_name", "TEXT NOT NULL DEFAULT ''")
        self._add_column("deliveries", "chat_link", "TEXT NOT NULL DEFAULT ''")

    def _add_column(self, table, column, definition):
        names = {
            row["name"]
            for row in self.conn.execute("PRAGMA table_info({})".format(table))
        }
        if column not in names:
            self.conn.execute(
                "ALTER TABLE {} ADD COLUMN {} {}".format(table, column, definition)
            )

    def _chmod(self):
        try:
            if self.path.exists():
                self.path.chmod(0o600)
            for suffix in ("-wal", "-shm", "-journal"):
                extra = Path(str(self.path) + suffix)
                if extra.exists():
                    extra.chmod(0o600)
        except OSError:
            log.exception("Права на базу не выставились")

    def _transaction(self, fn):
        with self._lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                result = fn()
                self.conn.execute("COMMIT")
            except Exception:
                try:
                    self.conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            return result

    def _read(self, fn):
        with self._lock:
            return fn()

    def _meta_value(self, key):
        def run():
            return self._meta(key)

        return self._read(run)

    def _meta(self, key):
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def _set_meta(self, key, value):
        self.conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
            (key, value),
        )


def _moment(now):
    if now is None:
        return int(time.time())
    return int(now)


def _target_fields(target):
    chat_name = target[2] if len(target) > 2 else ""
    chat_link = target[3] if len(target) > 3 else ""
    return int(target[0]), target[1], chat_name or "", chat_link or ""


def _legacy_events(path):
    file = Path(path)
    if not file.exists():
        return []
    try:
        payload = json.loads(file.read_text())
    except (OSError, ValueError):
        log.warning("Старый файл статистики не прочитался")
        return []
    if not isinstance(payload, list):
        log.warning("Старый файл статистики не прочитался")
        return []
    events = []
    for item in payload:
        if (
            isinstance(item, list)
            and len(item) == 2
            and isinstance(item[0], (int, float))
            and isinstance(item[1], str)
            and item[1]
        ):
            events.append((int(item[0]), item[1]))
    return events
