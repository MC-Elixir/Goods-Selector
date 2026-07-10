from agent.env_file import set_env_values


def test_set_env_values_updates_existing_and_preserves_lines(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# comment\nMJJL_API_KEY=\nOTHER=value\n", encoding="utf-8")

    changed = set_env_values(env, {"MJJL_API_KEY": "secret", "MJJL_API_BASE": "https://api.example/v1"})

    assert changed == ["MJJL_API_KEY", "MJJL_API_BASE"]
    assert env.read_text(encoding="utf-8").splitlines() == [
        "# comment",
        "MJJL_API_KEY=secret",
        "OTHER=value",
        "MJJL_API_BASE=https://api.example/v1",
    ]


def test_set_env_values_quotes_values_when_needed(tmp_path):
    env = tmp_path / ".env"

    set_env_values(env, {"TOKEN": 'has space "quoted"'})

    assert env.read_text(encoding="utf-8") == 'TOKEN="has space \\"quoted\\""\n'
