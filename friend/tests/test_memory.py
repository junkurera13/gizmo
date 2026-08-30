from pathlib import Path

from gizmo_friend.memory import Memory, SavedPage


def test_name_and_fact_survive_reopen(tmp_path: Path) -> None:
    db = tmp_path / "gizmo.db"
    mem = Memory(db)
    mem.remember_from_utterance("I'm Rio")
    mem.remember_from_utterance("I have a dog named Toast")
    mem.add_episode("looked at a pinecone")
    mem.rewrite_summary()
    assert mem.get_name() == "Rio"
    mem.close()

    again = Memory(db)
    prefix = again.prefix_memory()
    assert prefix.name == "Rio"
    assert any("Toast" in f for f in prefix.facts)
    assert prefix.summary
    assert any("pinecone" in e for e in prefix.episodes)
    again.close()


def test_remember_does_not_wait_for_shutdown(tmp_path: Path) -> None:
    mem = Memory(tmp_path / "gizmo.db")
    mem.remember_from_utterance("My name is Maya")
    assert mem.get_name() == "Maya"
    mem.close()


def test_pages_round_trip(tmp_path: Path) -> None:
    mem = Memory(tmp_path / "gizmo.db")
    page = mem.save_page(
        SavedPage(
            id="abc",
            subject="pinecone",
            line="A pinecone we kept.",
            still_path="/tmp/p.svg",
            created_at="2026-01-01T00:00:00+00:00",
        )
    )
    assert mem.last_page() == page
    mem.close()


def test_recall_is_not_a_new_fact(tmp_path: Path) -> None:
    mem = Memory(tmp_path / "gizmo.db")
    mem.remember_from_utterance("do you remember yesterday")
    assert mem.prefix_memory().facts == []
    mem.close()
