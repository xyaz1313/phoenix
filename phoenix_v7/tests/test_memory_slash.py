import phoenix_v7


def test_memory_forget_removes_matching(monkeypatch, tmp_path):
    db = tmp_path / "memory.db"
    monkeypatch.setattr(phoenix_v7, "_memory_db_path", db)
    from phoenix_v7.memory.store import write_memory
    write_memory(db, "用户的手机号是13800000000", "s1")

    result = phoenix_v7._handle_memory_slash("forget 手机号")
    assert "已删除" in result

    from phoenix_v7.memory.store import search_memories
    assert search_memories(db, "手机号") == []


def test_memory_clear_requires_confirm_token(monkeypatch, tmp_path):
    db = tmp_path / "memory.db"
    monkeypatch.setattr(phoenix_v7, "_memory_db_path", db)
    from phoenix_v7.memory.store import write_memory
    write_memory(db, "某条记忆", "s1")

    result = phoenix_v7._handle_memory_slash("clear")
    assert "confirm" in result.lower()
    from phoenix_v7.memory.store import search_memories
    assert search_memories(db, "记忆") != []


def test_memory_clear_with_confirm_wipes_all(monkeypatch, tmp_path):
    db = tmp_path / "memory.db"
    monkeypatch.setattr(phoenix_v7, "_memory_db_path", db)
    from phoenix_v7.memory.store import write_memory
    write_memory(db, "某条记忆", "s1")

    result = phoenix_v7._handle_memory_slash("clear confirm")
    assert "已清空" in result
    from phoenix_v7.memory.store import search_memories
    assert search_memories(db, "记忆") == []


def test_memory_usage_line_on_no_args():
    result = phoenix_v7._handle_memory_slash("")
    assert "forget" in result and "clear" in result
