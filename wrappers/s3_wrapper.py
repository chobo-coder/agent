"""S3 parquet reader."""

import pandas as pd
import boto3

import config


class S3Wrapper:
    """Reads parquet files from S3."""

    def __init__(self):
        self._bucket = config.S3_BUCKET
        self._client = boto3.client("s3", region_name=config.S3_REGION)

    def read_parquet(self, prefix: str) -> pd.DataFrame:
        """Read all parquet files under a prefix and concatenate.

        TODO: Replace with actual S3 read logic.
        """
        raise NotImplementedError(
            "Replace with actual S3 parquet reading: "
            "e.g., pd.read_parquet(f's3://{bucket}/{prefix}')"
        )

    def list_files(self, prefix: str) -> list[str]:
        """List parquet files under the given prefix."""
        response = self._client.list_objects_v2(Bucket=self._bucket, Prefix=prefix)
        return [
            obj["Key"]
            for obj in response.get("Contents", [])
            if obj["Key"].endswith(".parquet")
        ]
