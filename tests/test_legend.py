"""Phase 1b: centralized legend ids."""

from analytics.legend import LEGENDS, subtitle


def test_all_legend_ids_resolve():
    for key in LEGENDS:
        assert isinstance(subtitle(key), str)
        assert len(subtitle(key)) > 10
