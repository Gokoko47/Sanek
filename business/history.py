"""Short local conversation memory. No import or download of Telegram history."""
from __future__ import annotations

from .bot_types import is_sensitive


class History:
    def __init__(self, store, *, ttl: int, max_messages: int, max_chars: int):
        self.store = store
        self.ttl, self.max_messages, self.max_chars = ttl, max_messages, max_chars
        with store.lock, store.db:
            store.db.execute('''CREATE TABLE IF NOT EXISTS conversation_context(
                connection TEXT,chat INTEGER,message INTEGER,role TEXT,body TEXT,created REAL,
                PRIMARY KEY(connection,chat,message))''')
            store.db.execute('CREATE INDEX IF NOT EXISTS context_age ON conversation_context(created)')
            store.db.execute('PRAGMA secure_delete=ON')

    def enabled(self):
        return self.store.get('context_enabled', '1') == '1'

    def remember(self, cid, chat, mid, role, text, now):
        if not self.enabled() or role not in ('user', 'assistant') or not isinstance(text, str) or not text.strip() or is_sensitive(text):
            return
        body = text.strip()[:min(2000, self.max_chars)]
        with self.store.lock, self.store.db:
            self.store.db.execute('DELETE FROM conversation_context WHERE created<?', (now-self.ttl,))
            self.store.db.execute('INSERT OR REPLACE INTO conversation_context VALUES (?,?,?,?,?,?)',
                                  (cid, chat, mid, role, body, now))
            self.store.db.execute('DELETE FROM conversation_context WHERE rowid NOT IN (SELECT rowid FROM conversation_context ORDER BY created DESC,rowid DESC LIMIT 500)')
            rows = self.store.db.execute('SELECT message,length(body) AS chars FROM conversation_context WHERE connection=? AND chat=? ORDER BY created DESC,message DESC', (cid, chat)).fetchall()
            total = 0
            for index, row in enumerate(rows):
                total += row['chars']
                if index >= self.max_messages or total > self.max_chars:
                    self.store.db.execute('DELETE FROM conversation_context WHERE connection=? AND chat=? AND message=?', (cid, chat, row['message']))

    def snapshot(self, cid, chat, exclude_ids, now):
        if not self.enabled():
            return []
        with self.store.lock, self.store.db:
            self.store.db.execute('DELETE FROM conversation_context WHERE created<?', (now-self.ttl,))
            rows = self.store.db.execute('SELECT message,role,body FROM conversation_context WHERE connection=? AND chat=? ORDER BY created,message', (cid, chat)).fetchall()
            return [{'role': r['role'], 'text': r['body']} for r in rows if r['message'] not in exclude_ids]

    def prune(self,now):
        with self.store.lock,self.store.db:
            self.store.db.execute('DELETE FROM conversation_context WHERE created<?',(now-self.ttl,))

    def clear(self, cid=None, chat=None):
        with self.store.lock, self.store.db:
            if cid is None:
                self.store.db.execute('DELETE FROM conversation_context')
            elif chat is None:
                self.store.db.execute('DELETE FROM conversation_context WHERE connection=?',(cid,))
            else:
                self.store.db.execute('DELETE FROM conversation_context WHERE connection=? AND chat=?', (cid, chat))

    def configure(self, enabled):
        self.store.set('context_enabled', '1' if enabled else '0')
        if not enabled:
            self.clear()
