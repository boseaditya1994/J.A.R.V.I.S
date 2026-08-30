import sqlite3

from jarvis.memory.store import MemoryStore


def make_store(tmp_path):
    return MemoryStore(db_path=tmp_path / "memory.db")


def test_add_and_list_facts(tmp_path):
    store = make_store(tmp_path)

    store.add_fact("favorite language is Python")
    store.add_fact("allergic to peanuts")

    facts = store.list_facts()
    assert [f.text for f in facts] == ["favorite language is Python", "allergic to peanuts"]


def test_delete_facts_matching_is_case_insensitive_substring(tmp_path):
    store = make_store(tmp_path)
    store.add_fact("favorite language is Python")
    store.add_fact("allergic to peanuts")

    removed = store.delete_facts_matching("PYTHON")

    assert [f.text for f in removed] == ["favorite language is Python"]
    remaining = store.list_facts()
    assert [f.text for f in remaining] == ["allergic to peanuts"]


def test_delete_facts_matching_no_match_returns_empty(tmp_path):
    store = make_store(tmp_path)
    store.add_fact("allergic to peanuts")

    removed = store.delete_facts_matching("shellfish")

    assert removed == []
    assert len(store.list_facts()) == 1


def test_add_and_list_open_tasks(tmp_path):
    store = make_store(tmp_path)

    store.add_task("call Mom", due_at="2026-08-20T19:00:00")
    store.add_task("buy milk")

    tasks = store.list_open_tasks()
    assert [t.text for t in tasks] == ["call Mom", "buy milk"]
    assert tasks[0].due_at == "2026-08-20T19:00:00"
    assert tasks[1].due_at is None


def test_forget_everything_wipes_all_tables(tmp_path):
    store = make_store(tmp_path)
    store.add_fact("allergic to peanuts")
    store.add_task("call Mom")
    store.log_turn("hi", "hello there")

    store.forget_everything()

    assert store.list_facts() == []
    assert store.list_open_tasks() == []
    row = store.conn.execute("SELECT COUNT(*) FROM episodic_log").fetchone()
    assert row[0] == 0


def test_log_turn_persists_to_episodic_log(tmp_path):
    store = make_store(tmp_path)

    store.log_turn("hello", "hi there")

    row = store.conn.execute(
        "SELECT user_text, assistant_text FROM episodic_log"
    ).fetchone()
    assert row == ("hello", "hi there")


def test_data_persists_across_store_instances(tmp_path):
    db_path = tmp_path / "memory.db"
    store1 = MemoryStore(db_path=db_path)
    store1.add_fact("favorite language is Python")
    store1.close()

    store2 = MemoryStore(db_path=db_path)
    facts = store2.list_facts()

    assert [f.text for f in facts] == ["favorite language is Python"]


# -- Reminder notifications (Phase 8) ---------------------------------------


def test_new_task_has_no_notified_at(tmp_path):
    store = make_store(tmp_path)

    task = store.add_task("buy milk", due_at="2026-08-20T09:00:00")

    assert task.notified_at is None
    assert store.list_open_tasks()[0].notified_at is None


def test_list_due_unnotified_tasks_filters_correctly(tmp_path):
    store = make_store(tmp_path)
    due = store.add_task("call Mom", due_at="2026-08-20T09:00:00")
    store.add_task("future task", due_at="2026-08-25T09:00:00")
    store.add_task("no due date")
    already_notified = store.add_task("old reminder", due_at="2026-08-19T09:00:00")
    store.mark_task_notified(already_notified.id)

    result = store.list_due_unnotified_tasks("2026-08-20T12:00:00")

    assert [t.id for t in result] == [due.id]


def test_list_due_unnotified_tasks_orders_by_due_at(tmp_path):
    store = make_store(tmp_path)
    later = store.add_task("later", due_at="2026-08-20T15:00:00")
    earlier = store.add_task("earlier", due_at="2026-08-20T08:00:00")

    result = store.list_due_unnotified_tasks("2026-08-20T23:00:00")

    assert [t.id for t in result] == [earlier.id, later.id]


def test_mark_task_notified_excludes_it_from_later_calls(tmp_path):
    store = make_store(tmp_path)
    task = store.add_task("call Mom", due_at="2026-08-20T09:00:00")

    store.mark_task_notified(task.id)

    assert store.list_due_unnotified_tasks("2026-08-20T12:00:00") == []
    assert store.list_open_tasks()[0].notified_at is not None


def test_log_notification_and_count_notifications_since(tmp_path):
    store = make_store(tmp_path)

    store.log_notification("morning_brief", "good morning")
    store.log_notification("reminder_check", "reminders due: buy milk")

    assert store.count_notifications_since("2020-01-01T00:00:00") == 2


def test_count_notifications_since_excludes_earlier_notifications(tmp_path):
    store = make_store(tmp_path)
    store.log_notification("morning_brief", "good morning")

    # A cutoff after the logged notification's timestamp excludes it.
    future_cutoff = "2099-01-01T00:00:00"
    assert store.count_notifications_since(future_cutoff) == 0


def test_forget_everything_wipes_notifications_log(tmp_path):
    store = make_store(tmp_path)
    store.log_notification("morning_brief", "good morning")

    store.forget_everything()

    assert store.count_notifications_since("2020-01-01T00:00:00") == 0


def test_connect_adds_notified_at_column_to_preexisting_tasks_table(tmp_path):
    db_path = tmp_path / "memory.db"
    # Simulate a pre-Phase-8 DB: a tasks table without notified_at, created
    # directly rather than through db.connect()'s current (migrated) SCHEMA.
    raw = sqlite3.connect(db_path)
    raw.execute(
        "CREATE TABLE tasks (id INTEGER PRIMARY KEY, text TEXT NOT NULL, "
        "due_at TEXT, created_at TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0)"
    )
    raw.execute(
        "INSERT INTO tasks (id, text, created_at, done) VALUES (1, 'old task', 'x', 0)"
    )
    raw.commit()
    raw.close()

    store = MemoryStore(db_path=db_path)  # must not raise

    columns = {row[1] for row in store.conn.execute("PRAGMA table_info(tasks)")}
    assert "notified_at" in columns
    assert store.list_open_tasks()[0].notified_at is None


def test_connect_adds_recurrence_column_to_preexisting_tasks_table(tmp_path):
    db_path = tmp_path / "memory.db"
    raw = sqlite3.connect(db_path)
    raw.execute(
        "CREATE TABLE tasks (id INTEGER PRIMARY KEY, text TEXT NOT NULL, "
        "due_at TEXT, created_at TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0, "
        "notified_at TEXT)"
    )
    raw.execute(
        "INSERT INTO tasks (id, text, created_at, done) VALUES (1, 'old task', 'x', 0)"
    )
    raw.commit()
    raw.close()

    store = MemoryStore(db_path=db_path)  # must not raise

    columns = {row[1] for row in store.conn.execute("PRAGMA table_info(tasks)")}
    assert "recurrence" in columns
    assert store.list_open_tasks()[0].recurrence is None


# -- Recurring reminders (Phase 9 Part 3) -----------------------------------


def test_add_task_with_recurrence(tmp_path):
    store = make_store(tmp_path)

    task = store.add_task("book shuttle", due_at="2026-08-24T08:36:00", recurrence="weekday")

    assert task.recurrence == "weekday"
    assert store.list_open_tasks()[0].recurrence == "weekday"


def test_add_task_without_recurrence_defaults_to_none(tmp_path):
    store = make_store(tmp_path)

    task = store.add_task("buy milk")

    assert task.recurrence is None


def test_reschedule_task_updates_due_at_and_clears_notified_at(tmp_path):
    store = make_store(tmp_path)
    task = store.add_task("book shuttle", due_at="2026-08-24T08:36:00", recurrence="weekday")
    store.mark_task_notified(task.id)
    assert store.list_open_tasks()[0].notified_at is not None

    store.reschedule_task(task.id, "2026-08-25T08:36:00")

    updated = store.list_open_tasks()[0]
    assert updated.due_at == "2026-08-25T08:36:00"
    assert updated.notified_at is None


def test_rescheduled_task_is_picked_up_again_by_list_due_unnotified_tasks(tmp_path):
    store = make_store(tmp_path)
    task = store.add_task("book shuttle", due_at="2026-08-24T08:36:00", recurrence="weekday")
    store.mark_task_notified(task.id)
    store.reschedule_task(task.id, "2026-08-25T08:36:00")

    # Not due yet relative to a time before the new due_at.
    assert store.list_due_unnotified_tasks("2026-08-24T12:00:00") == []
    # Due once the new due_at has passed.
    due = store.list_due_unnotified_tasks("2026-08-25T09:00:00")
    assert len(due) == 1
    assert due[0].id == task.id
