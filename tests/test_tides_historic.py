from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from google.api_core.exceptions import NotFound

from diy_transit_analysis.config import TidesConfig
from diy_transit_analysis.tides.historic import TidesAccessError, fetch_historic


def _tides_config() -> TidesConfig:
    return TidesConfig(gcs_bucket="a-bucket", gcp_billing_project="a-project", agency_prefix="Foo")


@patch("diy_transit_analysis.tides.historic.storage.Client")
def test_fetch_historic_raises_tides_access_error_on_gcs_failure(mock_client_cls, tmp_path: Path):
    mock_client = MagicMock()
    mock_client.list_blobs.side_effect = NotFound("bucket not found")
    mock_client_cls.return_value = mock_client

    with pytest.raises(TidesAccessError, match="failed to list objects"):
        fetch_historic(_tides_config(), tmp_path)


@patch("diy_transit_analysis.tides.historic.storage.Client")
def test_fetch_historic_raises_on_empty_bucket_result(mock_client_cls, tmp_path: Path):
    mock_client = MagicMock()
    mock_client.list_blobs.return_value = []
    mock_client_cls.return_value = mock_client

    with pytest.raises(TidesAccessError, match="zero objects"):
        fetch_historic(_tides_config(), tmp_path)


@patch("diy_transit_analysis.tides.historic.storage.Client")
def test_fetch_historic_downloads_each_blob(mock_client_cls, tmp_path: Path):
    blob = MagicMock()
    blob.name = "Foo/2026-01-05.csv"

    def _download(local_path):
        Path(local_path).write_text("route_id,trip_id\n")

    blob.download_to_filename.side_effect = _download

    mock_client = MagicMock()
    mock_client.list_blobs.return_value = [blob]
    mock_client_cls.return_value = mock_client

    written = fetch_historic(_tides_config(), tmp_path)

    assert len(written) == 1
    assert written[0].name == "2026-01-05.csv"
    assert written[0].exists()
