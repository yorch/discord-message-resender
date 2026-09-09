from pathlib import Path

import pytest

from resender.config import ConfigError, Filters, load_routes

BASE = """
routes:
  - name: alpha
    source:
      guild_id: "100"
      channel_ids: ["200", "201"]
    target:
      webhook_url_env: HOOK_A
"""


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "routes.yaml"
    path.write_text(body)
    return path


def test_loads_route_and_resolves_webhook_from_env(tmp_path):
    routes = load_routes(write(tmp_path, BASE), {"HOOK_A": "https://discord.com/api/webhooks/1/x"})
    assert len(routes) == 1
    assert routes[0].name == "alpha"
    assert routes[0].channel_ids == {"200", "201"}
    assert routes[0].forwards is True


def test_missing_webhook_env_is_an_error_not_a_silent_archive(tmp_path):
    # Falling back to archive-only would look like it worked while quietly
    # forwarding nothing, which is the worst failure mode for an alert relay.
    with pytest.raises(ConfigError, match="HOOK_A"):
        load_routes(write(tmp_path, BASE), {})


def test_route_without_target_is_archive_only(tmp_path):
    body = """
routes:
  - name: archive
    source:
      guild_id: "100"
      channel_ids: ["200"]
"""
    routes = load_routes(write(tmp_path, body), {})
    assert routes[0].forwards is False


def test_unquoted_snowflake_round_trips_exactly(tmp_path):
    # Python ints are arbitrary precision, so a bare snowflake survives YAML
    # parsing intact. Both spellings must normalize to the same string.
    body = BASE.replace('["200", "201"]', "[1234567890123456789]")
    routes = load_routes(write(tmp_path, body), {"HOOK_A": "https://x/y"})
    assert routes[0].channel_ids == {"1234567890123456789"}


def test_non_numeric_channel_id_is_rejected(tmp_path):
    body = BASE.replace('["200", "201"]', '["<#200>"]')
    with pytest.raises(ConfigError, match="not a Discord ID"):
        load_routes(write(tmp_path, body), {"HOOK_A": "https://x/y"})


def test_duplicate_route_names_are_rejected(tmp_path):
    body = BASE + BASE.replace("routes:\n", "")
    with pytest.raises(ConfigError, match="duplicate route name"):
        load_routes(write(tmp_path, body), {"HOOK_A": "https://discord.com/api/webhooks/1/x"})


def test_disabled_routes_are_skipped(tmp_path):
    body = BASE.replace("    source:", "    enabled: false\n    source:")
    with pytest.raises(ConfigError, match="no enabled routes"):
        load_routes(write(tmp_path, body), {"HOOK_A": "https://x/y"})


def test_invalid_regex_is_reported_with_its_location(tmp_path):
    body = (
        BASE
        + """    filters:
      match_any: ["[unclosed"]
"""
    )
    with pytest.raises(ConfigError, match="invalid regular expression"):
        load_routes(write(tmp_path, body), {"HOOK_A": "https://x/y"})


def test_missing_file_points_at_the_example(tmp_path):
    with pytest.raises(ConfigError, match=r"routes\.example\.yaml"):
        load_routes(tmp_path / "absent.yaml", {})


class TestFilters:
    def test_empty_filters_allow_everything(self):
        assert Filters().allows("any", "anything") is True

    def test_author_allowlist(self):
        f = Filters(author_ids=frozenset({"7"}))
        assert f.allows("7", "text") is True
        assert f.allows("8", "text") is False

    def test_exclusion_vetoes_an_explicit_match(self):
        import re

        f = Filters(
            match_any=(re.compile("buy", re.I),),
            exclude_any=(re.compile("paper", re.I),),
        )
        assert f.allows("1", "BUY signal") is True
        assert f.allows("1", "BUY signal, paper trade only") is False
