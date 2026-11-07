"""Bounded per-run rotation of EventLogger JSONL files."""

import json
from datetime import datetime, timedelta

from multi_coin_grid_pro.core.reason_codes import ReasonCode, Stage
from multi_coin_grid_pro.observability.event_aggregator import AggregationPeriod, EventAggregator
from multi_coin_grid_pro.observability.event_logger import EventLogger


def _logger(tmp_path, **kwargs):
    return EventLogger(enabled=True, output_dir=str(tmp_path), buffer_size=1000, **kwargs)


def _emit_n(el, n):
    for i in range(n):
        el.emit_gate_denied(f"cid-{i}", f"C{i}-USDT", Stage.RISK, ReasonCode.INSUFFICIENT_RISK_BUDGET,
                            "headroom below minimum viable grid", metadata={"seq": i}, connector="bitget")
    el.flush()


def _seqs(path_list):
    out = []
    for p in path_list:
        for line in p.read_text().splitlines():
            out.append(json.loads(line)["metadata"]["seq"])
    return out


def test_rotates_at_size_limit_without_losing_or_splitting_lines(tmp_path):
    el = _logger(tmp_path, max_file_bytes=1000, max_files_per_run=100)
    _emit_n(el, 40)
    el.close()

    files = sorted(tmp_path.glob("events_*.jsonl"))
    assert len(files) > 1
    assert files[0].name == f"{el._run_stem}.jsonl"
    assert files[1].name == f"{el._run_stem}_p001.jsonl"
    for f in files:
        assert f.stat().st_size <= 1000
    # every line is valid JSON and the order across parts is preserved
    assert _seqs(files) == list(range(40))


def test_part_cap_deletes_only_oldest_parts_of_current_run(tmp_path):
    other_run = tmp_path / "events_20200101_000000.jsonl"
    other_run.write_text('{"metadata": {"seq": -1}}\n')

    el = _logger(tmp_path, max_file_bytes=600, max_files_per_run=3)
    _emit_n(el, 60)
    el.close()

    own = sorted(p for p in tmp_path.glob(f"{el._run_stem}*.jsonl"))
    assert len(own) == 3
    assert other_run.exists(), "files of other runs must never be deleted"
    seqs = _seqs(own)
    assert seqs == sorted(seqs) and seqs[-1] == 59, "newest events kept, in order"
    assert seqs[0] > 0, "oldest part of this run was dropped"


def test_aggregator_reads_events_across_rotated_parts(tmp_path):
    el = _logger(tmp_path, max_file_bytes=700, max_files_per_run=100)
    _emit_n(el, 25)
    el.close()
    assert len(list(tmp_path.glob("events_*.jsonl"))) > 1

    now = datetime.now()
    summary = EventAggregator(tmp_path)._aggregate_period(
        AggregationPeriod(now - timedelta(hours=1), now + timedelta(minutes=1)))
    assert summary.denied == 25
    assert summary.total_intents == 25


def test_rotation_failure_is_non_fatal(tmp_path, monkeypatch):
    el = _logger(tmp_path, max_file_bytes=300, max_files_per_run=5)
    _emit_n(el, 2)

    import builtins
    real_open = builtins.open

    def failing_open(path, *a, **k):
        if "_p" in str(path):
            raise OSError("disk full")
        return real_open(path, *a, **k)

    monkeypatch.setattr(builtins, "open", failing_open)
    _emit_n(el, 20)  # must not raise
    _emit_n(el, 5)   # logger degraded: drops events quietly, no exception
    assert el.buffer == []
    monkeypatch.setattr(builtins, "open", real_open)
    el.close()


def test_defaults_bound_a_run_to_100_mb(tmp_path):
    el = _logger(tmp_path)
    assert el.max_file_bytes * el.max_files_per_run == 100 * 1024 * 1024
    el.close()
