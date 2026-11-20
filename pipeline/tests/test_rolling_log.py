import io

import rolling_log


def test_the_log_rolls_instead_of_growing_without_end(tmp_path, capsys):
    f = tmp_path / "crawl.log"
    lines = [f"project {i}/28101" for i in range(400)]
    rolling_log.tee(io.StringIO("\n".join(lines) + "\n"), f, keep_bytes=2000, keep_files=1)

    assert capsys.readouterr().out.splitlines() == lines  # a terminal still sees the crawl, line for line
    assert sorted(p.name for p in tmp_path.iterdir()) == ["crawl.log", "crawl.log.1"]  # two generations, no third
    assert all(p.stat().st_size <= 2000 + 64 for p in tmp_path.iterdir())  # a cap, plus the record that broke it
    kept = f.read_text() + (tmp_path / "crawl.log.1").read_text()
    assert lines[-1] in kept and lines[0] not in kept  # the newest lines survive and the oldest are gone


def test_every_line_is_stamped_so_a_slow_crawl_reads_differently_from_a_stopped_one(tmp_path):
    f = tmp_path / "crawl.log"
    rolling_log.tee(io.StringIO("list 7/120: 1680 projects\n"), f)
    line = f.read_text().strip()
    assert line.endswith(" list 7/120: 1680 projects")
    assert len(line.split(" list ")[0]) == len("11-21 01:41:07")
