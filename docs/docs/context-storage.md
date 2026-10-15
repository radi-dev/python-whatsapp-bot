---
sidebar_position: 8
---

# Context Storage

Handlers receive a `context` object whose `user_data` dict remembers things about a user
between messages:

```python
@wa_bot.on_message(regex=r'^/setname (.+)')
def set_name(update, context):
    context.user_data['name'] = update.message_text.split(' ', 1)[1]

@wa_bot.on_message(regex=r'^/getname')
def get_name(update, context):
    update.reply_message(context.user_data.get('name', 'Not set'))
```

That data is **not** kept in process memory. It is read from and written to a storage
backend that you configure, so it behaves the same whether you run one process or
`uvicorn --workers 4` across three containers.

## Configuring a backend

Pass it to the bot:

```python
from python_whatsapp_bot import Whatsapp, SQLiteStorage

wa_bot = Whatsapp(number_id, token, context_storage=SQLiteStorage('bot_context.db'))
```

or set a process-wide default (used by every bot and every `User_context` without an explicit
storage):

```python
from python_whatsapp_bot import set_context_storage, RedisStorage

set_context_storage(RedisStorage('redis://localhost:6379/0'))
```

You can also set it later with `wa_bot.set_context_storage(...)`, as long as it happens before
the first update is processed.

### Nothing configured? The bot refuses to run

If at least one handler declares a `context` parameter and no storage is configured, the first
call to `process_update` / `aprocess_update` raises `ContextStorageNotConfiguredError`. The
library never falls back to process memory silently, because that is exactly what breaks in a
multi-worker deployment.

Handlers that do not take `context` (or are registered with `context=False`) never trigger
this check, so you are free to use a different state mechanism altogether.

## Backends

### SQLite (no dependencies)

```python
SQLiteStorage('bot_context.db', table_name='whatsapp_user_context', timeout=10.0)
```

Uses the standard library. WAL mode is enabled, so several worker processes on the **same
machine** can share the file safely. Not suitable for multiple machines.

### Redis

```bash
pip install "python-whatsapp-bot[redis]"
```

```python
RedisStorage('redis://:password@host:6379/0')
RedisStorage('rediss://host:6380/0', key_prefix='mybot:', ttl=7 * 24 * 3600)
RedisStorage(client=my_redis_client, async_client=my_async_redis_client)
```

Async handlers use a native `redis.asyncio` client, so the event loop is never blocked.
`ttl` (seconds) makes idle conversations expire automatically.

### Postgres, MySQL, and anything else SQLAlchemy supports

```bash
pip install "python-whatsapp-bot[postgres]"   # sqlalchemy + psycopg
pip install "python-whatsapp-bot[mysql]"      # sqlalchemy + pymysql
pip install "python-whatsapp-bot[sqlalchemy]" # bring your own driver
```

```python
SQLAlchemyStorage('postgresql+psycopg://user:pass@host/db')
SQLAlchemyStorage('mysql+pymysql://user:pass@host/db')
SQLAlchemyStorage('sqlite:///bot_context.db')
SQLAlchemyStorage(engine=app_engine)                  # reuse your app's Engine
SQLAlchemyStorage(engine=app_async_engine)            # or AsyncEngine (asyncpg, aiomysql, ...)
```

The table (`whatsapp_user_context` by default: `key`, `data`, `updated_at`) is created on
first use; pass `create_table=False` if you manage migrations yourself. Upserts use the native
`ON CONFLICT` / `ON DUPLICATE KEY` syntax on Postgres, SQLite and MySQL and a portable
update-then-insert elsewhere.

With a sync `Engine`, async handlers run the queries in a thread pool. With an `AsyncEngine`
they run natively, but sync handlers cannot use it.

### Memory (tests only)

```python
MemoryStorage()
```

Process-local. It logs a warning when created because it is **not shared between workers**.
Use it in tests and single-process experiments only.

## Expiry (`ttl`)

Without a TTL a row is kept for every phone number that ever messaged the bot. Every backend
accepts `ttl=<seconds>`:

```python
RedisStorage(url, ttl=7 * 24 * 3600)
SQLiteStorage('bot.db', ttl=7 * 24 * 3600)
SQLAlchemyStorage(url, ttl=30 * 24 * 3600, purge_interval=3600)
```

Semantics are the same everywhere: **a user's record expires `ttl` seconds after that user's
last activity**. Both reads and writes count - the dispatcher writes the record when it
changed and otherwise *touches* it, so a user who chats every day never loses their data even
if nothing in it changes. (The SQL backends coalesce touches within 10% of the TTL, at most a
minute, to avoid a write per message; a record therefore lives at least 0.9 × `ttl` after the
last message.)

| Backend | Expiry | Deletion |
|---|---|---|
| `RedisStorage` | native key TTL (`SET ... EX`, `EXPIRE`) | by Redis |
| `SQLiteStorage` / `SQLAlchemyStorage` / `MemoryStorage` | expired rows are filtered out of every read immediately | a sweep (`DELETE ... WHERE updated_at < now - ttl`) runs at most once per `purge_interval` seconds (default 300), piggy-backed on writes - no background threads |

For full control set `purge_interval=None` and call `storage.purge_expired()` (or
`await storage.apurge_expired()`) from a cron job or scheduler; it returns the number of rows
deleted. The sweep also removes lock rows left behind by crashed workers.

`User_context.touch()` / `atouch()` refresh a record manually, and `storage.touch(key)` is
available on every backend (a no-op without `ttl`).

### Your own backend

Subclass `ContextStorage` and implement three methods:

```python
from python_whatsapp_bot import ContextStorage

class MongoStorage(ContextStorage):
    def __init__(self, collection):
        super().__init__()
        self.col = collection

    def get(self, key):
        doc = self.col.find_one({'_id': key})
        return self._loads(doc['data']) if doc else None

    def set(self, key, data):
        self.col.replace_one({'_id': key}, {'_id': key, 'data': self._dumps(data)}, upsert=True)

    def delete(self, key):
        self.col.delete_one({'_id': key})
```

`aget` / `aset` / `adelete` default to running the sync methods in a thread pool; override
them if you have a native async client. Override `ping()` if a cheap connectivity check is
available - it is called once before the first update that needs the context, so a wrong
password or unreachable host fails immediately. To support `ttl`, implement `touch(key)` and
`purge_expired()` and filter expired records out of `get()`; to support per-user locking,
implement `lock()` (see below).

## How reads and writes happen

Each user has one record in the storage, keyed by their WhatsApp id:

```json
{"user_data": {"name": "Ada"}, "next_step": {"handler": "app.steps:get_email", "...": "..."}}
```

For every message update (once a storage is configured):

1. The record is loaded (one read). It holds `user_data` *and* the pending next step, so the
   dispatcher knows whether the user is mid-conversation.
2. The matching handler runs.
3. If the record changed - including nested changes such as
   `context.user_data['cart'].append(item)`, or a `set_next_step` call - it is written back
   (one write). Unchanged data is not written. This also happens if the handler raised,
   mirroring the behaviour of a plain shared dict.

## Multi-step conversations (`set_next_step`)

`wa_bot.set_next_step(update, function)` makes `function` handle the user's next message.
That state is persisted in the user's record, next to `user_data`:

- It is shared by every worker process and survives restarts.
- `context.user_data.clear()` does **not** abort the conversation (the step is outside
  `user_data`); `User_context.clear()` / `wa_bot.clear_next_step(...)` do.
- It is saved in the same single write as `user_data`, under the same per-user lock, so the two
  can never get out of sync.
- Setting a step without a configured storage raises `ContextStorageNotConfiguredError`.

### Functions are stored by reference

Redis and SQL cannot store a Python function, so the step is stored as a reference that every
worker can resolve:

| Function | Reference | What you need to do |
|---|---|---|
| module-level `def` | `import:<module>:<qualname>` | nothing |
| closure (e.g. inside an app factory), method, `functools.partial` | `step:<name>` | `@wa_bot.register_step('<name>')`, in every worker at import time |
| lambda / unregistered nested function | - | rejected with `NextStepNotSerializableError` |

The same rules apply to the optional `func=` filter and `end_conversation_action=`.

```python
def create_app():
    wa_bot = Whatsapp(number_id, token, context_storage=RedisStorage(url))

    @wa_bot.register_step('get_email')          # closure -> must be registered
    def get_email(update, context):
        context.user_data['email'] = update.message_text

    @wa_bot.on_message(regex=r'^/register')
    def start(update, context):
        update.reply_message('Your email?')
        wa_bot.set_next_step(update, get_email)
    ...
```

Keep function and step names stable while conversations are in flight: a stored reference that
can no longer be resolved (renamed function, missing registration in a worker) is logged,
discarded, and the message falls through to the regular handlers - the user is never stuck.

If the handler of a step raises, the step is kept, so the user's next message is offered to it
again. A step handler that calls `set_next_step` itself chains to the new step.

`wa_bot.get_next_step(phone)` returns the stored record (a plain dict) for inspection.

Because the data is serialized (JSON by default), values must be JSON-serializable: `str`,
`int`, `float`, `bool`, `None`, `list`, `dict`. Tuples come back as lists and non-string dict
keys come back as strings. Storing an unserializable object raises
`ContextSerializationError` when saving. You can pass a custom `serializer` (an object with
`dumps`/`loads`) to any backend.

## Per-user locking

Each update is a load → run → save cycle. Without coordination, two workers handling the same
user at the same time would each save their own view and the last write would win. To prevent
that, the dispatcher holds a **per-user lock in the storage backend** for the whole cycle:

1. The lock for the sender is acquired - *in the webhook request, before a worker thread is
   spawned and before anything is processed*. Updates of one user are therefore handled one at
   a time and in arrival order, across threads, processes and machines. Other users are
   unaffected.
2. The update is processed (load, handler, save).
3. The lock is released, even if the handler raised.

```python
wa_bot = Whatsapp(
    number_id, token,
    context_storage=RedisStorage('redis://...'),
    context_lock=True,          # default
    context_lock_timeout=60,    # TTL of a held lock, in seconds
    context_lock_wait=10,       # how long to wait for a busy user, in seconds
)
```

### `context_lock_timeout` - crashed-worker protection

A held lock expires by itself after `context_lock_timeout` seconds, so a worker that dies
mid-update can never block a user forever. It must be longer than your slowest handler: if a
handler outruns it, another worker may start processing the same user and the bot logs a
warning (`lock expired`). Raise it if you see that warning, or move long-running work out of
the handler.

### `context_lock_wait` - busy users and WhatsApp retries

If the sender's lock is still held by someone else after `context_lock_wait` seconds,
`process_update` / `aprocess_update` raise `ContextLockTimeoutError`. At that point **nothing
has been processed** (the message was not marked as read, no handler ran), so the update can
safely be retried. WhatsApp re-delivers webhooks that were not acknowledged with a 2xx status,
using exponential backoff - so simply answer with an error status:

```python
from python_whatsapp_bot import ContextLockTimeoutError

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        wa_bot.process_update(request.get_json())
    except ContextLockTimeoutError:
        return 'Busy, retry later', 503
    return 'OK', 200
```

(Or don't catch it at all: an unhandled exception makes most frameworks return 500, which has
the same effect.) The same applies to `ContextStorageNotConfiguredError` and other
`ContextStorageError`s raised while preparing the context.

Each `process_update` / `aprocess_update` call handles exactly the update it was given -
never one delivered by another concurrent call - so an error is always reported to the
webhook request that carried the affected message. Your web server may therefore call
`process_update` from as many threads as it likes; updates of different users are processed
in parallel and the per-user lock keeps each user's messages in order.

### Backends

| Backend | Lock implementation |
|---|---|
| `RedisStorage` | redis-py `Lock` (`SET NX PX` + atomic Lua release) - also in async mode |
| `SQLiteStorage` / `SQLAlchemyStorage` | a `<table>_locks` table (`key`, `token`, `expires_at`): atomic insert, expired locks are taken over, token-checked release. Polls every 100 ms while waiting |
| `MemoryStorage` | process-local (consistent with the rest of that backend) |

Lock expiry for the SQL backends is based on wall-clock time (`expires_at`), so keep the clocks
of your workers in sync (NTP).

### Disabling

`Whatsapp(..., context_lock=False)` skips locking entirely (last write wins). A custom backend
that does not implement `lock()` raises `ContextLockNotSupportedError` on the first update
unless locking is disabled - the bot never silently runs unprotected.

### Locks in your own backend

Implement `lock()` on your `ContextStorage` subclass and return a `ContextLock` with two
primitives: a non-blocking `_try_acquire()` that must also take over an *expired* lock, and a
`_release()` that only releases if the lock is still owned (compare `self.token`). Waiting,
TTL bookkeeping and the async API are inherited; override `_atry_acquire` / `_arelease` for a
native async client.

```python
from python_whatsapp_bot import ContextLock, ContextStorage

class MongoLock(ContextLock):
    def __init__(self, col, key, **kwargs):
        super().__init__(key, **kwargs)
        self.col = col

    def _try_acquire(self):
        now = time.time()
        try:
            self.col.insert_one({'_id': self.key, 'token': self.token, 'expires_at': now + self.timeout})
            return True
        except DuplicateKeyError:
            r = self.col.update_one({'_id': self.key, 'expires_at': {'$lte': now}},
                                    {'$set': {'token': self.token, 'expires_at': now + self.timeout}})
            return r.modified_count == 1

    def _release(self):
        self.col.delete_one({'_id': self.key, 'token': self.token})

class MongoStorage(ContextStorage):
    ...
    def lock(self, key, **kwargs):
        return MongoLock(self.db.locks, key, **kwargs)
```

You can use the lock yourself too, e.g. around a background job that edits a user's context:

```python
with storage.lock('2348145xxxxx'), wa_bot.user_context('2348145xxxxx') as ctx:
    ctx.user_data['credits'] += 10
```

## Using the context outside handlers

```python
with wa_bot.user_context('2348145xxxxx') as ctx:   # loaded on enter, saved on exit
    ctx.user_data['vip'] = True

# async
async with wa_bot.user_context('2348145xxxxx') as ctx:
    ctx.user_data['vip'] = True

# explicit
from python_whatsapp_bot import User_context
ctx = User_context('2348145xxxxx')          # uses the global storage (or pass storage=...)
ctx.user_data['lang'] = 'en'
ctx.save()                                  # returns True if something was written
ctx.refresh()                               # reload, discarding unsaved changes
ctx.clear()                                 # wipe the user's data
```
