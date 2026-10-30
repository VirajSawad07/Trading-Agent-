import sys
from unittest.mock import patch

import pytest

from src import download_data


def test_no_mt5_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.yaml").write_text(f"paths:\n  raw_data_dir: {tmp_path.as_posix()}/raw\n")
    monkeypatch.setattr(sys, "argv", ["download_data"])
    with patch.object(download_data.MT5Connector, "connect", return_value=False):
        with pytest.raises(SystemExit):
            download_data.main()
    assert list((tmp_path / "raw").iterdir()) == []


def test_forced_sample_is_labelled_synthetic(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.yaml").write_text(f"paths:\n  raw_data_dir: {tmp_path.as_posix()}/raw\n")
    monkeypatch.setattr(sys, "argv", ["download_data", "--force-sample", "--bars", "50"])
    download_data.main()
    assert [f.name for f in (tmp_path / "raw").iterdir()] == ["XAUUSD_M15_SYNTHETIC.csv"]
