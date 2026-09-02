import uuid

from gizmo_friend.brain.memory import memobase_user_id


def test_memory_identity_is_stable_and_valid():
    first = memobase_user_id("gizmo-owner")
    assert str(uuid.UUID(first)) == first
    assert first == memobase_user_id("gizmo-owner")
    assert first != memobase_user_id("another-owner")


def test_existing_uuid_identity_is_preserved():
    value = str(uuid.uuid4())
    assert memobase_user_id(value) == value
