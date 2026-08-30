# Reach

They hold the stick. The current page lands on a parent's phone. Gizmo is not a phone. Not a live call.

**v1:** a local outbox on disk (`gizmo_reach.ParentOutbox`). Friend calls `enqueue(page)` and fails soft. Nothing is sent to a real device.

Later: a parent-phone client that drains this outbox.

```
data/outbox.jsonl
```

Each line is one page: id, subject, line, still path, time.
