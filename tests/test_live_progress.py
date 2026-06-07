"""Unit tests for live pipeline progress logging."""

from eval.live_progress import LivePipelineProgress


def test_progress_tracks_done_count():
    progress = LivePipelineProgress(expected_total=2)
    body = "[T-001] I forgot my password and got locked out after 3 tries."

    progress.started("BTS-1", body)
    progress.finished("BTS-1", body, action="RESOLVE", success=True)

    progress.started("BTS-2", body)
    progress.finished("BTS-2", body, action="RESOLVE", success=True)

    assert len(progress._completed) == 2
