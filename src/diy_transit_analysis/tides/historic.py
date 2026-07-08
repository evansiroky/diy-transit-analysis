"""Fetch historic transit performance data from Caltrans' TIDES portal.

ASSUMPTION, NOT VERIFIED AGAINST THE LIVE ENDPOINT: as of this writing,
tides.dds.dot.ca.gov publishes historic transit operations data as files in
a Google Cloud Storage *requester-pays* bucket rather than through a
conventional REST download API. A caller must supply their own
billing-enabled GCP project (`gcp_billing_project` in config) to cover
egress costs. This module is written against that understanding, based on
review of the TIDES portal's public documentation page and the TIDES
project's own spec suite (tides-transit.org) — NOT a working integration
test against a real bucket. Before relying on this for real reporting,
verify the actual bucket name, prefix/partitioning scheme, and file format
against the live endpoint, and update specs/architecture.md#tides-historic-
data-access accordingly.

Per specs/principles.md#fail-loud-on-unverified-assumptions: any failure
here (bucket not found, access denied, unexpected object layout) raises
TidesAccessError rather than silently returning an empty/partial result,
so a wrong assumption surfaces immediately instead of producing a
confident-looking but bogus report.
"""

from __future__ import annotations

from pathlib import Path

from google.api_core.exceptions import GoogleAPIError
from google.cloud import storage

from diy_transit_analysis.config import TidesConfig


class TidesAccessError(RuntimeError):
    """Raised when fetching TIDES data fails or returns something unexpected.

    Wraps the underlying Google Cloud Storage exception (if any) so callers
    get a stable, project-specific error type instead of having to catch
    google.cloud.exceptions directly.
    """


def fetch_historic(tides_config: TidesConfig, dest_dir: Path) -> list[Path]:
    """Download every TIDES object for this agency's configured bucket/prefix.

    Returns the list of local file paths written under dest_dir, preserving
    the objects' original names (see specs/data-model.md#tides-historic-
    data-on-disk-fetched). Raises TidesAccessError on any GCS-level failure
    or if the bucket/prefix yields zero objects (an empty result is treated
    as a likely sign the bucket-shape assumption above is wrong, not a
    legitimate "no data" case, for an MVP-scale single-quarter query).
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    try:
        client = storage.Client()
        bucket = client.bucket(tides_config.gcs_bucket, user_project=tides_config.gcp_billing_project)
        blobs = list(client.list_blobs(bucket, prefix=tides_config.agency_prefix))
    except (GoogleAPIError, OSError, EnvironmentError, ValueError) as exc:
        # Broad catch is deliberate: this includes google-cloud-storage's own
        # GoogleAPIError (bucket not found, access denied, ...) *and*
        # EnvironmentError from storage.Client() itself when no GCP
        # credentials/project are configured at all — both are equally a
        # sign the unverified TIDES access assumption below needs a human to
        # actually provision a GCP project and check the real bucket layout,
        # so both fail loudly as TidesAccessError rather than an unrelated
        # raw traceback or (worse) a silently empty result.
        raise TidesAccessError(
            f"failed to list objects in gs://{tides_config.gcs_bucket} "
            f"(prefix={tides_config.agency_prefix!r}), billed to project "
            f"{tides_config.gcp_billing_project!r}: {exc}. This may mean no "
            "GCP credentials/project are configured, or that the assumed "
            "TIDES bucket layout (see tides/historic.py module docstring "
            "and specs/architecture.md#tides-historic-data-access) no "
            "longer matches the live portal — verify against the live "
            "endpoint."
        ) from exc

    if not blobs:
        raise TidesAccessError(
            f"gs://{tides_config.gcs_bucket} (prefix={tides_config.agency_prefix!r}) "
            "returned zero objects. Either this agency genuinely has no TIDES "
            "data for the configured window, or (more likely for an unverified "
            "integration) the assumed bucket/prefix layout is wrong — see "
            "tides/historic.py module docstring."
        )

    written: list[Path] = []
    for blob in blobs:
        local_path = dest_dir / Path(blob.name).name
        try:
            blob.download_to_filename(str(local_path))
        except GoogleAPIError as exc:
            raise TidesAccessError(f"failed to download gs://{tides_config.gcs_bucket}/{blob.name}: {exc}") from exc
        written.append(local_path)

    return written
