"""Short-lived operator drafts with one-attempt delivery and revision checks."""
from __future__ import annotations
import json
import secrets


class Drafts:
    def __init__(self, store, ttl=180):
        self.store, self.ttl = store, ttl
        with store.lock, store.db:
            store.db.execute('''CREATE TABLE IF NOT EXISTS reply_drafts(
                id TEXT PRIMARY KEY,connection TEXT,chat INTEGER,generation INTEGER,mid INTEGER,
                source_date INTEGER,mids TEXT,source TEXT,body TEXT,created REAL,
                revision INTEGER DEFAULT 0,edited INTEGER DEFAULT 0,state TEXT DEFAULT 'pending')''')

    def prune(self, now):
        with self.store.lock, self.store.db:
            self.store.db.execute('DELETE FROM reply_drafts WHERE created<?', (now-self.ttl,))

    def create(self, cid, chat, generation, source_date, mids, source, body, now):
        token = secrets.token_urlsafe(9)
        with self.store.lock, self.store.db:
            self.store.db.execute('DELETE FROM reply_drafts WHERE created<? OR (connection=? AND chat=?)', (now-self.ttl,cid,chat))
            self.store.db.execute('INSERT INTO reply_drafts(id,connection,chat,generation,mid,source_date,mids,source,body,created) VALUES (?,?,?,?,?,?,?,?,?,?)',
                (token,cid,chat,generation,mids[-1],source_date,json.dumps(mids),source,body,now))
            self.store.db.execute('DELETE FROM reply_drafts WHERE id IN (SELECT id FROM reply_drafts ORDER BY created DESC,rowid DESC LIMIT -1 OFFSET 100)')
        return token

    def get(self, token, now):
        self.prune(now)
        with self.store.lock:
            row = self.store.db.execute('SELECT * FROM reply_drafts WHERE id=?', (token,)).fetchone()
            return dict(row) if row else None

    def revise(self, token, text, revision, now):
        with self.store.lock, self.store.db:
            row = self.get(token,now)
            if not row or row['state']!='pending' or row['revision']!=revision:
                return False
            self.store.db.execute('UPDATE reply_drafts SET body=?,revision=revision+1,edited=1 WHERE id=?', (text,token))
            return True

    def claim(self, token, revision, now):
        with self.store.lock, self.store.db:
            row = self.get(token,now)
            if not row or row['state']!='pending' or row['revision']!=revision:
                return None
            self.store.db.execute("UPDATE reply_drafts SET state='attempted' WHERE id=?", (token,))
            return row

    def dismiss(self, token, revision, now):
        with self.store.lock,self.store.db:
            row=self.get(token,now)
            if not row or row['state']!='pending' or row['revision']!=revision:
                return False
            self.store.db.execute("UPDATE reply_drafts SET state='dismissed' WHERE id=?",(token,))
            return True

    def clear(self,cid=None,chat=None):
        with self.store.lock,self.store.db:
            if cid is None:self.store.db.execute('DELETE FROM reply_drafts')
            elif chat is None:self.store.db.execute('DELETE FROM reply_drafts WHERE connection=?',(cid,))
            else:self.store.db.execute('DELETE FROM reply_drafts WHERE connection=? AND chat=?',(cid,chat))

    def finish(self, token, state):
        with self.store.lock, self.store.db:
            self.store.db.execute('UPDATE reply_drafts SET state=? WHERE id=?', (state,token))
