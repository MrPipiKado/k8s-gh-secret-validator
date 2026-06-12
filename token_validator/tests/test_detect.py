import pytest

from token_validator.detect import detect_type, is_github_token


@pytest.mark.parametrize("token,expected", [
    ("ghp_abc", "classic PAT"),
    ("github_pat_abc", "fine-grained PAT"),
    ("gho_abc", "OAuth token"),
    ("ghu_abc", "user-to-server token"),
    ("ghs_abc", "app installation token"),
    ("ghr_abc", "refresh token"),
    ("dckr_pat_abc", "unknown"),
])
def test_detect_type(token, expected):
    assert detect_type(token) == expected


def test_is_github_token():
    assert is_github_token("ghp_abc")
    assert not is_github_token("dckr_pat_abc")
