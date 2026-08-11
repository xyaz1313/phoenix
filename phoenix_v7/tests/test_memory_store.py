from phoenix_v7.memory.store import (
    write_memory, search_memories, forget_matching, clear_all, stats,
)


def test_write_and_search_finds_content(tmp_path):
    db = tmp_path / "memory.db"
    write_memory(db, "用户喜欢用Python写类型注解", "s1")
    results = search_memories(db, "Python 类型注解")
    assert len(results) >= 1
    assert "类型注解" in results[0]["content"]


def test_search_no_match_returns_empty(tmp_path):
    db = tmp_path / "memory.db"
    write_memory(db, "用户喜欢用Python写类型注解", "s1")
    results = search_memories(db, "完全无关的查询词汇xyz")
    assert results == []


def test_repeated_write_reinforces_not_duplicates(tmp_path):
    db = tmp_path / "memory.db"
    write_memory(db, "用户偏好深色主题", "s1")
    write_memory(db, "用户偏好深色主题", "s2")
    results = search_memories(db, "深色主题")
    assert len(results) == 1
    assert results[0]["confidence"] > 0.5


def test_forget_matching_removes_entries(tmp_path):
    db = tmp_path / "memory.db"
    write_memory(db, "用户的手机号是13800000000", "s1")
    write_memory(db, "用户喜欢喝咖啡", "s1")
    removed = forget_matching(db, "手机号")
    assert removed == 1
    results = search_memories(db, "手机号")
    assert results == []


def test_clear_all_removes_everything(tmp_path):
    db = tmp_path / "memory.db"
    write_memory(db, "记忆一", "s1")
    write_memory(db, "记忆二", "s1")
    removed = clear_all(db)
    assert removed == 2
    assert search_memories(db, "记忆") == []


def test_stats_counts_by_tier(tmp_path):
    db = tmp_path / "memory.db"
    write_memory(db, "只提过一次的事", "s1")
    result = stats(db)
    assert result["observation"] + result["belief"] + result["fact"] + result["archived"] == 1
